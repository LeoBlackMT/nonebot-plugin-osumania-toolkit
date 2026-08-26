"""Matching helpers — ported from YAVSRG Interlude Events.fs / HitMechanics.fs."""
from __future__ import annotations

import bisect
import lzma
import struct
from dataclasses import dataclass
from typing import Any, Optional

from ...parser.osr_file_parser import osr_file
from ...parser.osu_file_parser import NOTE_HOLD_HEAD, NOTE_HOLD_TAIL, NOTE_NORMAL, osu_file

NOTE_KIND_ANY = 0
HIT_REQUIRED = "HIT_REQUIRED"
HIT_HOLD_REQUIRED = "HIT_HOLD_REQUIRED"
HIT_ACCEPTED = "HIT_ACCEPTED"
RELEASE_REQUIRED = "RELEASE_REQUIRED"
RELEASE_ACCEPTED = "RELEASE_ACCEPTED"

FOUND = "FOUND"
BLOCKED = "BLOCKED"
NOTFOUND = "NOTFOUND"

# HoldStateInternal (Events.fs)
H_NOTHING = "H_NOTHING"
H_HOLDING = "H_HOLDING"
H_DROPPED = "H_DROPPED"
H_REGRABBED = "H_REGRABBED"
H_MISSED_HEAD_DROPPED = "H_MISSED_HEAD_DROPPED"
H_MISSED_HEAD_REGRABBED = "H_MISSED_HEAD_REGRABBED"

_IS_DROPPED = frozenset({H_DROPPED, H_REGRABBED, H_MISSED_HEAD_DROPPED, H_MISSED_HEAD_REGRABBED})
_IS_MISSED_HEAD = frozenset({H_MISSED_HEAD_DROPPED, H_MISSED_HEAD_REGRABBED})


def f32(value: float) -> float:
    """IEEE-754 binary32 round trip (F# float32 semantics)."""
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def f32div(a: float, b: float) -> float:
    """float32 division (F# `delta / rate` stays in float32)."""
    import numpy as np

    return float(np.float32(np.float32(a) / np.float32(b)))


@dataclass(slots=True)
class NoteEntry:
    index: int
    row_index: int
    time_ms: float
    column: int
    note_kind: int
    status: str
    tail_index: Optional[int] = None
    head_index: Optional[int] = None
    delta: Optional[float] = None
    head_delta: Optional[float] = None
    tail_delta: Optional[float] = None
    press_time: Optional[float] = None
    release_time: Optional[float] = None
    hold_state: Optional[str] = None
    matched: bool = False
    judgement_index: Optional[int] = None
    note_start: float = 0.0
    note_end: float = 0.0
    blocked: bool = False


@dataclass(slots=True)
class HoldState:
    state: str = H_NOTHING
    head_index: Optional[int] = None
    tail_index: Optional[int] = None

    @property
    def IsDropped(self) -> bool:
        return self.state in _IS_DROPPED

    @property
    def MissedHead(self) -> bool:
        return self.state in _IS_MISSED_HEAD


def _empty_result(status: str, error: Optional[str], meta: Optional[dict[str, Any]] = None) -> dict:
    return {
        "status": status,
        "error": error,
        "matched_events": [],
        "events_f": [],
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
            "algorithm_version": "interlude_v2",
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


def _note_windows(ruleset_data: dict[str, Any]) -> tuple[float, float, list[tuple[int, float, float]], bool]:
    judgements = ruleset_data.get("Judgements", []) or []
    judgement_windows: list[tuple[int, float, float]] = []

    for idx, judgement in enumerate(judgements):
        if not isinstance(judgement, dict):
            continue
        tw = judgement.get("TimingWindows")
        if not isinstance(tw, list) or len(tw) != 2:
            continue
        if not _is_number(tw[0]) or not _is_number(tw[1]):
            continue
        judgement_windows.append((idx, float(tw[0]), float(tw[1])))

    # Ruleset.NoteWindows: last judgement with a window (loosest); fallback (0, 0)
    for idx in reversed(range(len(judgements))):
        item = judgements[idx]
        if not isinstance(item, dict):
            continue
        tw = item.get("TimingWindows")
        if isinstance(tw, list) and len(tw) == 2 and _is_number(tw[0]) and _is_number(tw[1]):
            return float(tw[0]), float(tw[1]), judgement_windows, bool(judgement_windows)

    return 0.0, 0.0, judgement_windows, bool(judgement_windows)


def _release_windows(
    ruleset_data: dict[str, Any],
    note_early: float,
    note_late: float,
) -> tuple[float, float]:
    """Ruleset.ReleaseWindows (Rulesets.fs), f32 faithful."""
    hold_mechanics = ruleset_data.get("HoldMechanics")
    if not isinstance(hold_mechanics, dict) or len(hold_mechanics) != 1:
        return note_early, note_late

    variant, payload = next(iter(hold_mechanics.items()))

    if variant == "OnlyRequireHold" and _is_number(payload):
        w = float(payload)
        return -w, w

    if variant == "JudgeReleasesSeparately" and isinstance(payload, list) and len(payload) == 2:
        windows = payload[0]
        if isinstance(windows, list):
            for item in reversed(windows):
                if isinstance(item, list) and len(item) == 2 and _is_number(item[0]) and _is_number(item[1]):
                    return float(item[0]), float(item[1])
        return 0.0, 0.0

    if variant == "OnlyJudgeReleases":
        return note_early, note_late

    if variant == "CombineHeadAndTail" and isinstance(payload, dict) and len(payload) == 1:
        sub_variant, sub_payload = next(iter(payload.items()))
        if sub_variant == "HeadJudgementOr" and isinstance(sub_payload, list) and len(sub_payload) >= 2:
            if _is_number(sub_payload[0]) and _is_number(sub_payload[1]):
                return float(sub_payload[0]), float(sub_payload[1])
        if sub_variant == "OsuMania" and isinstance(sub_payload, dict):
            w0 = sub_payload.get("Window0")
            w100 = sub_payload.get("Window100")
            if _is_number(w0) and _is_number(w100):
                return -abs(float(w0)), f32(f32(float(w100)) - 1.0)
            return 0.0, 0.0

    return note_early, note_late


def _release_judgement_windows(
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


def _build_hitflagdata(osu: osu_file, mirror: bool = False) -> tuple[list[NoteEntry], dict[int, list[int]], dict[int, list[int]], int, list[float]]:
    """Build per-(row, column) note entries, mirroring columns when the replay used MR."""
    if hasattr(osu, "to_TimeArray"):
        time_array = osu.to_TimeArray()
    elif hasattr(osu, "note_rows"):
        time_array = list(getattr(osu, "note_rows") or [])
    else:
        return [], {}, {}, 0, []

    keys = int(getattr(osu, "column_count", 0) or 0)
    if keys <= 0:
        return [], {}, {}, 0, []

    def map_col(col: int) -> Optional[int]:
        mapped = (keys - 1 - col) if mirror else col
        return mapped if 0 <= mapped < keys else None

    row_index_of: dict[float, int] = {}
    notes: list[NoteEntry] = []
    pending_heads: dict[int, list[int]] = {col: [] for col in range(keys)}
    row_times: list[float] = []

    for time_ms, row in sorted(time_array, key=lambda item: float(item[0])):
        t = float(time_ms)
        if not isinstance(row, list):
            continue
        if t not in row_index_of:
            row_index_of[t] = len(row_times)
            row_times.append(t)
        row_idx = row_index_of[t]

        limit = min(keys, len(row))
        # 行内按映射后列升序产出（mirror 时原始列逆序映射），使行内事件顺序与 F# 逐列升序一致
        for mapped in range(keys):
            col = (keys - 1 - mapped) if mirror else mapped
            if col >= limit:
                continue
            note_kind = int(row[col] or 0)
            if note_kind == 0:
                continue
            mapped = map_col(col)
            if mapped is None:
                continue

            if note_kind == NOTE_NORMAL:
                notes.append(
                    NoteEntry(
                        index=len(notes),
                        row_index=row_idx,
                        time_ms=t,
                        column=mapped,
                        note_kind=NOTE_NORMAL,
                        status=HIT_REQUIRED,
                        note_start=t,
                        note_end=t,
                    )
                )
            elif note_kind == NOTE_HOLD_HEAD:
                idx = len(notes)
                notes.append(
                    NoteEntry(
                        index=idx,
                        row_index=row_idx,
                        time_ms=t,
                        column=mapped,
                        note_kind=NOTE_HOLD_HEAD,
                        status=HIT_HOLD_REQUIRED,
                        note_start=t,
                        note_end=t,
                    )
                )
                pending_heads[mapped].append(idx)
            elif note_kind == NOTE_HOLD_TAIL:
                idx = len(notes)
                notes.append(
                    NoteEntry(
                        index=idx,
                        row_index=row_idx,
                        time_ms=t,
                        column=mapped,
                        note_kind=NOTE_HOLD_TAIL,
                        status=RELEASE_REQUIRED,
                        note_start=t,
                        note_end=t,
                    )
                )
                if pending_heads[mapped]:
                    head_idx = pending_heads[mapped].pop(0)
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

    return notes, notes_by_col, tails_by_col, keys, row_times


def _retime_frames(
    osr: osr_file,
    first_note: float,
    source_rate: float,
) -> list[tuple[float, int]]:
    """Rebuild replay frames as chart-relative ms with F# decode semantics.

    osu! .osr payload deltas are accumulated in float32; only frames whose
    key state changed are emitted; times are (t - first_note) * source_rate.
    """
    compressed = getattr(osr, "compressed_data", None)
    if not compressed:
        return []

    try:
        text = lzma.decompress(compressed).decode("ascii", "ignore")
    except Exception:
        return []

    t = 0.0
    last_state = 256
    first_f32 = f32(first_note)
    rate_f = f32(source_rate)
    frames: list[tuple[float, int]] = []
    for entry in text.split(","):
        parts = entry.split("|")
        if len(parts) < 2 or parts[0] == "-12345":
            continue
        t = f32(t + f32(float(parts[0])))
        state = int(parts[1])
        if state != last_state:
            frames.append((f32(f32(t - first_f32) * rate_f), state))
            last_state = state
    return frames


def _hitmechanics_interlude(
    *,
    now: float,
    col: int,
    note_indices: list[int],
    start_index: int,
    notes: list[NoteEntry],
    early_window: float,
    late_window: float,
    cbrush_window: float,
    cbrush_raw: float,
) -> tuple[str, Optional[int], Optional[float]]:
    """HitMechanics.interlude (HitMechanics.fs) verbatim."""
    end_of_window = f32(now - early_window)
    closest_bad_delta = late_window
    closest_note_index = -1
    closest_note_delta = late_window

    i = start_index
    while i < len(note_indices):
        note_idx = note_indices[i]
        note = notes[note_idx]
        if note.time_ms > end_of_window:
            break

        delta = f32(now - f32(note.time_ms))

        if note.status in (HIT_REQUIRED, HIT_HOLD_REQUIRED):
            if closest_note_index < 0 or abs(closest_note_delta) > abs(delta):
                closest_note_index = note_idx
                closest_note_delta = delta
            if abs(closest_note_delta) < cbrush_window:
                i = len(note_indices)
        elif note.status == HIT_ACCEPTED and note.delta is not None and note.delta <= f32(-cbrush_raw):
            if abs(closest_bad_delta) > abs(delta):
                closest_bad_delta = delta

        i += 1

    if closest_note_index >= 0:
        if abs(closest_bad_delta) < abs(closest_note_delta):
            return BLOCKED, None, None
        return FOUND, closest_note_index, closest_note_delta
    return NOTFOUND, None, None


def _hitmechanics_etterna(
    *,
    now: float,
    note_indices: list[int],
    start_index: int,
    notes: list[NoteEntry],
    early_window: float,
    late_window: float,
) -> tuple[str, Optional[int], Optional[float]]:
    """HitMechanics.etterna (HitMechanics.fs) verbatim."""
    end_of_window = f32(now - early_window)
    closest_note_index = -1
    closest_note_delta = 0.0

    i = start_index
    while i < len(note_indices):
        note_idx = note_indices[i]
        note = notes[note_idx]
        if note.time_ms > end_of_window:
            break

        delta = f32(now - f32(note.time_ms))
        if note.status in (HIT_REQUIRED, HIT_HOLD_REQUIRED):
            if closest_note_index < 0 or abs(closest_note_delta) > abs(delta):
                closest_note_index = note_idx
                closest_note_delta = delta
        i += 1

    if closest_note_index >= 0:
        return FOUND, closest_note_index, closest_note_delta
    return NOTFOUND, None, None


def _hitmechanics_osumania(
    *,
    now: float,
    note_indices: list[int],
    start_index: int,
    notes: list[NoteEntry],
    early_window: float,
    late_window: float,
) -> tuple[str, Optional[int], Optional[float]]:
    """HitMechanics.osu_mania (HitMechanics.fs) verbatim."""
    end_of_window = f32(now - early_window)
    candidate_note_index = -1
    candidate_note_delta = 0.0
    blocked = False

    i = start_index
    while i < len(note_indices):
        note_idx = note_indices[i]
        note = notes[note_idx]
        if note.time_ms > end_of_window:
            break

        delta = f32(now - f32(note.time_ms))
        if note.status == HIT_ACCEPTED and delta < 0.0:
            blocked = True
            i = len(note_indices)

        if note.status in (HIT_REQUIRED, HIT_HOLD_REQUIRED):
            candidate_note_index = note_idx
            candidate_note_delta = delta
            i = len(note_indices)

        i += 1

    if blocked:
        return BLOCKED, None, None
    if candidate_note_index >= 0:
        return FOUND, candidate_note_index, candidate_note_delta
    return NOTFOUND, None, None


def _first_tail_at_or_after(tails: list[int], notes: list[NoteEntry], target_index: int) -> int:
    """Earliest tail note index >= target_index (F# row scan equivalent)."""
    lo, hi = 0, len(tails)
    while lo < hi:
        mid = (lo + hi) // 2
        if notes[tails[mid]].index < target_index:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _legacy_event_dict(
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


def _f_event(
    index: int,
    time: float,
    column: int,
    action: str,
    delta: Optional[float],
) -> dict[str, Any]:
    return {
        "index": int(index),
        "time": float(time),
        "column": int(column),
        "action": action,
        "delta": None if delta is None else float(delta),
    }