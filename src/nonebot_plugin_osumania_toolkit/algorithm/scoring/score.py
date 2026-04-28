from __future__ import annotations

from math import exp
from typing import Any, Optional, TYPE_CHECKING

from nonebot.log import logger

from ...parser.osu_file_parser import NOTE_HOLD_HEAD, NOTE_HOLD_TAIL, NOTE_NORMAL

if TYPE_CHECKING:
    from ...parser.ruleset_file_parser import ruleset_file

# 参考内容:
# - YAVSRG/prelude/src/Gameplay/Scoring/Scoring.fs
# - YAVSRG/prelude/src/Gameplay/Scoring/WifeCurve.fs
# - YAVSRG/prelude/src/Gameplay/Rulesets/Rulesets.fs
# - YAVSRG/prelude/src/Gameplay/Rulesets/SC.fs
# - YAVSRG/prelude/src/Gameplay/Rulesets/Wife3.fs

_REQUIRED_MATCH_KEYS = {
    "matched_events",
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
        "grade": {
            "name": "",
            "accuracy_threshold": 0.0,
        },
        "meta": {
            "speed_factor": 1.0,
            "scale_applied": False,
            "note_priority": "OsuMania",
            "algorithm_version": "interlude_v1_score_v1",
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


def _get_miss_index(judgements: list[dict[str, Any]]) -> int:
    if not judgements:
        return 0
    for idx, j in enumerate(judgements):
        if isinstance(j, dict) and str(j.get("Name", "")).strip().upper() == "MISS":
            return idx
    return len(judgements) - 1


def _ms_to_judgement(delta: float, judgements: list[dict[str, Any]]) -> Optional[int]:
    if not judgements:
        return None

    for idx, judgement in enumerate(judgements):
        if not isinstance(judgement, dict):
            continue
        tw = judgement.get("TimingWindows")
        if tw is None:
            continue
        if not isinstance(tw, list) or len(tw) != 2:
            continue
        if not _is_number(tw[0]) or not _is_number(tw[1]):
            continue
        if float(tw[0]) <= delta <= float(tw[1]):
            return idx

    return len(judgements) - 1


def _ms_to_release_judgement(delta: float, release_windows: list[Any], miss_index: int) -> int:
    for idx, window in enumerate(release_windows):
        if window is None:
            continue
        if not isinstance(window, list) or len(window) != 2:
            continue
        if not _is_number(window[0]) or not _is_number(window[1]):
            continue
        if float(window[0]) <= delta <= float(window[1]):
            return idx
    return miss_index


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


def _points_for_event_by_wife(delta_abs: float, wife_version: int, judge_scale: float) -> float:
    scale_factor = judge_scale if judge_scale > 0 else 1.0
    scaled_delta = abs(delta_abs) / scale_factor

    scale = (10.0 - float(wife_version)) / 6.0
    miss_weight = -2.75
    ridic = 5.0 * scale
    boo_window = 180.0 * scale
    ts_pow = 0.75
    zero = 65.0 * (scale ** ts_pow)
    dev = 22.7 * (scale ** ts_pow)

    if scaled_delta <= ridic:
        return 1.0
    if scaled_delta <= zero:
        return _erf_approx((zero - scaled_delta) / dev)
    if scaled_delta <= boo_window:
        return (scaled_delta - zero) * miss_weight / (boo_window - zero)
    return miss_weight


def _check_single_requirement(
    req: dict[str, Any],
    judgement_counts: list[int],
    combo_breaks: int,
    accuracy: float | None,
) -> bool:
    """Evaluate a single requirement dict. All present conditions must pass (AND logic)."""
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
    accuracy: float | None,
) -> bool:
    """Evaluate a Requirement field. Supports single dict (OR logic) or list of dicts (AND logic)."""
    if isinstance(req, list):
        # Combined requirements: all must pass
        if not req:
            return False
        return all(
            _check_single_requirement(r, judgement_counts, combo_breaks, accuracy)
            if isinstance(r, dict) else False
            for r in req
        )
    if isinstance(req, dict):
        return _check_single_requirement(req, judgement_counts, combo_breaks, accuracy)
    return False


def _evaluate_lamps(
    lamps_config: list[dict[str, Any]],
    judgement_counts: list[int],
    combo_breaks: int,
    accuracy: float | None = None,
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

        # Build candidate lists for "best lamp" selection
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
    judgement_counts: list[int] | None = None,
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
            # New Lamp-like format
            req = item.get("Requirement")
            if _evaluate_requirement(req, jc, combo_breaks, accuracy):
                achieved = True
                grade_acc = _to_float(item.get("Accuracy", 1.0), 1.0)
        elif "Accuracy" in item:
            # Legacy format
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

    # Fallback: first grade name
    if grades_config and isinstance(grades_config[0], dict):
        first_name = str(grades_config[0].get("Name", "")).strip()
        return first_name, 0.0
    return "", 0.0


def _extract_hold_variant(hold_mechanics: Any) -> tuple[str, Any]:
    if isinstance(hold_mechanics, dict) and len(hold_mechanics) == 1:
        return next(iter(hold_mechanics.items()))
    return "OnlyRequireHold", 120.0


def _determine_hold_scoring(
    ev: dict[str, Any],
    hold_mechanics: Any,
    notes_map: list[dict[str, Any]],
) -> tuple[bool, str]:
    variant, _payload = _extract_hold_variant(hold_mechanics)
    action = str(ev.get("action", "")).upper()
    if action == "GHOST_TAP":
        return False, "GHOST"

    idx = _to_int(ev.get("notes_map_index", ev.get("index", -1)), -1)
    kind = _to_int(ev.get("note_kind", NOTE_NORMAL), NOTE_NORMAL)

    if variant == "JudgeReleasesSeparately":
        return kind in (NOTE_NORMAL, NOTE_HOLD_HEAD, NOTE_HOLD_TAIL), "HEAD_AND_RELEASE"

    if kind == NOTE_HOLD_TAIL and 0 <= idx < len(notes_map):
        return False, "TAIL_NOT_PRIMARY"
    return True, "PRIMARY_OBJECT"


def _count_object_scoring_policy(
    notes_count: int,
    matched_events: list[dict[str, Any]],
    hold_mechanics: Any,
) -> int:
    if notes_count <= 0:
        return 0

    note_kinds = [0 for _ in range(notes_count)]
    for ev in matched_events:
        if not isinstance(ev, dict):
            continue
        idx = _to_int(ev.get("notes_map_index", ev.get("index", -1)), -1)
        if idx < 0 or idx >= notes_count:
            continue
        kind = _to_int(ev.get("note_kind", 0), 0)
        if kind in (NOTE_NORMAL, NOTE_HOLD_HEAD, NOTE_HOLD_TAIL):
            note_kinds[idx] = kind

    normal_count = sum(1 for k in note_kinds if k == NOTE_NORMAL)
    head_count = sum(1 for k in note_kinds if k == NOTE_HOLD_HEAD)
    tail_count = sum(1 for k in note_kinds if k == NOTE_HOLD_TAIL)

    hold_variant, _payload = _extract_hold_variant(hold_mechanics)
    if hold_variant == "JudgeReleasesSeparately":
        return normal_count + head_count + tail_count
    return normal_count + head_count


def _event_note_index(event: dict[str, Any], note_count: int) -> Optional[int]:
    idx = _to_int(event.get("notes_map_index", event.get("index", -1)), -1)
    if 0 <= idx < note_count:
        return idx
    return None


def _note_has_action(note_obj: dict[str, Any], action: str) -> bool:
    for ev in note_obj.get("events", []):
        if str(ev.get("action", "")).upper() == action:
            return True
    return False


def _build_hold_links(per_note: list[dict[str, Any]]) -> tuple[dict[int, int], dict[int, int]]:
    heads_by_col: dict[int, list[int]] = {}
    tails_by_col: dict[int, list[int]] = {}

    for note in per_note:
        idx = _to_int(note.get("index", -1), -1)
        col = _to_int(note.get("column", -1), -1)
        kind = _to_int(note.get("note_kind", 0), 0)
        if idx < 0 or col < 0:
            continue
        if kind == NOTE_HOLD_HEAD:
            heads_by_col.setdefault(col, []).append(idx)
        elif kind == NOTE_HOLD_TAIL:
            tails_by_col.setdefault(col, []).append(idx)

    def _sort_key(note_index: int) -> tuple[float, int]:
        t = per_note[note_index].get("note_time")
        if _is_number(t):
            return float(t), note_index
        return float("inf"), note_index

    head_to_tail: dict[int, int] = {}
    tail_to_head: dict[int, int] = {}

    for col in set(heads_by_col.keys()) | set(tails_by_col.keys()):
        heads = sorted(heads_by_col.get(col, []), key=_sort_key)
        tails = sorted(tails_by_col.get(col, []), key=_sort_key)
        queue = list(heads)
        for tail_idx in tails:
            if not queue:
                break
            head_idx = queue.pop(0)
            head_to_tail[head_idx] = tail_idx
            tail_to_head[tail_idx] = head_idx

    return head_to_tail, tail_to_head


def _release_windows_from_hold_mechanics(
    hold_variant: str,
    hold_payload: Any,
    judgements: list[dict[str, Any]],
) -> tuple[list[Any], Optional[int]]:
    windows: list[Any] = []
    overheld_idx: Optional[int] = None

    if hold_variant == "JudgeReleasesSeparately" and isinstance(hold_payload, list) and len(hold_payload) == 2:
        if isinstance(hold_payload[0], list):
            windows = list(hold_payload[0])
        if isinstance(hold_payload[1], int):
            overheld_idx = hold_payload[1]

    if not windows:
        for judgement in judgements:
            windows.append(judgement.get("TimingWindows") if isinstance(judgement, dict) else None)

    return windows, overheld_idx


def _max_release_late_window(release_windows: list[Any], fallback: float) -> float:
    late_values: list[float] = []
    for window in release_windows:
        if not isinstance(window, list) or len(window) != 2:
            continue
        if not _is_number(window[0]) or not _is_number(window[1]):
            continue
        late_values.append(float(window[1]))
    if late_values:
        return max(late_values)
    return fallback


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
        miss_index = _get_miss_index(judgements)

        note_count = _to_int(match_result.get("note_count", 0), 0)
        press_count = _to_int(match_result.get("press_count", 0), 0)
        if note_count < 0:
            return _empty_report("InvalidInput", "note_count must be >= 0", judgements_len=judgement_len, match_result=match_result)

        matched_events_raw = match_result.get("matched_events", []) or []
        if not isinstance(matched_events_raw, list):
            return _empty_report("InvalidInput", "matched_events must be list", judgements_len=judgement_len, match_result=match_result)

        accuracy_cfg = ruleset_data.get("Accuracy")
        if not isinstance(accuracy_cfg, dict):
            return _empty_report("InvalidInput", "Accuracy must be object", judgements_len=judgement_len, match_result=match_result)

        points_array_raw = accuracy_cfg.get("PointsPerJudgement")
        wife_curve_raw = accuracy_cfg.get("WifeCurve")
        has_points = isinstance(points_array_raw, list)
        has_wife = isinstance(wife_curve_raw, int)
        if not has_points and not has_wife:
            return _empty_report("InvalidInput", "Accuracy needs PointsPerJudgement or WifeCurve", judgements_len=judgement_len, match_result=match_result)

        if has_points and has_wife:
            warnings.append("Both PointsPerJudgement and WifeCurve are present; selected by prefer_points_per_judgement.")

        if prefer_points_per_judgement and has_points:
            use_points = True
        elif (not prefer_points_per_judgement) and has_wife:
            use_points = False
        elif has_points:
            use_points = True
        else:
            use_points = False

        points_array: list[float] = []
        wife_version = 4

        if use_points:
            points_array = [float(x) for x in (points_array_raw or []) if _is_number(x)]
            if len(points_array) != judgement_len:
                warnings.append(
                    f"PointsPerJudgement length({len(points_array)}) does not match Judgements({judgement_len})."
                )
                if not points_array:
                    points_array = [1.0] + [0.0 for _ in range(max(0, judgement_len - 1))]
        else:
            wife_version = int(wife_curve_raw)
            if wife_version < 2 or wife_version > 9:
                warnings.append(f"WifeCurve={wife_version} is outside typical range 2..9.")

        max_point_per_object = (
            max(points_array)
            if use_points and points_array
            else _points_for_event_by_wife(0.0, wife_version, judge_scale or 1.0)
        )

        hold_mechanics = ruleset_data.get("HoldMechanics")
        hold_variant, hold_payload = _extract_hold_variant(hold_mechanics)
        release_windows, overheld_idx = _release_windows_from_hold_mechanics(hold_variant, hold_payload, judgements)
        release_late_threshold = _max_release_late_window(release_windows, 0.0)

        hit_mechanics = ruleset_data.get("HitMechanics") if isinstance(ruleset_data.get("HitMechanics"), dict) else {}
        ghost_tap_judgement = hit_mechanics.get("GhostTapJudgement") if isinstance(hit_mechanics, dict) else None

        offset_vector = list(match_result.get("offset_vector", []) or [])
        unmatched_notes = list(match_result.get("unmatched_notes", []) or [])
        unmatched_presses = list(match_result.get("unmatched_presses", []) or [])

        per_note: list[dict[str, Any]] = []
        for i in range(note_count):
            per_note.append(
                {
                    "index": i,
                    "note_time": None,
                    "column": -1,
                    "note_kind": NOTE_NORMAL,
                    "head_delta": None,
                    "tail_delta": None,
                    "head_judgement": None,
                    "tail_judgement": None,
                    "final_judgement_index": None,
                    "final_judgement_name": None,
                    "points": 0.0,
                    "hold_state": None,
                    "events": [],
                }
            )

        matched_events = sorted(
            [ev for ev in matched_events_raw if isinstance(ev, dict)],
            key=lambda ev: (
                _to_float(ev.get("time", 0.0), 0.0),
                _to_int(ev.get("column", 0), 0),
                _to_int(ev.get("index", -1), -1),
                str(ev.get("action", "")),
            ),
        )

        for ev in matched_events:
            idx = _event_note_index(ev, note_count)
            if idx is None:
                continue

            note = per_note[idx]
            note["events"].append(ev)

            if _is_number(ev.get("time")):
                note["note_time"] = _to_float(ev.get("time"), 0.0)
            note["column"] = _to_int(ev.get("column", note.get("column", -1)), note.get("column", -1))

            kind = _to_int(ev.get("note_kind", note.get("note_kind", NOTE_NORMAL)), note.get("note_kind", NOTE_NORMAL))
            if kind in (NOTE_NORMAL, NOTE_HOLD_HEAD, NOTE_HOLD_TAIL):
                note["note_kind"] = kind

            if _is_number(ev.get("head_delta")):
                note["head_delta"] = _to_float(ev.get("head_delta"), 0.0)
            if _is_number(ev.get("tail_delta")):
                note["tail_delta"] = _to_float(ev.get("tail_delta"), 0.0)

            hold_state = ev.get("hold_state")
            if hold_state is not None:
                note["hold_state"] = hold_state

            action = str(ev.get("action", "")).upper()
            j_idx = ev.get("judgement_index")
            if action in {"HIT", "HOLD_HEAD"}:
                if isinstance(j_idx, int):
                    note["head_judgement"] = j_idx
                elif _is_number(ev.get("delta")):
                    note["head_delta"] = _to_float(ev.get("delta"), 0.0)
                    note["head_judgement"] = _ms_to_judgement(note["head_delta"], judgements)
            elif action == "MISS":
                if note["note_kind"] == NOTE_HOLD_TAIL:
                    note["tail_judgement"] = miss_index
                else:
                    note["head_judgement"] = miss_index
            elif action in {"RELEASE", "DROP_HOLD"}:
                if isinstance(j_idx, int):
                    note["tail_judgement"] = j_idx
                elif action == "DROP_HOLD":
                    note["tail_judgement"] = miss_index

        if len(offset_vector) != note_count:
            warnings.append(f"offset_vector length({len(offset_vector)}) does not match note_count({note_count}).")

        for i in range(min(note_count, len(offset_vector))):
            v = offset_vector[i]
            if not _is_number(v):
                continue
            note = per_note[i]
            if note["note_kind"] == NOTE_HOLD_TAIL:
                if note["tail_delta"] is None:
                    note["tail_delta"] = _to_float(v, 0.0)
                if note["tail_judgement"] is None:
                    note["tail_judgement"] = _ms_to_judgement(note["tail_delta"], judgements)
            else:
                if note["head_delta"] is None:
                    note["head_delta"] = _to_float(v, 0.0)
                if note["head_judgement"] is None:
                    note["head_judgement"] = _ms_to_judgement(note["head_delta"], judgements)

        unmatched_note_indices = {
            _to_int(item[0], -1)
            for item in unmatched_notes
            if isinstance(item, (list, tuple)) and len(item) >= 1
        }

        head_to_tail, _tail_to_head = _build_hold_links(per_note)

        scoring_objects: list[dict[str, Any]] = []

        def _points_for(j_idx: int, delta_abs: Optional[float]) -> float:
            if use_points:
                return _points_for_event_by_points_per_judgement(j_idx, points_array)
            if delta_abs is None:
                delta_abs = 9999.0
            return _points_for_event_by_wife(delta_abs, wife_version, judge_scale or 1.0)

        def _score(note_idx: int, j_idx: int, when: float, delta_abs: Optional[float], source: str) -> None:
            if note_idx < 0 or note_idx >= len(per_note):
                return
            safe_j = _safe_judgement_index(j_idx, judgement_len, miss_index)
            points = _points_for(safe_j, delta_abs)
            per_note[note_idx]["points"] += points
            if per_note[note_idx]["final_judgement_index"] is None:
                per_note[note_idx]["final_judgement_index"] = safe_j
            scoring_objects.append(
                {
                    "time": when,
                    "judgement_index": safe_j,
                    "points": points,
                    "source": source,
                }
            )

        processed_tail_scoring: set[int] = set()

        for note in sorted(
            per_note,
            key=lambda item: (_to_float(item.get("note_time"), float("inf")), _to_int(item.get("index", -1), -1)),
        ):
            idx = _to_int(note.get("index", -1), -1)
            if idx < 0:
                continue

            note_time = _to_float(note.get("note_time"), float(idx))
            note_kind = _to_int(note.get("note_kind", NOTE_NORMAL), NOTE_NORMAL)

            if note_kind == NOTE_HOLD_TAIL:
                continue

            if note_kind == NOTE_NORMAL:
                j = note.get("head_judgement")
                if j is None and _is_number(note.get("head_delta")):
                    j = _ms_to_judgement(_to_float(note.get("head_delta"), 0.0), judgements)
                if idx in unmatched_note_indices or j is None:
                    j = miss_index
                note["final_judgement_index"] = _safe_judgement_index(j, judgement_len, miss_index)
                _score(
                    idx,
                    note["final_judgement_index"],
                    note_time,
                    abs(_to_float(note.get("head_delta"), 0.0)) if _is_number(note.get("head_delta")) else None,
                    "normal",
                )
                continue

            # Hold head
            tail_idx = head_to_tail.get(idx)
            tail_note = per_note[tail_idx] if tail_idx is not None and 0 <= tail_idx < len(per_note) else None

            head_j = note.get("head_judgement")
            if head_j is None and _is_number(note.get("head_delta")):
                head_j = _ms_to_judgement(_to_float(note.get("head_delta"), 0.0), judgements)
            if head_j is None:
                head_j = miss_index

            if hold_variant == "OnlyRequireHold":
                threshold = _to_float(hold_payload, 0.0)
                hold_ok = False
                if tail_note is not None and _is_number(tail_note.get("tail_delta")):
                    hold_ok = abs(_to_float(tail_note.get("tail_delta"), 0.0)) <= threshold
                    if _note_has_action(tail_note, "DROP_HOLD"):
                        hold_ok = False

                final_j = head_j if hold_ok and idx not in unmatched_note_indices else miss_index
                note["final_judgement_index"] = _safe_judgement_index(final_j, judgement_len, miss_index)
                _score(
                    idx,
                    note["final_judgement_index"],
                    note_time,
                    abs(_to_float(note.get("head_delta"), 0.0)) if _is_number(note.get("head_delta")) else None,
                    "hold_only_require",
                )
                if tail_note is not None and tail_note.get("final_judgement_index") is None:
                    tail_note["final_judgement_index"] = (
                        miss_index if not hold_ok else _safe_judgement_index(tail_note.get("tail_judgement", miss_index), judgement_len, miss_index)
                    )
                continue

            if hold_variant == "JudgeReleasesSeparately":
                if idx in unmatched_note_indices:
                    head_j = miss_index
                note["final_judgement_index"] = _safe_judgement_index(head_j, judgement_len, miss_index)
                _score(
                    idx,
                    note["final_judgement_index"],
                    note_time,
                    abs(_to_float(note.get("head_delta"), 0.0)) if _is_number(note.get("head_delta")) else None,
                    "hold_head",
                )

                release_j = miss_index
                release_time = note_time
                release_delta_abs: Optional[float] = None

                if tail_note is not None:
                    release_time = _to_float(tail_note.get("note_time"), note_time)
                    dropped = _note_has_action(tail_note, "DROP_HOLD")
                    if isinstance(tail_note.get("tail_judgement"), int):
                        release_j = _to_int(tail_note.get("tail_judgement"), miss_index)
                    elif _is_number(tail_note.get("tail_delta")):
                        tail_delta = _to_float(tail_note.get("tail_delta"), 0.0)
                        if dropped:
                            release_j = miss_index
                        elif overheld_idx is not None and tail_delta > release_late_threshold:
                            release_j = _safe_judgement_index(overheld_idx, judgement_len, miss_index)
                        else:
                            release_j = _ms_to_release_judgement(tail_delta, release_windows, miss_index)
                        release_delta_abs = abs(tail_delta)

                    tail_note["final_judgement_index"] = _safe_judgement_index(release_j, judgement_len, miss_index)
                    _score(
                        tail_idx if tail_idx is not None else -1,
                        tail_note["final_judgement_index"],
                        release_time,
                        release_delta_abs,
                        "hold_release",
                    )
                    if tail_idx is not None:
                        processed_tail_scoring.add(tail_idx)
                else:
                    warnings.append(f"Hold head index={idx} has no linked tail; release counted as miss.")
                continue

            if hold_variant == "OnlyJudgeReleases":
                dropped_idx = _to_int(hold_payload, miss_index)
                release_j = miss_index
                release_time = note_time
                release_delta_abs: Optional[float] = None

                if tail_note is not None and _is_number(tail_note.get("tail_delta")):
                    tail_delta = _to_float(tail_note.get("tail_delta"), 0.0)
                    release_j = _ms_to_judgement(tail_delta, judgements)
                    if release_j is None:
                        release_j = miss_index
                    if _note_has_action(tail_note, "DROP_HOLD") or tail_delta > 180.0:
                        release_j = max(_safe_judgement_index(release_j, judgement_len, miss_index), _safe_judgement_index(dropped_idx, judgement_len, miss_index))
                    release_time = _to_float(tail_note.get("note_time"), note_time)
                    release_delta_abs = abs(tail_delta)

                if idx in unmatched_note_indices:
                    release_j = miss_index

                note["final_judgement_index"] = _safe_judgement_index(release_j, judgement_len, miss_index)
                _score(idx, note["final_judgement_index"], release_time, release_delta_abs, "hold_only_release")
                if tail_note is not None and tail_note.get("final_judgement_index") is None:
                    tail_note["final_judgement_index"] = note["final_judgement_index"]
                continue

            # CombineHeadAndTail
            combine_j = _safe_judgement_index(head_j, judgement_len, miss_index)
            tail_j = miss_index
            sub_variant = None
            sub_payload = None
            if isinstance(hold_payload, dict) and len(hold_payload) == 1:
                sub_variant, sub_payload = next(iter(hold_payload.items()))

            if tail_note is not None and _is_number(tail_note.get("tail_delta")):
                tail_delta = _to_float(tail_note.get("tail_delta"), 0.0)
                t_j = tail_note.get("tail_judgement")
                if not isinstance(t_j, int):
                    t_j = _ms_to_judgement(tail_delta, judgements)
                tail_j = _safe_judgement_index(t_j, judgement_len, miss_index)
                if _note_has_action(tail_note, "DROP_HOLD"):
                    tail_j = miss_index
            else:
                tail_j = miss_index

            if sub_variant == "HeadJudgementOr" and isinstance(sub_payload, list) and len(sub_payload) == 4:
                late = _to_float(sub_payload[1], 180.0)
                dropped_idx = _safe_judgement_index(sub_payload[2], judgement_len, miss_index)
                overheld_idx2 = _safe_judgement_index(sub_payload[3], judgement_len, miss_index)

                dropped = tail_note is None or _note_has_action(tail_note, "DROP_HOLD")
                overheld = False
                if tail_note is not None and _is_number(tail_note.get("tail_delta")):
                    overheld = _to_float(tail_note.get("tail_delta"), 0.0) > late

                if dropped:
                    combine_j = max(combine_j, dropped_idx)
                elif overheld:
                    combine_j = max(combine_j, overheld_idx2)
            elif sub_variant == "OsuMania":
                combine_j = max(combine_j, tail_j)
                warn = "CombineHeadAndTail.OsuMania uses temporary approximation max(head, tail)."
                if warn not in warnings:
                    warnings.append(warn)
            else:
                combine_j = max(combine_j, tail_j)

            if idx in unmatched_note_indices:
                combine_j = miss_index

            note["final_judgement_index"] = _safe_judgement_index(combine_j, judgement_len, miss_index)
            _score(
                idx,
                note["final_judgement_index"],
                note_time,
                abs(_to_float(note.get("head_delta"), 0.0)) if _is_number(note.get("head_delta")) else None,
                "hold_combined",
            )
            if tail_note is not None and tail_note.get("final_judgement_index") is None:
                tail_note["final_judgement_index"] = tail_j

        if hold_variant == "JudgeReleasesSeparately":
            for tail_idx, tail_note in enumerate(per_note):
                if _to_int(tail_note.get("note_kind", 0), 0) != NOTE_HOLD_TAIL:
                    continue
                if tail_idx in processed_tail_scoring:
                    continue
                j = tail_note.get("tail_judgement")
                if not isinstance(j, int):
                    j = miss_index
                tail_note["final_judgement_index"] = _safe_judgement_index(j, judgement_len, miss_index)
                _score(
                    tail_idx,
                    tail_note["final_judgement_index"],
                    _to_float(tail_note.get("note_time"), float(tail_idx)),
                    abs(_to_float(tail_note.get("tail_delta"), 0.0)) if _is_number(tail_note.get("tail_delta")) else None,
                    "orphan_tail",
                )

        # Ghost tap scoring
        if isinstance(ghost_tap_judgement, int):
            g_idx = _safe_judgement_index(ghost_tap_judgement, judgement_len, miss_index)
            for item in unmatched_presses:
                if isinstance(item, (list, tuple)) and len(item) >= 2 and _is_number(item[1]):
                    press_t = _to_float(item[1], 0.0)
                else:
                    press_t = 0.0
                scoring_objects.append(
                    {
                        "time": press_t,
                        "judgement_index": g_idx,
                        "points": _points_for(g_idx, 9999.0 if not use_points else None),
                        "source": "ghost_tap",
                    }
                )

        scoring_objects.sort(key=lambda obj: (_to_float(obj.get("time"), 0.0), str(obj.get("source", ""))))

        judgement_counts = [0 for _ in range(judgement_len)]
        points_sum = 0.0
        max_points = 0.0

        combo = 0
        best_combo = 0
        combo_breaks = 0

        for obj in scoring_objects:
            j_idx = _safe_judgement_index(obj.get("judgement_index"), judgement_len, miss_index)
            points = _to_float(obj.get("points", 0.0), 0.0)

            judgement_counts[j_idx] += 1
            points_sum += points
            max_points += max_point_per_object

            breaks_combo = False
            if 0 <= j_idx < judgement_len and isinstance(judgements[j_idx], dict):
                breaks_combo = bool(judgements[j_idx].get("BreaksCombo", False))

            if breaks_combo:
                combo = 0
                combo_breaks += 1
            else:
                combo += 1
                best_combo = max(best_combo, combo)

        expected_objects = _count_object_scoring_policy(note_count, matched_events, hold_mechanics)
        if len(scoring_objects) < expected_objects:
            warnings.append(
                f"Scoring objects({len(scoring_objects)}) < policy expected({expected_objects})."
            )

        accuracy_fraction = 1.0 if max_points == 0.0 else points_sum / max_points

        lamps, selected_lamp = _evaluate_lamps(
            ruleset_data.get("Lamps") if isinstance(ruleset_data.get("Lamps"), list) else [],
            judgement_counts,
            combo_breaks,
            accuracy=accuracy_fraction,
        )

        grade_name, grade_threshold = _pick_grade(
            ruleset_data.get("Grades") if isinstance(ruleset_data.get("Grades"), list) else [],
            accuracy_fraction,
            judgement_counts=judgement_counts,
            combo_breaks=combo_breaks,
        )

        for note in per_note:
            j_idx = note.get("final_judgement_index")
            if isinstance(j_idx, int) and 0 <= j_idx < judgement_len and isinstance(judgements[j_idx], dict):
                note["final_judgement_name"] = str(judgements[j_idx].get("Name", ""))
            else:
                note["final_judgement_name"] = None

            note.pop("head_judgement", None)
            note.pop("tail_judgement", None)
            note.pop("events", None)

        # Attach hold scoring helper result to warnings if unexpected events exist.
        for ev in matched_events:
            counts_as, _reason = _determine_hold_scoring(ev, hold_mechanics, per_note)
            if not counts_as and str(ev.get("action", "")).upper() not in {"GHOST_TAP", "DROP_HOLD", "RELEASE"}:
                warnings.append("Detected non-scored event outside expected hold policy.")
                break

        warnings = list(dict.fromkeys(warnings))

        meta_src = match_result.get("meta", {}) if isinstance(match_result.get("meta"), dict) else {}
        meta = {
            "speed_factor": _to_float(meta_src.get("speed_factor", 1.0), 1.0),
            "scale_applied": bool(meta_src.get("scale_applied", False)),
            "note_priority": meta_src.get("note_priority", "OsuMania"),
            "algorithm_version": "interlude_v1_score_v1",
        }

        logger.debug(
            "get_score_result finished: "
            f"notes={note_count}, presses={press_count}, objects={len(scoring_objects)}, "
            f"accuracy={accuracy_fraction:.6f}, points={points_sum:.6f}/{max_points:.6f}, "
            f"mode={'points' if use_points else 'wife'}"
        )

        return {
            "status": "OK",
            "error": None,
            "accuracy_fraction": float(accuracy_fraction),
            "points_sum": float(points_sum),
            "max_points": float(max_points),
            "judgement_counts": judgement_counts,
            "per_note": per_note,
            "matched_events": list(match_result.get("matched_events", []) or []),
            "offset_vector": list(match_result.get("offset_vector", []) or []),
            "delta_list": list(match_result.get("delta_list", []) or []),
            "matched_pairs": list(match_result.get("matched_pairs", []) or []),
            "unmatched_presses": unmatched_presses,
            "unmatched_notes": unmatched_notes,
            "note_count": note_count,
            "press_count": press_count,
            "combo": {
                "best_combo": best_combo,
                "combo_breaks": combo_breaks,
            },
            "lamps": lamps,
            "lamp": selected_lamp,
            "grade": {
                "name": grade_name,
                "accuracy_threshold": float(grade_threshold),
            },
            "meta": meta,
            "warnings": warnings,
        }

    except Exception as exc:
        logger.error(f"get_score_result failed: {exc}")
        return _empty_report(
            "Error",
            str(exc),
            judgements_len=0,
            match_result=match_result if isinstance(match_result, dict) else None,
            warnings=warnings,
        )