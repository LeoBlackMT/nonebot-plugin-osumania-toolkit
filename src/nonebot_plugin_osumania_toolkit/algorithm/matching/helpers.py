from __future__ import annotations

import bisect
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional

from nonebot.log import logger

from ...parser.osr_file_parser import osr_file
from ...parser.osu_file_parser import NOTE_HOLD_HEAD, NOTE_HOLD_TAIL, NOTE_NORMAL, osu_file

# 参考实现路径：
# - YAVSRG/prelude/src/Gameplay/Scoring/HitMechanics.fs
# - YAVSRG/prelude/src/Gameplay/Scoring/Scoring.fs
# - YAVSRG/prelude/src/Gameplay/Scoring/Events.fs
# - osu.Game/Rulesets/UI/ReplayRecorder.cs
# - osu.Game.Rulesets.Osu/Replays/OsuAutoGeneratorBase.cs

NOTE_KIND_ANY = 0
HIT_REQUIRED = "HIT_REQUIRED"
HIT_ACCEPTED = "HIT_ACCEPTED"
RELEASE_REQUIRED = "RELEASE_REQUIRED"
RELEASE_ACCEPTED = "RELEASE_ACCEPTED"
MISS = "MISS"
DROP_HOLD = "DROP_HOLD"

FOUND = "FOUND"
BLOCKED = "BLOCKED"
NOTFOUND = "NOTFOUND"


@dataclass(slots=True)
class NoteEntry:
    index: int
    time_ms: float
    column: int
    note_kind: int
    note_start: float
    note_end: float
    status: str
    tail_index: Optional[int] = None
    head_index: Optional[int] = None
    press_time: Optional[float] = None
    release_time: Optional[float] = None
    delta: Optional[float] = None
    head_delta: Optional[float] = None
    tail_delta: Optional[float] = None
    hold_state: Optional[str] = None
    blocked: bool = False
    matched: bool = False
    judgement_index: Optional[int] = None


@dataclass(slots=True)
class HoldState:
    active: bool = False
    head_index: Optional[int] = None
    tail_index: Optional[int] = None
    press_time: Optional[float] = None


def _empty_result(status: str, error: Optional[str], meta: Optional[dict[str, Any]] = None) -> dict:
    return {
        "status": status,
        "error": error,
        "matched_events": [],
        "offset_vector": [],
        "delta_list": [],
        "matched_pairs": [],
        "unmatched_presses": [],
        "unmatched_notes": [],
        "note_count": 0,
        "press_count": 0,
        "meta": meta or {
            "rate_used": 1.0,
            "speed_factor": 1.0,
            "scale_applied": False,
            "chart_time_offset": 0.0,
            "note_priority": "OsuMania",
            "algorithm_version": "interlude_v1",
        },
    }


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _determine_speed_factor(osr: osr_file) -> float:
    speed_factor = 1.0
    try:
        speed_factor = float(getattr(osr, "speed_factor", 1.0) or 1.0)
    except Exception:
        speed_factor = 1.0

    if speed_factor != 1.0:
        return speed_factor

    mod_value = int(getattr(osr, "mod", 0) or 0)
    if (mod_value & 64) or (mod_value & 512):
        return 1.5
    if mod_value & 256:
        return 0.75
    return 1.0


def _resolve_scale_decision(speed_factor: float, assume_replay_times_scaled: Optional[bool]) -> bool:
    if assume_replay_times_scaled is True:
        return True
    if assume_replay_times_scaled is False:
        return False
    return speed_factor != 1.0


def _apply_time_scaling(
    events: list[tuple[int, float]],
    replay_data: list[tuple[float, int]],
    *,
    scale: bool,
    speed_factor: float,
    rate: float,
) -> tuple[list[tuple[int, float]], list[tuple[float, int]], bool]:
    applied = False

    if scale and speed_factor not in (0.0, 1.0):
        events = [(col, float(t) / speed_factor) for col, t in events]
        replay_data = [(float(t) / speed_factor, mask) for t, mask in replay_data]
        applied = True

    if rate > 0 and abs(rate - 1.0) > 1e-9:
        events = [(col, float(t) / rate) for col, t in events]
        replay_data = [(float(t) / rate, mask) for t, mask in replay_data]

    return events, replay_data, applied


def _select_press_and_replay_stream(
    osr: osr_file,
    *,
    use_chart_time: bool,
    assume_replay_times_scaled: Optional[bool],
    rate: float,
) -> tuple[list[tuple[int, float]], list[tuple[float, int]], float, bool]:
    speed_factor = _determine_speed_factor(osr)

    chart_events = getattr(osr, "press_events_chart_float", None) or getattr(osr, "press_events_chart", None)
    chart_replay = getattr(osr, "replay_data_chart", None)

    real_events = (
        getattr(osr, "press_events_real_float", None)
        or getattr(osr, "press_events_real", None)
        or getattr(osr, "press_events_float", None)
        or getattr(osr, "press_events", None)
        or []
    )
    real_replay = getattr(osr, "replay_data_real", None) or []

    if use_chart_time and (chart_events or chart_replay):
        events = [(int(col), float(t)) for col, t in (chart_events or [])]
        replay_data = [(float(t), int(mask)) for t, mask in (chart_replay or [])]
        if rate > 0 and abs(rate - 1.0) > 1e-9:
            events = [(col, t / rate) for col, t in events]
            replay_data = [(t / rate, mask) for t, mask in replay_data]
        scale_applied = bool(getattr(osr, "scale_applied", speed_factor != 1.0))
        return events, replay_data, speed_factor, scale_applied

    events = [(int(col), float(t)) for col, t in real_events]
    replay_data = [(float(t), int(mask)) for t, mask in real_replay]

    if use_chart_time:
        scale = _resolve_scale_decision(speed_factor, assume_replay_times_scaled)
    else:
        scale = False

    events, replay_data, scale_applied = _apply_time_scaling(
        events,
        replay_data,
        scale=scale,
        speed_factor=speed_factor,
        rate=rate,
    )
    return events, replay_data, speed_factor, scale_applied


def _nearest_note_distance(note_times: list[float], time_value: float) -> float:
    if not note_times:
        return float("inf")

    idx = bisect.bisect_left(note_times, time_value)
    best = float("inf")
    if idx < len(note_times):
        best = abs(note_times[idx] - time_value)
    if idx > 0:
        best = min(best, abs(note_times[idx - 1] - time_value))
    return best


def _nearest_note_time(note_times: list[float], time_value: float) -> Optional[float]:
    if not note_times:
        return None

    idx = bisect.bisect_left(note_times, time_value)
    candidates: list[float] = []
    if idx < len(note_times):
        candidates.append(note_times[idx])
    if idx > 0:
        candidates.append(note_times[idx - 1])
    if not candidates:
        return None
    return min(candidates, key=lambda t: abs(t - time_value))


def _offset_match_score_by_column(
    *,
    press_events: list[tuple[int, float]],
    note_times_by_col: dict[int, list[float]],
    offset: float,
    hit_window: float = 180.0,
    sample_limit: int = 2048,
) -> tuple[int, float]:
    matched = 0
    abs_delta_sum = 0.0

    for col, press_time in press_events[:sample_limit]:
        note_times = note_times_by_col.get(int(col), [])
        if not note_times:
            continue

        nearest = _nearest_note_time(note_times, float(press_time) + offset)
        if nearest is None:
            continue

        delta = float(press_time) + offset - nearest
        if -hit_window <= delta <= hit_window:
            matched += 1
            abs_delta_sum += abs(delta)

    if matched <= 0:
        return 0, float("inf")
    return matched, abs_delta_sum / matched


def _estimate_chart_time_offset(
    *,
    osu: osu_file,
    press_events: list[tuple[int, float]],
    replay_data: list[tuple[float, int]],
    use_chart_time: bool,
) -> float:
    """
    估计是否需要把 replay 的 chart_time 平移到谱面绝对时间轴。

    参考 prelude：ReplayFrame 的 ChartTime 相对 first_note，匹配时使用 first_note + chart_time。
    若输入已是绝对时间，平移会显著变差，因此通过最邻近音符距离做双候选评分（0 与 first_note）。
    """
    if not use_chart_time:
        return 0.0

    note_times: list[float] = []
    if hasattr(osu, "note_rows") and isinstance(getattr(osu, "note_rows"), list):
        note_times = sorted(float(t) for t, _ in getattr(osu, "note_rows") if isinstance(t, (int, float)))
    elif hasattr(osu, "note_starts") and isinstance(getattr(osu, "note_starts"), list):
        note_times = sorted(float(t) for t in getattr(osu, "note_starts") if isinstance(t, (int, float)))

    if not note_times:
        return 0.0

    first_note = float(note_times[0])
    if first_note <= 1.0:
        return 0.0

    sample_times = [float(t) for _, t in press_events[:256]] if press_events else []
    if not sample_times:
        sample_times = [float(t) for t, _ in replay_data[:256]]

    if len(sample_times) < 8:
        return 0.0

    note_times_by_col: dict[int, list[float]] = {}
    raw_note_times = getattr(osu, "note_times", None)
    if isinstance(raw_note_times, dict):
        for col_raw, times_raw in raw_note_times.items():
            if not isinstance(col_raw, int):
                continue
            if not isinstance(times_raw, list):
                continue
            cleaned = sorted(float(t) for t in times_raw if isinstance(t, (int, float)))
            if cleaned:
                note_times_by_col[col_raw] = cleaned

    # 先用按列命中潜力比较两个候选偏移（0 与 first_note），避免仅按最近距离导致误判。
    if press_events and note_times_by_col:
        base_match, base_mad = _offset_match_score_by_column(
            press_events=press_events,
            note_times_by_col=note_times_by_col,
            offset=0.0,
        )
        shifted_match, shifted_mad = _offset_match_score_by_column(
            press_events=press_events,
            note_times_by_col=note_times_by_col,
            offset=first_note,
        )

        sample_n = min(len(press_events), 2048)
        improve_threshold = max(8, int(sample_n * 0.01))
        if shifted_match >= base_match + improve_threshold and shifted_mad <= base_mad + 8.0:
            return first_note
        return 0.0

    def score(offset: float) -> float:
        distances = [_nearest_note_distance(note_times, t + offset) for t in sample_times]
        return float(sum(distances) / max(1, len(distances)))

    base_score = score(0.0)
    shifted_score = score(first_note)

    # 只有当平移显著改善时才应用，避免破坏本来已在绝对时间轴的数据。
    if shifted_score + 20.0 < base_score and shifted_score <= base_score * 0.75:
        return first_note
    return 0.0


def _build_hitflagdata(osu: osu_file) -> tuple[list[NoteEntry], dict[int, list[int]], dict[int, list[int]], int]:
    if hasattr(osu, "to_TimeArray"):
        time_array = osu.to_TimeArray()
    elif hasattr(osu, "note_rows"):
        time_array = list(getattr(osu, "note_rows") or [])
    else:
        return [], {}, {}, 0

    keys = int(getattr(osu, "column_count", 0) or 0)
    if keys <= 0:
        return [], {}, {}, 0

    notes: list[NoteEntry] = []
    pending_heads: dict[int, deque[int]] = {col: deque() for col in range(keys)}

    for time_ms, row in sorted(time_array, key=lambda item: float(item[0])):
        t = float(time_ms)
        if not isinstance(row, list):
            continue

        limit = min(keys, len(row))
        for col in range(limit):
            note_kind = int(row[col] or 0)
            if note_kind == 0:
                continue

            if note_kind == NOTE_NORMAL:
                notes.append(
                    NoteEntry(
                        index=len(notes),
                        time_ms=t,
                        column=col,
                        note_kind=NOTE_NORMAL,
                        note_start=t,
                        note_end=t,
                        status=HIT_REQUIRED,
                    )
                )
            elif note_kind == NOTE_HOLD_HEAD:
                idx = len(notes)
                notes.append(
                    NoteEntry(
                        index=idx,
                        time_ms=t,
                        column=col,
                        note_kind=NOTE_HOLD_HEAD,
                        note_start=t,
                        note_end=t,
                        status=HIT_REQUIRED,
                    )
                )
                pending_heads[col].append(idx)
            elif note_kind == NOTE_HOLD_TAIL:
                idx = len(notes)
                notes.append(
                    NoteEntry(
                        index=idx,
                        time_ms=t,
                        column=col,
                        note_kind=NOTE_HOLD_TAIL,
                        note_start=t,
                        note_end=t,
                        status=RELEASE_REQUIRED,
                    )
                )
                if pending_heads[col]:
                    head_idx = pending_heads[col].popleft()
                    notes[head_idx].tail_index = idx
                    notes[head_idx].note_end = t
                    notes[idx].head_index = head_idx
                    notes[idx].note_start = notes[head_idx].time_ms

    notes_by_col: dict[int, list[int]] = {col: [] for col in range(keys)}
    tails_by_col: dict[int, list[int]] = {col: [] for col in range(keys)}

    for note in notes:
        if note.note_kind == NOTE_HOLD_TAIL:
            tails_by_col[note.column].append(note.index)
        else:
            notes_by_col[note.column].append(note.index)

    return notes, notes_by_col, tails_by_col, keys


def _extract_note_windows(ruleset_data: dict[str, Any]) -> tuple[float, float, list[tuple[int, float, float]], bool]:
    judgement_windows: list[tuple[int, float, float]] = []
    has_any_window = False

    for idx, judgement in enumerate(ruleset_data.get("Judgements", []) or []):
        if not isinstance(judgement, dict):
            continue
        tw = judgement.get("TimingWindows")
        if tw is None:
            continue
        if not isinstance(tw, list) or len(tw) != 2:
            continue
        early, late = tw[0], tw[1]
        if not _is_number(early) or not _is_number(late):
            continue
        early_f = float(early)
        late_f = float(late)
        judgement_windows.append((idx, early_f, late_f))
        has_any_window = True

    if judgement_windows:
        early_note = min(w[1] for w in judgement_windows)
        late_note = max(w[2] for w in judgement_windows)
        return early_note, late_note, judgement_windows, has_any_window

    # 无窗口时仍可匹配：给一个保守默认窗口并记录 warning。
    logger.warning("ruleset 未提供可用 TimingWindows，使用默认窗口 [-120, 120] ms")
    return -120.0, 120.0, [], False


def _extract_release_windows(
    ruleset_data: dict[str, Any],
    *,
    default_early: float,
    default_late: float,
) -> tuple[float, float]:
    hold_mechanics = ruleset_data.get("HoldMechanics")
    if not isinstance(hold_mechanics, dict) or len(hold_mechanics) != 1:
        return default_early, default_late

    variant, payload = next(iter(hold_mechanics.items()))

    if variant == "JudgeReleasesSeparately" and isinstance(payload, list) and len(payload) == 2:
        windows = payload[0]
        if isinstance(windows, list):
            pairs: list[tuple[float, float]] = []
            for item in windows:
                if isinstance(item, list) and len(item) == 2 and _is_number(item[0]) and _is_number(item[1]):
                    pairs.append((float(item[0]), float(item[1])))
            if pairs:
                return min(p[0] for p in pairs), max(p[1] for p in pairs)

    if variant == "OnlyJudgeReleases" and isinstance(payload, int):
        judgements = ruleset_data.get("Judgements", []) or []
        if 0 <= payload < len(judgements):
            tw = judgements[payload].get("TimingWindows") if isinstance(judgements[payload], dict) else None
            if isinstance(tw, list) and len(tw) == 2 and _is_number(tw[0]) and _is_number(tw[1]):
                return float(tw[0]), float(tw[1])

    if variant == "CombineHeadAndTail" and isinstance(payload, dict) and len(payload) == 1:
        sub_variant, sub_payload = next(iter(payload.items()))
        if sub_variant == "HeadJudgementOr" and isinstance(sub_payload, list) and len(sub_payload) >= 2:
            if _is_number(sub_payload[0]) and _is_number(sub_payload[1]):
                return float(sub_payload[0]), float(sub_payload[1])
        if sub_variant == "OsuMania" and isinstance(sub_payload, dict):
            window0 = sub_payload.get("Window0")
            if _is_number(window0):
                w = abs(float(window0))
                return -w, w

    if variant == "OnlyRequireHold" and _is_number(payload):
        hold_required = abs(float(payload))
        return min(default_early, -hold_required), max(default_late, hold_required)

    return default_early, default_late


def _extract_release_judgement_windows(
    ruleset_data: dict[str, Any],
    default_windows: list[tuple[int, float, float]],
) -> list[tuple[int, float, float]]:
    hold_mechanics = ruleset_data.get("HoldMechanics")
    if not isinstance(hold_mechanics, dict) or len(hold_mechanics) != 1:
        return default_windows

    variant, payload = next(iter(hold_mechanics.items()))
    if variant != "JudgeReleasesSeparately" or not isinstance(payload, list) or len(payload) != 2:
        return default_windows

    windows_raw = payload[0]
    if not isinstance(windows_raw, list):
        return default_windows

    out: list[tuple[int, float, float]] = []
    for idx, item in enumerate(windows_raw):
        if not isinstance(item, list) or len(item) != 2:
            continue
        if not _is_number(item[0]) or not _is_number(item[1]):
            continue
        out.append((idx, float(item[0]), float(item[1])))

    return out if out else default_windows


def _infer_judgement_index(delta: float, windows: list[tuple[int, float, float]]) -> Optional[int]:
    for idx, early, late in windows:
        if early <= delta <= late:
            return idx
    return None


def _build_replay_input_events(
    *,
    replay_data: list[tuple[float, int]],
    press_events: list[tuple[int, float]],
    keys: int,
    mirror: bool,
) -> list[tuple[float, int, str]]:
    def map_col(col: int) -> Optional[int]:
        mapped = (keys - 1 - col) if mirror else col
        if 0 <= mapped < keys:
            return mapped
        return None

    events: list[tuple[float, int, str]] = []
    built_from_replay = False

    if replay_data:
        built_from_replay = True
        prev_mask = 0

        replay_rows = list(replay_data)
        if any(replay_rows[i][0] > replay_rows[i + 1][0] for i in range(len(replay_rows) - 1)):
            # 仅在明显乱序时做稳定排序；同时间戳保持原始顺序，避免引入额外边沿。
            replay_rows = [
                item
                for _, item in sorted(
                    enumerate(replay_rows),
                    key=lambda pair: (float(pair[1][0]), pair[0]),
                )
            ]

        for time_ms, mask in replay_rows:
            now = int(mask)
            changed = prev_mask ^ now
            if changed == 0:
                prev_mask = now
                continue

            # 与 prelude ReplayConsumer 对齐：按列递增逐列处理，
            # 每列先判定是否 keyup，否则判定 keydown。
            bit_limit = max(keys, 18)
            for col in range(bit_limit):
                bit = 1 << col
                if (changed & bit) == 0:
                    continue
                mapped = map_col(col)
                if mapped is None:
                    continue

                prev_down = (prev_mask & bit) != 0
                now_down = (now & bit) != 0
                if prev_down and not now_down:
                    events.append((float(time_ms), mapped, "up"))
                elif now_down and not prev_down:
                    events.append((float(time_ms), mapped, "down"))

            prev_mask = now

    if not events:
        for col, t in sorted(press_events, key=lambda item: (float(item[1]), int(item[0]))):
            mapped = map_col(int(col))
            if mapped is None:
                continue
            events.append((float(t), mapped, "down"))

    # replay 帧分支必须保序（同时刻多帧会影响边沿语义）；press 兜底分支可按时间排序。
    if not built_from_replay:
        order = {"up": 0, "down": 1}
        events.sort(key=lambda item: (item[0], order.get(item[2], 9), item[1]))
    return events


def _build_event_dict(
    *,
    index: int,
    time_ms: float,
    column: int,
    action: str,
    note_kind: int,
    press_time: Optional[float],
    release_time: Optional[float],
    delta: Optional[float],
    head_delta: Optional[float],
    tail_delta: Optional[float],
    hold_state: Optional[str],
    blocked: bool,
    judgement_index: Optional[int],
    notes_map_index: Optional[int],
) -> dict[str, Any]:
    return {
        "index": int(index),
        "time": float(time_ms),
        "column": int(column),
        "action": action,
        "note_kind": int(note_kind),
        "press_time": None if press_time is None else float(press_time),
        "release_time": None if release_time is None else float(release_time),
        "delta": None if delta is None else float(delta),
        "head_delta": None if head_delta is None else float(head_delta),
        "tail_delta": None if tail_delta is None else float(tail_delta),
        "hold_state": hold_state,
        "blocked": bool(blocked),
        "judgement_index": judgement_index,
        "notes_map_index": notes_map_index,
    }


def _hitmechanics_interlude(
    *,
    now: float,
    col: int,
    note_indices: list[int],
    start_index: int,
    notes: list[NoteEntry],
    early_window: float,
    late_window: float,
    cbrush_threshold: float,
    accepted_history: list[dict[str, float]],
) -> tuple[str, Optional[int], Optional[float]]:
    window_start = now - late_window
    window_end = now - early_window

    earliest: Optional[tuple[int, float]] = None
    closest: Optional[tuple[int, float]] = None

    i = start_index
    while i < len(note_indices):
        note_idx = note_indices[i]
        note = notes[note_idx]
        if note.time_ms > window_end:
            break

        if note.status == HIT_REQUIRED:
            if note.time_ms >= window_start:
                delta = now - note.time_ms
                if earliest is None:
                    earliest = (note_idx, delta)
                if closest is None:
                    closest = (note_idx, delta)
                else:
                    cur_abs = abs(delta)
                    best_abs = abs(closest[1])
                    if cur_abs < best_abs or (cur_abs == best_abs and note_idx < closest[0]):
                        closest = (note_idx, delta)
        i += 1

    if earliest is None or closest is None:
        return NOTFOUND, None, None

    if cbrush_threshold > 0 and abs(closest[1]) < cbrush_threshold:
        candidate_idx, candidate_delta = earliest
    else:
        candidate_idx, candidate_delta = closest

    candidate_note_time = notes[candidate_idx].time_ms
    blocked = False
    for prev in accepted_history[-8:]:
        if int(prev.get("column", -1)) != col:
            continue
        prev_note_time = float(prev.get("note_time", 0.0))
        prev_press_time = float(prev.get("press_time", 0.0))
        if prev_note_time >= candidate_note_time:
            continue
        bad_delta = prev_press_time - candidate_note_time
        if early_window <= bad_delta <= late_window and abs(bad_delta) < abs(candidate_delta):
            blocked = True
            break

    if blocked:
        return BLOCKED, None, None
    return FOUND, candidate_idx, candidate_delta


def _hitmechanics_etterna(
    *,
    now: float,
    note_indices: list[int],
    start_index: int,
    notes: list[NoteEntry],
    early_window: float,
    late_window: float,
) -> tuple[str, Optional[int], Optional[float]]:
    window_start = now - late_window
    window_end = now - early_window

    best: Optional[tuple[int, float]] = None
    i = start_index
    while i < len(note_indices):
        idx = note_indices[i]
        note = notes[idx]
        if note.time_ms > window_end:
            break
        if note.status == HIT_REQUIRED and note.time_ms >= window_start:
            delta = now - note.time_ms
            if best is None or abs(delta) < abs(best[1]) or (abs(delta) == abs(best[1]) and idx < best[0]):
                best = (idx, delta)
        i += 1

    if best is None:
        return NOTFOUND, None, None
    return FOUND, best[0], best[1]


def _hitmechanics_osumania(
    *,
    now: float,
    col: int,
    note_indices: list[int],
    start_index: int,
    notes: list[NoteEntry],
    early_window: float,
    late_window: float,
) -> tuple[str, Optional[int], Optional[float]]:
    window_start = now - late_window
    window_end = now - early_window

    i = start_index
    while i < len(note_indices):
        idx = note_indices[i]
        note = notes[idx]
        if note.time_ms > window_end:
            break

        delta = now - note.time_ms
        if note.status == HIT_ACCEPTED and delta < 0.0:
            return BLOCKED, None, None

        if note.status == HIT_REQUIRED and note.time_ms >= window_start:
            return FOUND, idx, delta

        i += 1

    return NOTFOUND, None, None


def _expire_notes(
    *,
    now: float,
    notes: list[NoteEntry],
    notes_by_col: dict[int, list[int]],
    tails_by_col: dict[int, list[int]],
    note_start_index: dict[int, int],
    tail_start_index: dict[int, int],
    late_note_window: float,
    late_release_window: float,
    matched_events: list[dict[str, Any]],
    hold_states: list[HoldState],
) -> None:
    for col, indices in notes_by_col.items():
        ptr = note_start_index[col]
        while ptr < len(indices):
            idx = indices[ptr]
            note = notes[idx]
            if note.time_ms + late_note_window >= now:
                break

            if note.status == HIT_REQUIRED:
                note.status = MISS
                note.hold_state = "MissedHead" if note.note_kind == NOTE_HOLD_HEAD else None
                matched_events.append(
                    _build_event_dict(
                        index=note.index,
                        time_ms=note.time_ms,
                        column=note.column,
                        action="MISS",
                        note_kind=note.note_kind,
                        press_time=None,
                        release_time=None,
                        delta=None,
                        head_delta=note.head_delta,
                        tail_delta=note.tail_delta,
                        hold_state=note.hold_state,
                        blocked=False,
                        judgement_index=None,
                        notes_map_index=note.index,
                    )
                )

                # 头 miss 时把尾也标记为 miss，避免遗留 RELEASE_REQUIRED。
                if note.tail_index is not None:
                    tail = notes[note.tail_index]
                    if tail.status == RELEASE_REQUIRED:
                        tail.status = MISS
                        tail.hold_state = "MissedHead"
                        matched_events.append(
                            _build_event_dict(
                                index=tail.index,
                                time_ms=tail.time_ms,
                                column=tail.column,
                                action="MISS",
                                note_kind=tail.note_kind,
                                press_time=None,
                                release_time=None,
                                delta=None,
                                head_delta=note.head_delta,
                                tail_delta=None,
                                hold_state="MissedHead",
                                blocked=False,
                                judgement_index=None,
                                notes_map_index=tail.index,
                            )
                        )
                        state = hold_states[col]
                        if state.active and state.head_index == note.index:
                            hold_states[col] = HoldState()

            ptr += 1
        note_start_index[col] = ptr

    for col, tail_indices in tails_by_col.items():
        ptr = tail_start_index[col]
        while ptr < len(tail_indices):
            idx = tail_indices[ptr]
            tail = notes[idx]
            if tail.time_ms + late_release_window >= now:
                break
            if tail.status == RELEASE_REQUIRED:
                tail.status = DROP_HOLD
                tail.hold_state = "Dropped"
                matched_events.append(
                    _build_event_dict(
                        index=tail.index,
                        time_ms=tail.time_ms,
                        column=tail.column,
                        action="DROP_HOLD",
                        note_kind=tail.note_kind,
                        press_time=tail.press_time,
                        release_time=tail.release_time,
                        delta=None,
                        head_delta=tail.head_delta,
                        tail_delta=tail.tail_delta,
                        hold_state="Dropped",
                        blocked=False,
                        judgement_index=None,
                        notes_map_index=tail.index,
                    )
                )

                if tail.head_index is not None:
                    head = notes[tail.head_index]
                    if head.hold_state in (None, "Holding"):
                        head.hold_state = "Dropped"
                state = hold_states[col]
                if state.active and state.tail_index == tail.index:
                    hold_states[col] = HoldState()

            ptr += 1
        tail_start_index[col] = ptr


def _apply_press(
    *,
    now: float,
    col: int,
    outcome: str,
    note_index: Optional[int],
    delta: Optional[float],
    notes: list[NoteEntry],
    hold_states: list[HoldState],
    matched_events: list[dict[str, Any]],
    offset_vector: list[Optional[float]],
    delta_list: list[tuple[int, float]],
    matched_pairs: list[tuple[int, float, float]],
    unmatched_presses: list[tuple[int, float]],
    accepted_history: list[dict[str, float]],
    judgement_windows: list[tuple[int, float, float]],
    ghost_tap_judgement: Optional[int],
) -> None:
    if outcome == FOUND and note_index is not None and delta is not None:
        note = notes[note_index]
        note.status = HIT_ACCEPTED
        note.matched = True
        note.press_time = now
        note.delta = delta
        note.head_delta = delta if note.note_kind == NOTE_HOLD_HEAD else note.head_delta
        note.hold_state = "Holding" if note.note_kind == NOTE_HOLD_HEAD else note.hold_state
        note.judgement_index = _infer_judgement_index(delta, judgement_windows)

        action = "HOLD_HEAD" if note.note_kind == NOTE_HOLD_HEAD else "HIT"
        offset_vector[note.index] = float(delta)
        delta_list.append((col, float(delta)))
        matched_pairs.append((col, float(note.time_ms), float(now)))

        matched_events.append(
            _build_event_dict(
                index=note.index,
                time_ms=note.time_ms,
                column=note.column,
                action=action,
                note_kind=note.note_kind,
                press_time=now,
                release_time=None,
                delta=delta,
                head_delta=note.head_delta,
                tail_delta=note.tail_delta,
                hold_state=note.hold_state,
                blocked=False,
                judgement_index=note.judgement_index,
                notes_map_index=note.index,
            )
        )

        accepted_history.append(
            {
                "column": float(col),
                "note_time": float(note.time_ms),
                "press_time": float(now),
                "delta": float(delta),
            }
        )

        if note.note_kind == NOTE_HOLD_HEAD and note.tail_index is not None:
            tail = notes[note.tail_index]
            tail.head_delta = delta
            hold_states[col] = HoldState(
                active=True,
                head_index=note.index,
                tail_index=tail.index,
                press_time=now,
            )
        return

    unmatched_presses.append((col, float(now)))
    blocked = outcome == BLOCKED

    if blocked or ghost_tap_judgement is not None:
        matched_events.append(
            _build_event_dict(
                index=-1,
                time_ms=float(now),
                column=col,
                action="GHOST_TAP",
                note_kind=NOTE_KIND_ANY,
                press_time=now,
                release_time=None,
                delta=None,
                head_delta=None,
                tail_delta=None,
                hold_state=None,
                blocked=blocked,
                judgement_index=ghost_tap_judgement,
                notes_map_index=None,
            )
        )


def _apply_release(
    *,
    now: float,
    col: int,
    notes: list[NoteEntry],
    hold_states: list[HoldState],
    release_early_window: float,
    release_late_window: float,
    release_judgement_windows: list[tuple[int, float, float]],
    matched_events: list[dict[str, Any]],
    offset_vector: list[Optional[float]],
) -> None:
    state = hold_states[col]
    if not state.active or state.tail_index is None:
        return

    tail = notes[state.tail_index]
    head = notes[state.head_index] if state.head_index is not None else None

    tail.release_time = now
    tail.press_time = state.press_time
    tail_delta = now - tail.time_ms
    tail.tail_delta = tail_delta

    if release_early_window <= tail_delta <= release_late_window:
        tail.status = RELEASE_ACCEPTED
        tail.matched = True
        tail.hold_state = "Released"
        tail.judgement_index = _infer_judgement_index(tail_delta, release_judgement_windows)
        offset_vector[tail.index] = float(tail_delta)

        if head is not None:
            head.release_time = now
            head.tail_delta = tail_delta
            head.hold_state = "Released"

        matched_events.append(
            _build_event_dict(
                index=tail.index,
                time_ms=tail.time_ms,
                column=tail.column,
                action="RELEASE",
                note_kind=tail.note_kind,
                press_time=tail.press_time,
                release_time=now,
                delta=tail_delta,
                head_delta=tail.head_delta,
                tail_delta=tail_delta,
                hold_state="Released",
                blocked=False,
                judgement_index=tail.judgement_index,
                notes_map_index=tail.index,
            )
        )
    else:
        tail.status = DROP_HOLD
        tail.hold_state = "Dropped"
        if head is not None and head.status == HIT_ACCEPTED:
            head.release_time = now
            head.tail_delta = tail_delta
            head.hold_state = "Dropped"

        matched_events.append(
            _build_event_dict(
                index=tail.index,
                time_ms=tail.time_ms,
                column=tail.column,
                action="DROP_HOLD",
                note_kind=tail.note_kind,
                press_time=tail.press_time,
                release_time=now,
                delta=tail_delta,
                head_delta=tail.head_delta,
                tail_delta=tail_delta,
                hold_state="Dropped",
                blocked=False,
                judgement_index=None,
                notes_map_index=tail.index,
            )
        )

    hold_states[col] = HoldState()


