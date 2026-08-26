"""Score conversion engine — ported from YAVSRG Interlude Scoring.fs."""
from __future__ import annotations

import struct
from math import exp
from typing import Any, Optional, TYPE_CHECKING

from nonebot.log import logger

from ...parser.osu_file_parser import NOTE_HOLD_HEAD, NOTE_HOLD_TAIL, NOTE_NORMAL

if TYPE_CHECKING:
    from ...parser.ruleset_file_parser import ruleset_file

# 参考内容:
# - YAVSRG/prelude/src/Gameplay/Scoring/Scoring.fs
# - YAVSRG/prelude/src/Gameplay/Scoring/OsuHolds.fs
# - YAVSRG/prelude/src/Gameplay/Scoring/Lamps.fs
# - YAVSRG/prelude/src/Gameplay/Scoring/Grades.fs
# - YAVSRG/prelude/src/Gameplay/Scoring/WifeCurve.fs

_REQUIRED_MATCH_KEYS = {
    "matched_events",
    "events_f",
    "offset_vector",
    "delta_list",
    "matched_pairs",
    "unmatched_presses",
    "unmatched_notes",
    "note_count",
    "press_count",
    "meta",
}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _f32(value: float) -> float:
    """IEEE-754 binary32 round trip (F# float32 judgement window semantics)."""
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def _safe_judgement_index(value: Any, judgement_len: int, miss_index: int) -> int:
    idx = _to_int(value, miss_index)
    if judgement_len <= 0:
        return 0
    if idx < 0:
        return 0
    if idx >= judgement_len:
        return judgement_len - 1
    return idx


def _empty_report(
    status: str,
    error: Optional[str],
    *,
    judgements_len: int = 0,
    match_result: Optional[dict[str, Any]] = None,
    warnings: Optional[list[str]] = None,
) -> dict[str, Any]:
    report = {
        "status": status,
        "error": error,
        "accuracy_fraction": 0.0,
        "points_sum": 0.0,
        "max_points": 0.0,
        "judgement_counts": [0 for _ in range(max(0, judgements_len))],
        "per_note": [],
        "matched_events": [],
        "offset_vector": [],
        "delta_list": [],
        "matched_pairs": [],
        "unmatched_presses": [],
        "unmatched_notes": [],
        "note_count": 0,
        "press_count": 0,
        "combo": {
            "best_combo": 0,
            "combo_breaks": 0,
        },
        "lamps": {},
        "lamp": "",
        "lamp_index": -1,
        "grade": {
            "name": "",
            "accuracy_threshold": 0.0,
        },
        "grade_index": -1,
        "meta": {
            "speed_factor": 1.0,
            "scale_applied": False,
            "note_priority": "OsuMania",
            "algorithm_version": "interlude_v1_score_v2",
        },
        "warnings": list(warnings or []),
    }

    if isinstance(match_result, dict):
        report["matched_events"] = list(match_result.get("matched_events", []) or [])
        report["offset_vector"] = list(match_result.get("offset_vector", []) or [])
        report["delta_list"] = list(match_result.get("delta_list", []) or [])
        report["matched_pairs"] = list(match_result.get("matched_pairs", []) or [])
        report["unmatched_presses"] = list(match_result.get("unmatched_presses", []) or [])
        report["unmatched_notes"] = list(match_result.get("unmatched_notes", []) or [])
        report["note_count"] = _to_int(match_result.get("note_count", 0), 0)
        report["press_count"] = _to_int(match_result.get("press_count", 0), 0)

        meta = match_result.get("meta")
        if isinstance(meta, dict):
            report["meta"].update(
                {
                    "speed_factor": _to_float(meta.get("speed_factor", 1.0), 1.0),
                    "scale_applied": bool(meta.get("scale_applied", False)),
                    "note_priority": meta.get("note_priority", "OsuMania"),
                }
            )

    return report


def _ms_to_judgement(delta: float, judgements: list[dict[str, Any]]) -> int:
    """Judgement ms_to_judgement (Scoring.fs): first window containing delta.

    Judgements with no explicit window are skipped; the last judgement is the
    catch-all.  Comparisons run in float32 like the F# engine.
    """
    j = 0
    while j + 1 < len(judgements):
        tw = judgements[j].get("TimingWindows")
        if not isinstance(tw, list) or len(tw) != 2 or not _is_number(tw[0]) or not _is_number(tw[1]):
            j += 1
        elif delta < _f32(float(tw[0])) or delta > _f32(float(tw[1])):
            j += 1
        else:
            break
    return j


def _points_for_event_by_points_per_judgement(j_idx: int, points_array: list[float]) -> float:
    if not points_array:
        return 0.0
    if j_idx < 0:
        return float(points_array[0])
    if j_idx >= len(points_array):
        return float(points_array[-1])
    return float(points_array[j_idx])


def _erf_approx(x: float) -> float:
    a1 = 0.254829592
    a2 = -0.284496736
    a3 = 1.421413741
    a4 = -1.453152027
    a5 = 1.061405429
    p = 0.3275911

    sign = -1.0 if x < 0.0 else 1.0
    x_abs = abs(x)
    t = 1.0 / (1.0 + p * x_abs)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * exp(-(x_abs * x_abs))
    return sign * y


def _wife3_points(judge: int, delta: float) -> float:
    """Wife3Curve.calculate (WifeCurve.fs) verbatim; delta is GameplayTime."""
    delta = abs(float(delta))
    scale = (10.0 - float(judge)) / 6.0
    miss_weight = -2.75
    ridic = 5.0 * scale
    boo_window = 180.0 * scale
    ts_pow = 0.75
    zero = 65.0 * (scale ** ts_pow)
    dev = 22.7 * (scale ** ts_pow)

    if delta <= ridic:
        return 1.0
    if delta <= zero:
        return _erf_approx((zero - delta) / dev)
    if delta <= boo_window:
        return (delta - zero) * miss_weight / (boo_window - zero)
    return miss_weight


def _check_single_requirement(
    req: dict[str, Any],
    judgement_counts: list[int],
    combo_breaks: int,
    accuracy: Optional[float],
) -> bool:
    checks_present = 0
    checks_passed = 0

    if "ComboBreaksAtMost" in req:
        checks_present += 1
        limit = req.get("ComboBreaksAtMost")
        if isinstance(limit, int) and combo_breaks <= limit:
            checks_passed += 1

    if "JudgementAtMost" in req:
        checks_present += 1
        entry = req.get("JudgementAtMost")
        if isinstance(entry, list) and len(entry) == 2 and isinstance(entry[0], int) and isinstance(entry[1], int):
            j_idx = entry[0]
            limit = entry[1]
            if 0 <= j_idx < len(judgement_counts) and judgement_counts[j_idx] <= limit:
                checks_passed += 1

    if "Accuracy" in req:
        checks_present += 1
        threshold = req.get("Accuracy")
        if _is_number(threshold) and accuracy is not None and accuracy >= float(threshold):
            checks_passed += 1

    return checks_present > 0 and checks_present == checks_passed


def _evaluate_requirement(
    req: Any,
    judgement_counts: list[int],
    combo_breaks: int,
    accuracy: Optional[float],
) -> bool:
    if isinstance(req, list):
        if not req:
            return False
        return all(
            _check_single_requirement(r, judgement_counts, combo_breaks, accuracy)
            if isinstance(r, dict)
            else False
            for r in req
        )
    if isinstance(req, dict):
        return _check_single_requirement(req, judgement_counts, combo_breaks, accuracy)
    return False


def _evaluate_lamps(
    lamps_config: list[dict[str, Any]],
    judgement_counts: list[int],
    combo_breaks: int,
    accuracy: Optional[float] = None,
) -> tuple[dict[str, bool], str]:
    lamps: dict[str, bool] = {}
    judgement_candidates: list[tuple[int, int, str]] = []
    judgement_fallback_candidates: list[tuple[int, str]] = []
    combo_candidates: list[tuple[int, str]] = []

    for lamp in lamps_config:
        if not isinstance(lamp, dict):
            continue
        name = str(lamp.get("Name", "")).strip()
        if not name:
            continue

        req = lamp.get("Requirement")
        ok = _evaluate_requirement(req, judgement_counts, combo_breaks, accuracy)
        lamps[name] = ok

        if not ok:
            continue

        reqs = req if isinstance(req, list) else ([req] if isinstance(req, dict) else [])
        for r in reqs:
            if not isinstance(r, dict):
                continue
            if "JudgementAtMost" in r:
                entry = r.get("JudgementAtMost")
                if isinstance(entry, list) and len(entry) == 2 and isinstance(entry[0], int) and isinstance(entry[1], int):
                    j_idx = entry[0]
                    limit = entry[1]
                    if 0 <= j_idx < len(judgement_counts):
                        judgement_candidates.append((j_idx, limit, name))
                    judgement_fallback_candidates.append((min(j_idx, limit), name))
            if "ComboBreaksAtMost" in r:
                limit = r.get("ComboBreaksAtMost")
                if isinstance(limit, int):
                    combo_candidates.append((limit, name))

    if judgement_candidates:
        chosen = min(judgement_candidates, key=lambda item: (item[0], item[1], item[2]))
        return lamps, chosen[2]

    if judgement_fallback_candidates:
        chosen = min(judgement_fallback_candidates, key=lambda item: (item[0], item[1]))
        return lamps, chosen[1]

    if combo_candidates:
        chosen = min(combo_candidates, key=lambda item: (item[0], item[1]))
        return lamps, chosen[1]

    return lamps, ""


def _pick_grade(
    grades_config: list[dict[str, Any]],
    accuracy: float,
    judgement_counts: Optional[list[int]] = None,
    combo_breaks: int = 0,
) -> tuple[str, float]:
    jc = judgement_counts if judgement_counts is not None else []
    best_idx = -1
    best_name = ""
    best_acc = 0.0

    for idx, item in enumerate(grades_config):
        if not isinstance(item, dict):
            continue
        name = str(item.get("Name", "")).strip()
        if not name:
            continue

        achieved = False
        grade_acc = 0.0

        if "Requirement" in item:
            req = item.get("Requirement")
            if _evaluate_requirement(req, jc, combo_breaks, accuracy):
                achieved = True
                grade_acc = _to_float(item.get("Accuracy", 1.0), 1.0)
        elif "Accuracy" in item:
            threshold = item.get("Accuracy")
            if _is_number(threshold):
                grade_acc = float(threshold)
                if accuracy >= grade_acc:
                    achieved = True

        if achieved and idx > best_idx:
            best_idx = idx
            best_name = name
            best_acc = grade_acc

    if best_idx >= 0:
        return best_name, best_acc

    if grades_config and isinstance(grades_config[0], dict):
        first_name = str(grades_config[0].get("Name", "")).strip()
        return first_name, 0.0
    return "", 0.0


def _extract_hold_variant(hold_mechanics: Any) -> tuple[str, Any]:
    if isinstance(hold_mechanics, dict) and len(hold_mechanics) == 1:
        return next(iter(hold_mechanics.items()))
    return "OnlyRequireHold", 120.0


def _lamp_calculate(lamps_config: list[dict[str, Any]], judgement_counts: list[int], combo_breaks: int) -> int:
    """Lamp.calculate (Lamps.fs) verbatim for the shared-subset schema."""
    worst_judgement = -1
    for i, count in enumerate(judgement_counts):
        if count > 0:
            worst_judgement = i

    achieved = -1
    while achieved + 1 < len(lamps_config):
        lamp = lamps_config[achieved + 1]
        req = lamp.get("Requirement") if isinstance(lamp, dict) else None
        if isinstance(req, list) or not isinstance(req, dict):
            break
        if "ComboBreaksAtMost" in req and isinstance(req["ComboBreaksAtMost"], int):
            if combo_breaks > int(req["ComboBreaksAtMost"]):
                break
        elif "JudgementAtMost" in req and isinstance(req["JudgementAtMost"], list) and len(req["JudgementAtMost"]) == 2:
            judgement, threshold = int(req["JudgementAtMost"][0]), int(req["JudgementAtMost"][1])
            if worst_judgement > judgement:
                break
            if judgement < len(judgement_counts) and judgement_counts[judgement] > threshold:
                break
        achieved += 1
    return achieved


def _grade_calculate(grades_config: list[dict[str, Any]], accuracy: float) -> int:
    """Grade.calculate (Grades.fs) verbatim: accuracy-only thresholds from -1."""
    achieved = -1
    while achieved + 1 < len(grades_config):
        item = grades_config[achieved + 1]
        if not isinstance(item, dict) or "Accuracy" not in item or not _is_number(item.get("Accuracy")):
            break
        if float(item["Accuracy"]) - accuracy > 0.0:
            break
        achieved += 1
    return achieved


def _ruleset_uses_superset_constructs(ruleset_data: dict[str, Any]) -> bool:
    """True when the ruleset relies on plugin-only extensions (interlude cannot express them)."""
    grades = ruleset_data.get("Grades") if isinstance(ruleset_data.get("Grades"), list) else []
    for grade in grades:
        if isinstance(grade, dict) and "Requirement" in grade:
            return True
    lamps = ruleset_data.get("Lamps") if isinstance(ruleset_data.get("Lamps"), list) else []
    for lamp in lamps:
        if not isinstance(lamp, dict):
            continue
        req = lamp.get("Requirement")
        if isinstance(req, list):
            return True
        if isinstance(req, dict) and "Accuracy" in req:
            return True
    return False


def _ln_judgement_osu(
    windows: dict[str, Any],
    head_delta: float,
    release_delta: float,
    overheld: bool,
    dropped: bool,
) -> int:
    """OsuHolds.ln_judgement (OsuHolds.fs) verbatim."""
    release_delta_abs = abs(release_delta)
    head_delta_abs = abs(head_delta)

    def w(name: str) -> float:
        value = windows.get(name)
        return _to_float(value, 0.0)

    if overheld:
        if head_delta_abs < w("WindowOverhold200"):
            return 2
        if head_delta_abs < w("WindowOverhold100"):
            return 3
        return 4
    if dropped:
        return 5 if release_delta < -w("Window50") else 4
    mean = (release_delta_abs + head_delta_abs) * 0.5
    if release_delta < -w("Window50"):
        return 5
    if head_delta_abs < w("Window320") and mean < w("Window320"):
        return 0
    if head_delta_abs < w("Window300") and mean < w("Window300"):
        return 1
    if head_delta_abs < w("Window200") and mean < w("Window200"):
        return 2
    if head_delta_abs < w("Window100") and mean < w("Window100"):
        return 3
    return 4


def _release_judgement_from_windows(release_delta: float, windows: list[Any], miss_index: int) -> int:
    """Release window scan (ProcessRelease -> JudgeReleasesSeparately) verbatim."""
    j = 0
    while j + 1 < len(windows):
        window = windows[j]
        if not isinstance(window, list) or len(window) != 2 or not _is_number(window[0]) or not _is_number(window[1]):
            j += 1
        elif release_delta < _f32(float(window[0])) or release_delta > _f32(float(window[1])):
            j += 1
        else:
            break
    return min(j, max(0, miss_index if miss_index >= len(windows) else len(windows) - 1))


def get_score_result(
    ruleset: "ruleset_file",
    match_result: dict,
    *,
    prefer_points_per_judgement: bool = True,
    judge_scale: float | None = None,
) -> dict:
    """Build a score report from ruleset.raw_data and match_notes_and_presses output."""

    warnings: list[str] = []

    try:
        if ruleset is None or not hasattr(ruleset, "raw_data"):
            return _empty_report("InvalidInput", "ruleset is invalid")

        ruleset_data = getattr(ruleset, "raw_data", None)
        if not isinstance(ruleset_data, dict):
            return _empty_report("InvalidInput", "ruleset.raw_data must be dict")

        if not isinstance(match_result, dict):
            return _empty_report("InvalidInput", "match_result must be dict")

        missing_keys = sorted(k for k in _REQUIRED_MATCH_KEYS if k not in match_result)
        if missing_keys:
            return _empty_report(
                "InvalidInput",
                f"match_result missing keys: {', '.join(missing_keys)}",
                match_result=match_result,
            )

        judgements = ruleset_data.get("Judgements")
        if not isinstance(judgements, list) or not judgements:
            return _empty_report("InvalidInput", "Judgements is empty", match_result=match_result)

        judgement_len = len(judgements)
        miss_index = judgement_len - 1

        note_count = _to_int(match_result.get("note_count", 0), 0)
        press_count = _to_int(match_result.get("press_count", 0), 0)

        superset = _ruleset_uses_superset_constructs(ruleset_data)

        accuracy_config = ruleset_data.get("Accuracy") if isinstance(ruleset_data.get("Accuracy"), dict) else {}
        points_array: list[float] = []
        wife_version: Optional[int] = None
        if isinstance(accuracy_config.get("PointsPerJudgement"), list):
            points_array = [float(v) for v in accuracy_config["PointsPerJudgement"]]
            if len(points_array) != judgement_len:
                warnings.append("PointsPerJudgement 长度与 Judgements 不一致，按 clamp 取值")
        elif isinstance(accuracy_config.get("WifeCurve"), int):
            wife_version = int(accuracy_config["WifeCurve"])
            if wife_version < 2 or wife_version > 9:
                warnings.append(f"WifeCurve judge={wife_version} 超出常规范围 2..9")
        use_wife = wife_version is not None

        hold_mechanics = ruleset_data.get("HoldMechanics")
        hold_variant, hold_payload = _extract_hold_variant(hold_mechanics)

        hit_mechanics = ruleset_data.get("HitMechanics") if isinstance(ruleset_data.get("HitMechanics"), dict) else {}
        ghost_tap_judgement: Optional[int] = None
        ghost_raw = hit_mechanics.get("GhostTapJudgement") if isinstance(hit_mechanics, dict) else None
        if isinstance(ghost_raw, int):
            ghost_tap_judgement = ghost_raw

        events = list(match_result.get("events_f", []) or [])

        judgement_counts = [0 for _ in range(judgement_len)]
        points_sum = 0.0
        max_points = 0.0
        combo = 0
        best_combo = 0
        combo_breaks = 0
        max_possible_combo = 0
        per_note: list[dict[str, Any]] = []

        def score_event(j: int, points: float) -> None:
            nonlocal points_sum, max_points
            judgement_counts[j] += 1
            points_sum += points
            max_points += 1.0

        def points_for(j: int, delta: float) -> float:
            if use_wife:
                return _wife3_points(int(wife_version), delta)
            return _points_for_event_by_points_per_judgement(j, points_array)

        def judgement_breaks_combo(j: int) -> bool:
            if 0 <= j < judgement_len and isinstance(judgements[j], dict):
                return bool(judgements[j].get("BreaksCombo", False))
            return False

        for ev in events:
            if not isinstance(ev, dict):
                continue
            action = str(ev.get("action", "")).upper()
            event_index = _to_int(ev.get("index", -1), -1)
            event_time = _to_float(ev.get("time", 0.0), 0.0)
            delta = ev.get("delta")
            delta_f = _to_float(delta, 0.0) if delta is not None else None
            missed = bool(ev.get("missed", False))
            overhold = bool(ev.get("overhold", False))
            dropped = bool(ev.get("dropped", False))
            missed_head = bool(ev.get("missed_head", False))

            combo_action: str = "increase"
            break_increases_max: bool = True
            judgement_index: Optional[int] = None
            points: Optional[float] = None

            if action == "HIT":
                if hold_variant == "OnlyJudgeReleases":
                    combo_action = "break" if missed else "increase"
                else:
                    j = miss_index if missed else _ms_to_judgement(delta_f, judgements)
                    p = points_for(j, delta_f)
                    score_event(j, p)
                    judgement_index = j
                    points = p
                    combo_action = "break" if judgement_breaks_combo(j) else "increase"
                per_note.append(
                    {
                        "index": event_index,
                        "time": event_time,
                        "column": _to_int(ev.get("column", -1), -1),
                        "note_kind": NOTE_NORMAL,
                        "action": action,
                        "final_judgement_index": judgement_index,
                        "points": 0.0 if points is None else points,
                        "source": "hit",
                    }
                )

            elif action == "HOLD":
                if hold_variant in ("OnlyRequireHold", "JudgeReleasesSeparately"):
                    j = miss_index if missed else _ms_to_judgement(delta_f, judgements)
                    p = points_for(j, delta_f)
                    score_event(j, p)
                    judgement_index = j
                    points = p
                    combo_action = "break" if judgement_breaks_combo(j) else "increase"
                else:
                    combo_action = "break" if missed else "increase"
                per_note.append(
                    {
                        "index": event_index,
                        "time": event_time,
                        "column": _to_int(ev.get("column", -1), -1),
                        "note_kind": NOTE_HOLD_HEAD,
                        "action": action,
                        "final_judgement_index": judgement_index,
                        "points": 0.0 if points is None else points,
                        "source": "hold_head",
                    }
                )

            elif action == "RELEASE":
                head_delta = ev.get("head_delta")
                head_delta_f = _to_float(head_delta, 0.0) if head_delta is not None else delta_f
                release_delta = _to_float(delta, 0.0)
                j: Optional[int] = None
                if hold_variant == "CombineHeadAndTail" and isinstance(hold_payload, dict) and len(hold_payload) == 1:
                    sub_variant, sub_payload = next(iter(hold_payload.items()))
                    if sub_variant == "OsuMania" and isinstance(sub_payload, dict):
                        if missed and missed_head and not overhold:
                            j = miss_index
                        else:
                            j = _ln_judgement_osu(sub_payload, head_delta_f, release_delta, overhold, dropped)
                        p = points_for(j, release_delta)
                        score_event(j, p)
                        judgement_index = j
                        points = p
                        combo_action = "break" if judgement_breaks_combo(j) else "increase"
                    elif sub_variant == "HeadJudgementOr" and isinstance(sub_payload, list) and len(sub_payload) == 4:
                        head_j = _ms_to_judgement(head_delta_f, judgements)
                        dropped_idx = _safe_judgement_index(sub_payload[2], judgement_len, miss_index)
                        overheld_idx = _safe_judgement_index(sub_payload[3], judgement_len, miss_index)
                        if missed_head and missed:
                            j = miss_index
                        elif overhold and not dropped:
                            j = max(head_j, overheld_idx)
                        elif dropped:
                            j = max(head_j, dropped_idx)
                        else:
                            j = head_j
                        p = points_for(j, release_delta)
                        score_event(j, p)
                        judgement_index = j
                        points = p
                        combo_action = "break" if judgement_breaks_combo(j) else "increase"
                    else:
                        combo_action = "break" if missed else "increase"
                elif hold_variant == "OnlyRequireHold":
                    combo_action = "break" if (not overhold) and (missed or dropped) else "increase"
                elif hold_variant == "JudgeReleasesSeparately" and isinstance(hold_payload, list) and len(hold_payload) == 2:
                    release_windows = hold_payload[0]
                    overheld_idx = (
                        _safe_judgement_index(hold_payload[1], judgement_len, miss_index)
                        if isinstance(hold_payload[1], int)
                        else miss_index
                    )
                    if dropped:
                        j = miss_index
                    elif overhold:
                        j = overheld_idx
                    elif missed:
                        j = miss_index
                    else:
                        j = _release_judgement_from_windows(release_delta, release_windows, miss_index)
                    p = points_for(j, release_delta)
                    score_event(j, p)
                    judgement_index = j
                    points = p
                    combo_action = "break" if judgement_breaks_combo(j) else "increase"
                elif hold_variant == "OnlyJudgeReleases":
                    dropped_idx = (
                        _safe_judgement_index(hold_payload, judgement_len, miss_index)
                        if isinstance(hold_payload, int)
                        else miss_index
                    )
                    if missed:
                        j = miss_index
                    else:
                        j = _ms_to_judgement(release_delta, judgements)
                        if dropped or overhold:
                            j = max(j, dropped_idx)
                    p = points_for(j, release_delta)
                    score_event(j, p)
                    judgement_index = j
                    points = p
                    combo_action = "break" if judgement_breaks_combo(j) else "increase"
                else:
                    combo_action = "break" if missed else "increase"
                per_note.append(
                    {
                        "index": event_index,
                        "time": event_time,
                        "column": _to_int(ev.get("column", -1), -1),
                        "note_kind": NOTE_HOLD_TAIL,
                        "action": action,
                        "final_judgement_index": judgement_index,
                        "points": 0.0 if points is None else points,
                        "source": "hold_release",
                    }
                )

            elif action == "DROP_HOLD":
                combo_action = "break"
                break_increases_max = False
                per_note.append(
                    {
                        "index": event_index,
                        "time": event_time,
                        "column": _to_int(ev.get("column", -1), -1),
                        "note_kind": NOTE_HOLD_TAIL,
                        "action": action,
                        "final_judgement_index": None,
                        "points": 0.0,
                        "source": "drop_hold",
                    }
                )

            elif action == "REGRAB_HOLD":
                combo_action = "nochange"

            elif action == "GHOST_TAP":
                if ghost_tap_judgement is not None and 0 <= ghost_tap_judgement < judgement_len:
                    j = ghost_tap_judgement
                    p = points_for(j, 0.0)
                    score_event(j, p)
                    judgement_index = j
                    points = p
                    combo_action = "break" if judgement_breaks_combo(j) else "nochange"
                    per_note.append(
                        {
                            "index": event_index,
                            "time": event_time,
                            "column": _to_int(ev.get("column", -1), -1),
                            "note_kind": 0,
                            "action": action,
                            "final_judgement_index": judgement_index,
                            "points": points,
                            "source": "ghost",
                        }
                    )
                else:
                    combo_action = "nochange"
            else:
                continue

            if combo_action == "increase":
                combo += 1
                best_combo = max(best_combo, combo)
                max_possible_combo += 1
            elif combo_action == "break":
                combo_breaks += 1
                combo = 0
                if break_increases_max:
                    max_possible_combo += 1
            # nochange: nothing

        accuracy_fraction = 1.0 if max_points == 0.0 else points_sum / max_points

        lamps_config = ruleset_data.get("Lamps") if isinstance(ruleset_data.get("Lamps"), list) else []
        grades_config = ruleset_data.get("Grades") if isinstance(ruleset_data.get("Grades"), list) else []

        lamps: dict[str, bool] = {}
        lamp_name = ""
        lamp_index = -1
        grade_name = ""
        grade_threshold = 0.0
        grade_index = -1

        if superset:
            lamps, lamp_name = _evaluate_lamps(lamps_config, judgement_counts, combo_breaks, accuracy_fraction)
            grade_name, grade_threshold = _pick_grade(grades_config, accuracy_fraction, judgement_counts, combo_breaks)
        else:
            lamp_index = _lamp_calculate(lamps_config, judgement_counts, combo_breaks)
            grade_index = _grade_calculate(grades_config, accuracy_fraction)
            if 0 <= lamp_index < len(lamps_config) and isinstance(lamps_config[lamp_index], dict):
                lamp_name = str(lamps_config[lamp_index].get("Name", "")).strip()
            for idx, lamp in enumerate(lamps_config):
                if isinstance(lamp, dict):
                    lamps[str(lamp.get("Name", "")).strip()] = idx <= lamp_index
            if 0 <= grade_index < len(grades_config) and isinstance(grades_config[grade_index], dict):
                grade_name = str(grades_config[grade_index].get("Name", "")).strip()
                grade_threshold = _to_float(grades_config[grade_index].get("Accuracy", 0.0), 0.0)

        return {
            "status": "OK",
            "error": None,
            "accuracy_fraction": accuracy_fraction,
            "points_sum": points_sum,
            "max_points": max_points,
            "judgement_counts": judgement_counts,
            "per_note": per_note,
            "matched_events": list(match_result.get("matched_events", []) or []),
            "events_f": list(match_result.get("events_f", []) or []),
            "offset_vector": list(match_result.get("offset_vector", []) or []),
            "delta_list": list(match_result.get("delta_list", []) or []),
            "matched_pairs": list(match_result.get("matched_pairs", []) or []),
            "unmatched_presses": list(match_result.get("unmatched_presses", []) or []),
            "unmatched_notes": list(match_result.get("unmatched_notes", []) or []),
            "note_count": note_count,
            "press_count": press_count,
            "combo": {
                "best_combo": best_combo,
                "combo_breaks": combo_breaks,
            },
            "lamps": lamps,
            "lamp": lamp_name,
            "lamp_index": lamp_index,
            "grade": {
                "name": grade_name,
                "accuracy_threshold": grade_threshold,
            },
            "grade_index": grade_index,
            "meta": {
                "speed_factor": _to_float(match_result.get("meta", {}).get("speed_factor", 1.0), 1.0),
                "scale_applied": bool(match_result.get("meta", {}).get("scale_applied", False)),
                "note_priority": match_result.get("meta", {}).get("note_priority", "OsuMania"),
                "algorithm_version": "interlude_v1_score_v2",
            },
            "warnings": warnings,
        }

    except Exception as exc:
        logger.error(f"get_score_result 执行失败: {exc}")
        return _empty_report("Error", str(exc), match_result=match_result)