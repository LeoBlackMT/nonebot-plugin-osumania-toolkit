# -*- coding: utf-8 -*-
"""
移植：prelude/src/Calculator/Patterns/Patterns.fs
ref: 9786913f5e52e6ef0fb51fdacc8c7c61f42728d0

注意：
- PatternRecognizer：接收 (RowInfo list) 并返回 int
- 这里的 RowInfo / Direction 来自 patterns/primitives.py
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, List, Tuple

from nonebot import get_plugin_config

from ...config import Config
from .primitives import RowInfo, Direction, detect_direction

config = get_plugin_config(Config)

COORDINATION_SPECIFIC_ORDER = config.coordination_specific_order
CORE_RATING_MULTIPLIER = config.core_rating_multiplier
DENSITY_SPECIFIC_ORDER = config.density_specific_order
INVERSE_GAP_TOLERANCE_MS = config.inverse_gap_tolerance_ms
INVERSE_MIN_FILLED_LANES = config.inverse_min_filled_lanes
JACKY_CONTEXT_WINDOW = config.jacky_context_window
JACKY_FALLBACK_MAX_MSPB = config.jacky_fallback_max_mspb
JACKY_MIN_BPM = config.jacks_min_bpm
RELEASE_FULL_MATCH_ROWS = config.release_full_match_rows
RELEASE_MIN_TAIL_ROWS = config.release_min_tail_rows
RELEASE_ROLL_POINTS = config.release_roll_points
RELEASE_SCAN_ROWS = config.release_scan_rows
SHIELD_MAX_BEAT_RATIO = config.shield_max_beat_ratio
SUBTYPE_RATING_MULTIPLIER_BY_MODE = config.subtype_rating_multiplier_by_mode
RC_CORE_LN_SCALE = config.rc_core_ln_scale
RC_LN_CORE_SCALE = config.rc_ln_core_scale
WILDCARD_SPECIFIC_ORDER = config.wildcard_specific_order


# -----------------------------
# CorePattern（对应 F# 判别联合类型）
# -----------------------------

class CorePattern(Enum):
    Stream = "Stream"
    Chordstream = "Chordstream"
    Jacks = "Jacks"
    Coordination = "Coordination"
    Density = "Density"
    Wildcard = "Wildcard"
    
    @property
    def RatingMultiplier(self) -> float:
        return CORE_RATING_MULTIPLIER.get(self.value, 1.0)


def resolve_rating_multiplier(pattern: CorePattern, specific_type: str | None, mode_tag: str = "Mix") -> float:
    ln_core_patterns = {CorePattern.Coordination, CorePattern.Density, CorePattern.Wildcard}
    rc_core_patterns = {CorePattern.Stream, CorePattern.Chordstream, CorePattern.Jacks}

    default_multiplier = pattern.RatingMultiplier

    subtype_map = SUBTYPE_RATING_MULTIPLIER_BY_MODE.get(mode_tag, SUBTYPE_RATING_MULTIPLIER_BY_MODE.get("Mix", {}))

    value = default_multiplier if specific_type is None else subtype_map.get(specific_type, default_multiplier)

    if mode_tag == "RC" and pattern in ln_core_patterns:
        mix_map = SUBTYPE_RATING_MULTIPLIER_BY_MODE.get("Mix", {})
        base = default_multiplier if specific_type is None else mix_map.get(specific_type, default_multiplier)
        value = base * RC_LN_CORE_SCALE

    if mode_tag == "LN" and pattern in rc_core_patterns:
        value *= RC_CORE_LN_SCALE

    return value

PatternRecognizer = Callable[[List[RowInfo]], int]


def _reorder_specific(
    items: List[Tuple[str, PatternRecognizer]],
    preferred_order: List[str],
) -> List[Tuple[str, PatternRecognizer]]:
    if len(items) <= 1 or len(preferred_order) == 0:
        return items
    order_rank = {name: idx for idx, name in enumerate(preferred_order)}
    with_index = list(enumerate(items))
    with_index.sort(key=lambda pair: (order_rank.get(pair[1][0], len(order_rank)), pair[0]))
    return [item for _, item in with_index]


def _as_head_point_row(row: RowInfo, previous_head_cols: List[int]) -> RowInfo:
    head_cols = row.LNHeads
    jacks = len(set(head_cols).intersection(previous_head_cols)) if len(head_cols) > 0 else 0
    direction = Direction.None_
    roll = False
    if len(previous_head_cols) > 0 and len(head_cols) > 0:
        direction, roll = detect_direction(previous_head_cols, head_cols)
    return RowInfo(
        Index=row.Index,
        Time=row.Time,
        MsPerBeat=row.MsPerBeat,
        BeatLength=row.BeatLength,
        Notes=len(head_cols),
        Jacks=jacks,
        Direction=direction,
        Roll=roll,
        Keys=row.Keys,
        LeftHandKeys=row.LeftHandKeys,
        LNHeads=row.LNHeads,
        LNBodies=row.LNBodies,
        LNTails=row.LNTails,
        NormalNotes=[],
        RawNotes=head_cols,
    )


def _head_rows(xs: List[RowInfo], n: int) -> List[RowInfo]:
    rows: List[RowInfo] = []
    prev: List[int] = []
    for row in xs[:n]:
        hr = _as_head_point_row(row, prev)
        rows.append(hr)
        if len(hr.RawNotes) > 0:
            prev = hr.RawNotes
    return rows


def _is_same_hand_adjacent(col_a: int, col_b: int, split: int) -> bool:
    if abs(col_a - col_b) != 1:
        return False
    left_a = col_a < split
    left_b = col_b < split
    return left_a == left_b


def _jack_bpm(delta_ms: float) -> float:
    if delta_ms <= 0.0:
        return 230.0
    return min(15000.0 / delta_ms, 230.0)


def _is_ln_head_context(xs: List[RowInfo]) -> bool:
    return len(xs) > 0 and len(xs[0].LNHeads) > 0


def _has_ln_context(xs: List[RowInfo], window: int) -> bool:
    for row in xs[:window]:
        if len(row.LNHeads) > 0 or len(row.LNBodies) > 0 or len(row.LNTails) > 0:
            return True
    return False


def _inverse_ready(xs: List[RowInfo]) -> bool:
    if len(xs) < 5:
        return False
    win = xs[:5]
    if any(len(r.NormalNotes) > 0 for r in win):
        return False
    if max((len(r.LNBodies) for r in win), default=0) < INVERSE_MIN_FILLED_LANES:
        return False

    gaps: List[float] = []
    for i in range(len(win) - 1):
        if len(win[i].LNTails) > 0 and len(win[i + 1].LNHeads) > 0:
            gaps.append(win[i + 1].Time - win[i].Time)

    if len(gaps) < 2:
        return False
    return (max(gaps) - min(gaps)) <= INVERSE_GAP_TOLERANCE_MS


# -----------------------------
# 核心识别器（module Core）
# -----------------------------

def CORE_STREAM(xs: List[RowInfo]) -> int:
    # | {Notes=1;Jacks=0;RawNotes=x}::{Notes=1;Jacks=0}::{Notes=1;Jacks=0}::{Notes=1;Jacks=0}::{Notes=1;Jacks=0;RawNotes=y}::_ when x[0]<>y[0] -> 5
    if len(xs) < 5:
        return 0
    a, b, c, d, e = xs[0], xs[1], xs[2], xs[3], xs[4]
    if (
        a.Notes == 1 and a.Jacks == 0 and
        b.Notes == 1 and b.Jacks == 0 and
        c.Notes == 1 and c.Jacks == 0 and
        d.Notes == 1 and d.Jacks == 0 and
        e.Notes == 1 and e.Jacks == 0
    ):
        # RawNotes 是 int list，F# 里 x.[0]
        if a.RawNotes[0] != e.RawNotes[0]:
            return 5
    return 0


def CORE_JACKS(xs: List[RowInfo]) -> int:
    # | {Jacks=x;MsPerBeat=mspb}::_ when x>1 && mspb<2000 -> 1
    if len(xs) < 1:
        return 0
    x0 = xs[0]
    if x0.Jacks > 1 and x0.MsPerBeat < 2000.0:
        return 1
    return 0


def CORE_CHORDSTREAM(xs: List[RowInfo]) -> int:
    # | {Notes=a;Jacks=0}::{Notes=b;Jacks=0}::{Notes=c;Jacks=0}::{Notes=d;Jacks=0}::_ when a>1 && (b>1||c>1||d>1) -> 4
    if len(xs) < 4:
        return 0
    a, b, c, d = xs[0], xs[1], xs[2], xs[3]
    if a.Notes > 1 and a.Jacks == 0 and b.Jacks == 0 and c.Jacks == 0 and d.Jacks == 0:
        if (b.Notes > 1) or (c.Notes > 1) or (d.Notes > 1):
            return 4
    return 0


def CORE_COORDINATION(xs: List[RowInfo]) -> int:
    if len(xs) < 1:
        return 0
    a = xs[0]
    if len(a.LNHeads) > 0 or len(a.LNBodies) > 0 or len(a.LNTails) > 0:
        return 1
    return 0


def CORE_DENSITY(xs: List[RowInfo]) -> int:
    if len(xs) < 1:
        return 0
    if _is_ln_head_context(xs):
        return 1
    return 0


def CORE_WILDCARD(xs: List[RowInfo]) -> int:
    if len(xs) < 1:
        return 0
    if _is_ln_head_context(xs):
        return 1
    return 0


# -----------------------------
# 连打模块（Jacks）
# -----------------------------

def JACKS_CHORDJACKS(xs: List[RowInfo]) -> int:
    # | {Notes=a}::{Notes=b;Jacks=j}::_ when a>2 && b>1 && j>=1 && (b<a || j<b) -> 2
    if len(xs) < 2:
        return 0
    a, b = xs[0], xs[1]
    if a.Notes > 2 and b.Notes > 1 and b.Jacks >= 1 and ((b.Notes < a.Notes) or (b.Jacks < b.Notes)):
        return 2
    return 0


def JACKS_MINIJACKS(xs: List[RowInfo]) -> int:
    # | {Jacks=x}::{Jacks=0}::_ when x>0 -> 2
    if len(xs) < 2:
        return 0
    a, b = xs[0], xs[1]
    if a.Jacks > 0 and b.Jacks == 0:
        return 2
    return 0


def JACKS_LONGJACKS(xs: List[RowInfo]) -> int:
    # | {Jacks=a;RawNotes=ra}::{Jacks=b;RawNotes=rb}::{Jacks=c;RawNotes=rc}::{Jacks=d;RawNotes=rd}::{Jacks=e;RawNotes=re}::_ when a>0&&b>0&&c>0&&d>0&&e>0 ->
    #     if exists x in ra where x in rb && x in rc && x in rd && x in re then 5 else 0
    if len(xs) < 5:
        return 0
    a, b, c, d, e = xs[0], xs[1], xs[2], xs[3], xs[4]
    if a.Jacks > 0 and b.Jacks > 0 and c.Jacks > 0 and d.Jacks > 0 and e.Jacks > 0:
        ra, rb, rc, rd, re = a.RawNotes, b.RawNotes, c.RawNotes, d.RawNotes, e.RawNotes
        for x in ra:
            if (x in rb) and (x in rc) and (x in rd) and (x in re):
                return 5
        return 0
    return 0


# -----------------------------
# 4K 连打模块（Jacks_4K）
# -----------------------------

def JACKS_4K_QUADSTREAM(xs: List[RowInfo]) -> int:
    # | {Notes=4}::_::{Jacks=0}::{Jacks=0}::_ -> 4
    if len(xs) < 4:
        return 0
    a, _, c, d = xs[0], xs[1], xs[2], xs[3]
    if a.Notes == 4 and c.Jacks == 0 and d.Jacks == 0:
        return 4
    return 0


def JACKS_4K_GLUTS(xs: List[RowInfo]) -> int:
    # | {RawNotes=ra}::{Jacks=1;RawNotes=rb}::{Jacks=1;RawNotes=rc}::_ ->
    #     if exists x in ra where x in rb && x in rc then 0 else 3
    if len(xs) < 3:
        return 0
    a, b, c = xs[0], xs[1], xs[2]
    ra, rb, rc = a.RawNotes, b.RawNotes, c.RawNotes
    if b.Jacks == 1 and c.Jacks == 1:
        for x in ra:
            if (x in rb) and (x in rc):
                return 0
        return 3
    return 0


# -----------------------------
# 4K 和弦流模块（Chordstream_4K）
# -----------------------------

def CHORDSTREAM_4K_HANDSTREAM(xs: List[RowInfo]) -> int:
    # | {Notes=3;Jacks=0}::{Jacks=0}::{Jacks=0}::{Jacks=0}::_ -> 4
    if len(xs) < 4:
        return 0
    a, b, c, d = xs[0], xs[1], xs[2], xs[3]
    if a.Notes == 3 and a.Jacks == 0 and b.Jacks == 0 and c.Jacks == 0 and d.Jacks == 0:
        return 4
    return 0


def CHORDSTREAM_4K_JUMPSTREAM(xs: List[RowInfo]) -> int:
    # | {Notes=2;Jacks=0}::{Notes=1;Jacks=0}::{Notes=a;Jacks=0}::{Notes=b;Jacks=0}::_ when a<3 && b<3 -> 4
    if len(xs) < 4:
        return 0
    a, b, c, d = xs[0], xs[1], xs[2], xs[3]
    if a.Notes == 2 and a.Jacks == 0 and b.Notes == 1 and b.Jacks == 0 and c.Jacks == 0 and d.Jacks == 0:
        if c.Notes < 3 and d.Notes < 3:
            return 4
    return 0


def CHORDSTREAM_4K_DOUBLE_JUMPSTREAM(xs: List[RowInfo]) -> int:
    # | {Notes=1;Jacks=0}::{Notes=2;Jacks=0}::{Notes=2;Jacks=0}::{Notes=1;Jacks=0}::_ -> 4
    if len(xs) < 4:
        return 0
    a, b, c, d = xs[0], xs[1], xs[2], xs[3]
    if (
        a.Notes == 1 and a.Jacks == 0 and
        b.Notes == 2 and b.Jacks == 0 and
        c.Notes == 2 and c.Jacks == 0 and
        d.Notes == 1 and d.Jacks == 0
    ):
        return 4
    return 0


def CHORDSTREAM_4K_TRIPLE_JUMPSTREAM(xs: List[RowInfo]) -> int:
    # | {Notes=1;Jacks=0}::{Notes=2;Jacks=0}::{Notes=2;Jacks=0}::{Notes=2;Jacks=0}::{Notes=1;Jacks=0}::_ -> 4
    if len(xs) < 5:
        return 0
    a, b, c, d, e = xs[0], xs[1], xs[2], xs[3], xs[4]
    if (
        a.Notes == 1 and a.Jacks == 0 and
        b.Notes == 2 and b.Jacks == 0 and
        c.Notes == 2 and c.Jacks == 0 and
        d.Notes == 2 and d.Jacks == 0 and
        e.Notes == 1 and e.Jacks == 0
    ):
        return 4
    return 0


def CHORDSTREAM_4K_JUMPTRILL(xs: List[RowInfo]) -> int:
    # | {Notes=2}::{Notes=2;Roll=true}::{Notes=2;Roll=true}::{Notes=2;Roll=true}::_ -> 4
    if len(xs) < 4:
        return 0
    a, b, c, d = xs[0], xs[1], xs[2], xs[3]
    if a.Notes == 2 and b.Notes == 2 and c.Notes == 2 and d.Notes == 2 and b.Roll and c.Roll and d.Roll:
        return 4
    return 0


def CHORDSTREAM_4K_SPLITTRILL(xs: List[RowInfo]) -> int:
    # | {Notes=2}::{Notes=2;Jacks=0;Roll=false}::{Notes=2;Jacks=0;Roll=false}::_ -> 3
    if len(xs) < 3:
        return 0
    a, b, c = xs[0], xs[1], xs[2]
    if a.Notes == 2 and b.Notes == 2 and c.Notes == 2 and b.Jacks == 0 and c.Jacks == 0 and (not b.Roll) and (not c.Roll):
        return 3
    return 0


# -----------------------------
# 4K 流式模块（Stream_4K）
# -----------------------------

def STREAM_4K_ROLL(xs: List[RowInfo]) -> int:
    # | {Notes=1;Direction=Left}::{Notes=1;Direction=Left}::{Notes=1;Direction=Left}::_ -> 3
    # | {Notes=1;Direction=Right}::{Notes=1;Direction=Right}::{Notes=1;Direction=Right}::_ -> 3
    if len(xs) < 3:
        return 0
    a, b, c = xs[0], xs[1], xs[2]
    if a.Notes == 1 and b.Notes == 1 and c.Notes == 1:
        if a.Direction == Direction.Left and b.Direction == Direction.Left and c.Direction == Direction.Left:
            return 3
        if a.Direction == Direction.Right and b.Direction == Direction.Right and c.Direction == Direction.Right:
            return 3
    return 0


def STREAM_4K_TRILL(xs: List[RowInfo]) -> int:
    # | {RawNotes=a}::{RawNotes=b;Jacks=0}::{RawNotes=c;Jacks=0}::{RawNotes=d;Jacks=0}::_ when a=c && b=d -> 4
    if len(xs) < 4:
        return 0
    a, b, c, d = xs[0], xs[1], xs[2], xs[3]
    if b.Jacks == 0 and c.Jacks == 0 and d.Jacks == 0:
        if a.RawNotes == c.RawNotes and b.RawNotes == d.RawNotes:
            return 4
    return 0


def STREAM_4K_MINITRILL(xs: List[RowInfo]) -> int:
    # | {RawNotes=a}::{RawNotes=b;Jacks=0}::{RawNotes=c;Jacks=0}::{RawNotes=d}::_ when a=c && b<>d -> 4
    if len(xs) < 4:
        return 0
    a, b, c, d = xs[0], xs[1], xs[2], xs[3]
    if b.Jacks == 0 and c.Jacks == 0:
        if a.RawNotes == c.RawNotes and b.RawNotes != d.RawNotes:
            return 4
    return 0


# -----------------------------
# 7K 和弦流模块（Chordstream_7K）
# -----------------------------

def CHORDSTREAM_7K_DOUBLE_STREAMS(xs: List[RowInfo]) -> int:
    # | {Notes=2}::{Notes=2;Jacks=0;Roll=false}::_ -> 2
    if len(xs) < 2:
        return 0
    a, b = xs[0], xs[1]
    if a.Notes == 2 and b.Notes == 2 and b.Jacks == 0 and (not b.Roll):
        return 2
    return 0


def CHORDSTREAM_7K_DENSE_CHORDSTREAM(xs: List[RowInfo]) -> int:
    # | {Notes=x}::{Notes=y;Jacks=0}::_ when x>1 && y>1 -> 2
    if len(xs) < 2:
        return 0
    a, b = xs[0], xs[1]
    if a.Notes > 1 and b.Notes > 1 and b.Jacks == 0:
        return 2
    return 0


def CHORDSTREAM_7K_LIGHT_CHORDSTREAM(xs: List[RowInfo]) -> int:
    # | {Notes=x}::{Notes=y;Jacks=0}::_ when x>1 && y=1 -> 2
    if len(xs) < 2:
        return 0
    a, b = xs[0], xs[1]
    if a.Notes > 1 and b.Notes == 1 and b.Jacks == 0:
        return 2
    return 0


def CHORDSTREAM_7K_CHORD_ROLL(xs: List[RowInfo]) -> int:
    # | {Notes=x}::{Notes=y;Direction=Left;Roll=true}::{Notes=z;Direction=Left;Roll=true}::_ when x>1 && y>1 && z>1 -> 3
    # | {Notes=x}::{Notes=y;Direction=Right;Roll=true}::{Notes=z;Direction=Right;Roll=true}::_ when x>1 && y>1 && z>1 -> 3
    if len(xs) < 3:
        return 0
    a, b, c = xs[0], xs[1], xs[2]
    if a.Notes > 1 and b.Notes > 1 and c.Notes > 1 and b.Roll and c.Roll:
        if b.Direction == Direction.Left and c.Direction == Direction.Left:
            return 3
        if b.Direction == Direction.Right and c.Direction == Direction.Right:
            return 3
    return 0


def CHORDSTREAM_7K_BRACKETS(xs: List[RowInfo]) -> int:
    # | {Notes=x}::{Notes=y;Roll=false;Jacks=0}::{Notes=z;Roll=false;Jacks=0}::_ when x>2 && y>2 && z>2 && x+y+z>9 -> 3
    if len(xs) < 3:
        return 0
    a, b, c = xs[0], xs[1], xs[2]
    if a.Notes > 2 and b.Notes > 2 and c.Notes > 2 and (not b.Roll) and (not c.Roll) and b.Jacks == 0 and c.Jacks == 0:
        if (a.Notes + b.Notes + c.Notes) > 9:
            return 3
    return 0


# -----------------------------
# 其他键型和弦流模块（与 7K 很像，但不含 BRACKETS）
# -----------------------------

def CHORDSTREAM_OTHER_DOUBLE_STREAMS(xs: List[RowInfo]) -> int:
    # 同 7K DOUBLE_STREAMS
    return CHORDSTREAM_7K_DOUBLE_STREAMS(xs)


def CHORDSTREAM_OTHER_DENSE_CHORDSTREAM(xs: List[RowInfo]) -> int:
    return CHORDSTREAM_7K_DENSE_CHORDSTREAM(xs)


def CHORDSTREAM_OTHER_LIGHT_CHORDSTREAM(xs: List[RowInfo]) -> int:
    return CHORDSTREAM_7K_LIGHT_CHORDSTREAM(xs)


def CHORDSTREAM_OTHER_CHORD_ROLL(xs: List[RowInfo]) -> int:
    return CHORDSTREAM_7K_CHORD_ROLL(xs)


# -----------------------------
# 协调类模块（Coordination）
# -----------------------------

def COORDINATION_COLUMN_LOCK(xs: List[RowInfo]) -> int:
    if len(xs) < 3:
        return 0
    split = xs[0].LeftHandKeys

    ln_col = xs[0].LNHeads[0] if len(xs[0].LNHeads) > 0 else None
    if ln_col is None:
        return 0

    adj_cols = [
        c for c in (ln_col - 1, ln_col + 1)
        if 0 <= c < xs[0].Keys and _is_same_hand_adjacent(ln_col, c, split)
    ]
    if len(adj_cols) == 0:
        return 0

    for adj in adj_cols:
        hits: List[float] = []
        for row in xs[:8]:
            # 持续按住 LN（面身）期间看相邻列普通音。
            if ln_col in row.LNBodies and adj in row.NormalNotes:
                hits.append(row.Time)
        if len(hits) < 3:
            continue

        bpms: List[float] = []
        for i in range(len(hits) - 1):
            bpms.append(_jack_bpm(hits[i + 1] - hits[i]))
        if len(bpms) > 0 and max(bpms) >= JACKY_MIN_BPM:
            return 3

    return 0


def COORDINATION_RELEASE(xs: List[RowInfo]) -> int:
    if len(xs) < RELEASE_MIN_TAIL_ROWS:
        return 0

    # 互斥：当前窗口若已命中 Shield / Inverse / JackyWC，则不判定为 Release。
    if COORDINATION_SHIELD(xs) != 0:
        return 0
    if _inverse_ready(xs):
        return 0
    if WILDCARD_JACK(xs) != 0:
        return 0

    picked_rows = [r for r in xs[:RELEASE_SCAN_ROWS] if len(r.LNTails) == 1]
    if len(picked_rows) < RELEASE_MIN_TAIL_ROWS:
        return 0

    use_rows = min(RELEASE_FULL_MATCH_ROWS, len(picked_rows))
    tails = [r.LNTails[0] for r in picked_rows[:use_rows]]
    prev = [tails[0]]
    rows = []
    for i in range(use_rows):
        row = picked_rows[i]
        cur = [tails[i]]
        direction, roll = detect_direction(prev, cur)
        rows.append(
            RowInfo(
                Index=row.Index,
                Time=row.Time,
                MsPerBeat=row.MsPerBeat,
                BeatLength=row.BeatLength,
                Notes=1,
                Jacks=1 if cur[0] in prev else 0,
                Direction=direction,
                Roll=roll,
                Keys=row.Keys,
                LeftHandKeys=row.LeftHandKeys,
                LNHeads=row.LNHeads,
                LNBodies=row.LNBodies,
                LNTails=row.LNTails,
                NormalNotes=[],
                RawNotes=cur,
            )
        )
        prev = cur

    # 第 1 行 direction 基本是占位值（prev==cur），实际判定从第 2 行开始。
    effective_rows = rows[1:] if len(rows) > 1 else []
    if len(effective_rows) < RELEASE_ROLL_POINTS:
        return 0

    matched = False
    if RELEASE_ROLL_POINTS >= 3:
        # 经典 3 点滚动判定。
        matched = STREAM_4K_ROLL(effective_rows[:RELEASE_ROLL_POINTS]) != 0
    else:
        # RELEASE_ROLL_POINTS=2 时使用二点释放切换判定。
        a = effective_rows[0].RawNotes[0]
        b = effective_rows[1].RawNotes[0] if len(effective_rows) > 1 else a
        dt = effective_rows[1].Time - effective_rows[0].Time if len(effective_rows) > 1 else 0.0
        matched = a != b and dt > 0

    if matched:
        return 5 if use_rows >= RELEASE_FULL_MATCH_ROWS else 4
    return 0


def COORDINATION_SHIELD(xs: List[RowInfo]) -> int:
    if len(xs) < 2:
        return 0
    a, b = xs[0], xs[1]
    dt = b.Time - a.Time
    beat_limit = b.BeatLength * SHIELD_MAX_BEAT_RATIO
    if dt < 0 or dt > beat_limit:
        return 0

    # 普通音 -> LN 头
    for col in a.NormalNotes:
        if col in b.LNHeads:
            return 2

    # LN 尾 -> 普通音
    for col in a.LNTails:
        if col in b.NormalNotes:
            return 2

    return 0


# -----------------------------
# 4K 密度模块（Density_4K）
# -----------------------------

def DENSITY_4K_JUMPSTREAM(xs: List[RowInfo]) -> int:
    if len(xs) < 4 or not _is_ln_head_context(xs):
        return 0
    return 4 if CHORDSTREAM_4K_JUMPSTREAM(_head_rows(xs, 4)) != 0 else 0


def DENSITY_4K_HANDSTREAM(xs: List[RowInfo]) -> int:
    if len(xs) < 4 or not _is_ln_head_context(xs):
        return 0
    return 4 if CHORDSTREAM_4K_HANDSTREAM(_head_rows(xs, 4)) != 0 else 0

def DENSITY_4K_INVERSE(xs: List[RowInfo]) -> int:
    return 5 if _inverse_ready(xs) else 0



# -----------------------------
# 7K 密度模块（Density_7K）
# -----------------------------

def DENSITY_7K_DOUBLE_STREAMS(xs: List[RowInfo]) -> int:
    if len(xs) < 2 or not _is_ln_head_context(xs):
        return 0
    return 2 if CHORDSTREAM_7K_DOUBLE_STREAMS(_head_rows(xs, 2)) != 0 else 0

def DENSITY_7K_DENSE_CHORDSTREAM(xs: List[RowInfo]) -> int:
    if len(xs) < 2 or not _is_ln_head_context(xs):
        return 0
    return 2 if CHORDSTREAM_7K_DENSE_CHORDSTREAM(_head_rows(xs, 2)) != 0 else 0

def DENSITY_7K_LIGHT_CHORDSTREAM(xs: List[RowInfo]) -> int:
    if len(xs) < 2 or not _is_ln_head_context(xs):
        return 0
    return 2 if CHORDSTREAM_7K_LIGHT_CHORDSTREAM(_head_rows(xs, 2)) != 0 else 0

def DENSITY_7K_INVERSE(xs: List[RowInfo]) -> int:
    return 5 if _inverse_ready(xs) else 0


# -----------------------------
# 其他键型密度模块（Density_Other）
# -----------------------------

def DENSITY_Other_DOUBLE_STREAMS(xs: List[RowInfo]) -> int:
    return DENSITY_7K_DOUBLE_STREAMS(xs)

def DENSITY_Other_DENSE_CHORDSTREAM(xs: List[RowInfo]) -> int:
    return DENSITY_7K_DENSE_CHORDSTREAM(xs)

def DENSITY_Other_LIGHT_CHORDSTREAM(xs: List[RowInfo]) -> int:
    return DENSITY_7K_LIGHT_CHORDSTREAM(xs)

def DENSITY_Other_INVERSE(xs: List[RowInfo]) -> int:
    return DENSITY_7K_INVERSE(xs)


# -----------------------------
# 万能类模块（Wildcard）
# -----------------------------

def WILDCARD_JACK(xs: List[RowInfo]) -> int:
    if len(xs) < 2 or not _has_ln_context(xs, JACKY_CONTEXT_WINDOW):
        return 0

    # JackyWC 不再仅依赖 LNHeads 派生行，避免把有效 jack 信息过滤掉。
    rows = [r for r in xs[: max(4, JACKY_CONTEXT_WINDOW)] if r.Notes > 0]
    if len(rows) < 2:
        return 0

    if JACKS_CHORDJACKS(rows) != 0 or JACKS_MINIJACKS(rows) != 0:
        return 4

    check_rows = rows[: min(4, len(rows))]
    # 近窗内至少 2 行出现 jack，且存在一行双押以上。
    jack_rows = sum(1 for r in check_rows if r.Jacks > 0)
    if jack_rows >= 2 and any(r.Notes >= 2 for r in check_rows):
        return 3

    # 高速连续 jack 也可判定。
    fastest_mspb = min(r.MsPerBeat for r in check_rows)
    if jack_rows >= 2 and fastest_mspb <= JACKY_FALLBACK_MAX_MSPB:
        return 3
    return 0


def WILDCARD_SPEED(xs: List[RowInfo]) -> int:
    if len(xs) < 2 or not _has_ln_context(xs, 4):
        return 0
    rows = _head_rows(xs, min(4, len(xs)))
    if xs[0].Keys == 4:
        if len(rows) >= 3 and STREAM_4K_ROLL(rows[:3]) != 0:
            return 3
        # 4K 下方向连续或极高速度都可判定为 Speedy。
        if len(rows) >= 2:
            same_dir = rows[0].Direction in (Direction.Left, Direction.Right) and rows[0].Direction == rows[1].Direction
            if same_dir or rows[0].MsPerBeat <= 180.0:
                return 3
    else:
        if len(rows) >= 3 and CHORDSTREAM_7K_CHORD_ROLL(rows[:3]) != 0:
            return 3
        # 非 4K 允许两行连续高密度同向滚动判定。
        if len(rows) >= 2:
            cond = rows[0].Notes >= 2 and rows[1].Notes >= 2 and rows[0].Direction == rows[1].Direction and rows[0].Direction in (Direction.Left, Direction.Right)
            if cond or rows[0].MsPerBeat <= 170.0:
                return 3
    return 0


# -----------------------------
# SpecificPatterns 记录（对应 F# 类型 SpecificPatterns，包含 3 个静态成员）
# -----------------------------

@dataclass
class SpecificPatterns:
    Stream: List[Tuple[str, PatternRecognizer]]
    Chordstream: List[Tuple[str, PatternRecognizer]]
    Jack: List[Tuple[str, PatternRecognizer]]
    Coordination: List[Tuple[str, PatternRecognizer]]
    Density: List[Tuple[str, PatternRecognizer]]
    Wildcard: List[Tuple[str, PatternRecognizer]]


def SPECIFIC_4K() -> SpecificPatterns:
    coordination = _reorder_specific(
        [
            ("Column Lock", COORDINATION_COLUMN_LOCK),
            ("Release", COORDINATION_RELEASE),
            ("Shield", COORDINATION_SHIELD),
        ],
        COORDINATION_SPECIFIC_ORDER,
    )
    density = _reorder_specific(
        [
            ("JS Density", DENSITY_4K_JUMPSTREAM),
            ("HS Density", DENSITY_4K_HANDSTREAM),
            ("Inverse", DENSITY_4K_INVERSE),
        ],
        DENSITY_SPECIFIC_ORDER,
    )
    wildcard = _reorder_specific(
        [
            ("Jacky WC", WILDCARD_JACK),
            ("Speedy WC", WILDCARD_SPEED),
        ],
        WILDCARD_SPECIFIC_ORDER,
    )

    return SpecificPatterns(
        Stream=[
            ("Rolls", STREAM_4K_ROLL),
            ("Trills", STREAM_4K_TRILL),
            ("Minitrills", STREAM_4K_MINITRILL),
        ],
        Chordstream=[
            ("Handstream", CHORDSTREAM_4K_HANDSTREAM),
            ("Split Trill", CHORDSTREAM_4K_SPLITTRILL),
            ("Jumptrill", CHORDSTREAM_4K_JUMPTRILL),
            # F# 里注释掉了 Triple/Double Jumpstream
            # ("Triple Jumpstream", CHORDSTREAM_4K_TRIPLE_JUMPSTREAM),
            # ("Double Jumpstream", CHORDSTREAM_4K_DOUBLE_JUMPSTREAM),
            ("Jumpstream", CHORDSTREAM_4K_JUMPSTREAM),
        ],
        Jack=[
            ("Longjacks", JACKS_LONGJACKS),
            ("Quadstream", JACKS_4K_QUADSTREAM),
            ("Gluts", JACKS_4K_GLUTS),
            ("Chordjacks", JACKS_CHORDJACKS),
            ("Minijacks", JACKS_MINIJACKS),
        ],
        Coordination=coordination,
        Density=density,
        Wildcard=wildcard,
    )


def SPECIFIC_7K() -> SpecificPatterns:
    coordination = _reorder_specific(
        [
            ("Column Lock", COORDINATION_COLUMN_LOCK),
            ("Release", COORDINATION_RELEASE),
            ("Shield", COORDINATION_SHIELD),
        ],
        COORDINATION_SPECIFIC_ORDER,
    )
    density = _reorder_specific(
        [
            ("DS Density", DENSITY_7K_DOUBLE_STREAMS),
            ("DCS Density", DENSITY_7K_DENSE_CHORDSTREAM),
            ("LCS Density", DENSITY_7K_LIGHT_CHORDSTREAM),
            ("Inverse", DENSITY_7K_INVERSE),
        ],
        DENSITY_SPECIFIC_ORDER,
    )
    wildcard = _reorder_specific(
        [
            ("Jacky WC", WILDCARD_JACK),
            ("Speedy WC", WILDCARD_SPEED),
        ],
        WILDCARD_SPECIFIC_ORDER,
    )

    return SpecificPatterns(
        Stream=[],
        Chordstream=[
            ("Brackets", CHORDSTREAM_7K_BRACKETS),
            # F# 注释：("Chord Rolls", Chordstream_7K.CHORD_ROLL)
            ("Double Stream", CHORDSTREAM_7K_DOUBLE_STREAMS),
            ("Dense Chordstream", CHORDSTREAM_7K_DENSE_CHORDSTREAM),
            ("Light Chordstream", CHORDSTREAM_7K_LIGHT_CHORDSTREAM),
        ],
        Jack=[
            ("Longjacks", JACKS_LONGJACKS),
            ("Chordjacks", JACKS_CHORDJACKS),
            ("Minijacks", JACKS_MINIJACKS),
        ],
        Coordination=coordination,
        Density=density,
        Wildcard=wildcard,
    )


def SPECIFIC_OTHER() -> SpecificPatterns:
    coordination = _reorder_specific(
        [
            ("Column Lock", COORDINATION_COLUMN_LOCK),
            ("Release", COORDINATION_RELEASE),
            ("Shield", COORDINATION_SHIELD),
        ],
        COORDINATION_SPECIFIC_ORDER,
    )
    density = _reorder_specific(
        [
            ("DS Density", DENSITY_Other_DOUBLE_STREAMS),
            ("DCS Density", DENSITY_Other_DENSE_CHORDSTREAM),
            ("LCS Density", DENSITY_Other_LIGHT_CHORDSTREAM),
            ("Inverse", DENSITY_Other_INVERSE),
        ],
        DENSITY_SPECIFIC_ORDER,
    )
    wildcard = _reorder_specific(
        [
            ("Jacky WC", WILDCARD_JACK),
            ("Speedy WC", WILDCARD_SPEED),
        ],
        WILDCARD_SPECIFIC_ORDER,
    )

    return SpecificPatterns(
        Stream=[],
        Chordstream=[
            ("Chord Rolls", CHORDSTREAM_OTHER_CHORD_ROLL),
            ("Double Stream", CHORDSTREAM_OTHER_DOUBLE_STREAMS),
            ("Dense Chordstream", CHORDSTREAM_OTHER_DENSE_CHORDSTREAM),
            ("Light Chordstream", CHORDSTREAM_OTHER_LIGHT_CHORDSTREAM),
        ],
        Jack=[
            ("Longjacks", JACKS_LONGJACKS),
            ("Chordjacks", JACKS_CHORDJACKS),
            ("Minijacks", JACKS_MINIJACKS),
        ],
        Coordination=coordination,
        Density=density,
        Wildcard=wildcard,
    )