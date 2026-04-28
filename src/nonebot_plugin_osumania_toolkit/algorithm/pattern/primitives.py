# -*- coding: utf-8 -*-
"""
对应 prelude/src/Calculator/Patterns/Primitives.fs
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Tuple

from nonebot import get_plugin_config

from ...config import Config
from .chart import Chart, NoteType

config = get_plugin_config(Config)


class Direction(Enum):
    None_ = "None"
    Left = "Left"
    Right = "Right"
    Outwards = "Outwards"
    Inwards = "Inwards"


@dataclass
class RowInfo:
    Index: int
    Time: float
    MsPerBeat: float
    BeatLength: float
    Notes: int
    Jacks: int
    Direction: Direction
    Roll: bool
    Keys: int
    LeftHandKeys: int
    LNHeads: List[int]
    LNBodies: List[int]
    LNTails: List[int]
    NormalNotes: List[int]
    RawNotes: List[int]


def _keys_on_left_hand(keymode: int) -> int:
    if keymode == 3:
        return 2
    if keymode == 4:
        return 2
    if keymode == 5:
        return 3
    if keymode == 6:
        return 3
    if keymode == 7:
        return 4
    if keymode == 8:
        return 4
    if keymode == 9:
        return 5
    if keymode == 10:
        return 5
    return max(1, keymode // 2)


def _beat_length_at(chart: Chart, time: float) -> float:
    if len(chart.BPM) == 0:
        return 500.0
    current = chart.BPM[0].Data.MsPerBeat
    for item in chart.BPM:
        if item.Time > time:
            break
        current = item.Data.MsPerBeat
    return current


def detect_direction(previous_row: List[int], current_row: List[int]) -> Tuple[Direction, bool]:
    assert len(previous_row) > 0
    assert len(current_row) > 0

    pleftmost = previous_row[0]
    prightmost = previous_row[-1]
    cleftmost = current_row[0]
    crightmost = current_row[-1]

    leftmost_change = cleftmost - pleftmost
    rightmost_change = crightmost - prightmost

    if leftmost_change > 0:
        if rightmost_change > 0:
            direction = Direction.Right
        else:
            direction = Direction.Inwards
    elif leftmost_change < 0:
        if rightmost_change < 0:
            direction = Direction.Left
        else:
            direction = Direction.Outwards
    else:
        if rightmost_change < 0:
            direction = Direction.Inwards
        elif rightmost_change > 0:
            direction = Direction.Outwards
        else:
            direction = Direction.None_

    is_roll = (pleftmost > crightmost) or (prightmost < cleftmost)
    return direction, is_roll


def calculate_primitives(chart: Chart) -> List[RowInfo]:
    first_note = chart.Notes[0].Time
    first_row = chart.Notes[0].Data

    previous_row = [k for k in range(chart.Keys) if first_row[k] in (NoteType.NORMAL, NoteType.HOLDHEAD)]
    if len(previous_row) == 0:
        # F# 会 Logging.Error 然后返回 []
        return []

    previous_time = first_note
    index = 0
    left_hand_keys = _keys_on_left_hand(chart.Keys)

    out: List[RowInfo] = []

    # 从第二行开始
    for item in chart.Notes[1:]:
        t = item.Time
        row = item.Data
        index += 1

        current_row: List[int] = []
        normal_notes: List[int] = []
        ln_heads: List[int] = []
        ln_bodies: List[int] = []
        ln_tails: List[int] = []
        for k in range(chart.Keys):
            n = row[k]
            if n in (NoteType.NORMAL, NoteType.HOLDHEAD):
                current_row.append(k)
            if n == NoteType.NORMAL:
                normal_notes.append(k)
            if n == NoteType.HOLDHEAD:
                ln_heads.append(k)
            elif n == NoteType.HOLDBODY:
                ln_bodies.append(k)
            elif n == NoteType.HOLDTAIL:
                ln_tails.append(k)

        if len(current_row) == 0 and len(ln_heads) == 0 and len(ln_bodies) == 0 and len(ln_tails) == 0:
            continue

        if len(current_row) > 0:
            direction, is_roll = detect_direction(previous_row, current_row)
            # Jacks：当前行与上一有效按键行的列交集大小。
            jacks = len(set(current_row).intersection(previous_row))
        else:
            direction, is_roll = Direction.None_, False
            jacks = 0

        out.append(
            RowInfo(
                Index=index,
                Time=(t - first_note),
                MsPerBeat=(t - previous_time) * 4.0,   # *4 => 1/4 间隔
                BeatLength=_beat_length_at(chart, t),
                Notes=len(current_row),
                Jacks=jacks,
                Direction=direction,
                Roll=is_roll,
                Keys=chart.Keys,
                LeftHandKeys=left_hand_keys,
                LNHeads=ln_heads,
                LNBodies=ln_bodies,
                LNTails=ln_tails,
                NormalNotes=normal_notes,
                RawNotes=current_row,
            )
        )

        if len(current_row) > 0:
            previous_row = current_row
        previous_time = t

    return out


def ln_percent(chart: Chart) -> float:
    notes = 0
    lnotes = 0
    for item in chart.Notes:
        nr = item.Data
        for n in nr:
            if n == NoteType.NORMAL:
                notes += 1
            elif n == NoteType.HOLDHEAD:
                notes += 1
                lnotes += 1
    return (float(lnotes) / float(notes)) if notes > 0 else 0.0


def sv_time(chart: Chart) -> float:
    # 对应 Metrics.sv_time：统计有效 SV 变化时间段
    if len(chart.SV) == 0:
        return 0.0
    total = 0.0
    time = chart.FirstNote
    vel = 1.0
    for sv in chart.SV:
        if (not (vel == vel)) or abs(vel - 1.0) > config.sv_speed_eps:
            total += (sv.Time - time)
        vel = sv.Data
        time = sv.Time
    if (not (vel == vel)) or abs(vel - 1.0) > config.sv_speed_eps:
        total += (chart.LastNote - time)

    # 极端 BPM 变化：即便 SV 时间较短也视作 SV
    extreme = False
    bpms = chart.BPM
    if len(bpms) >= 1:
        prev_mspb = None
        for item in bpms:
            mspb = float(item.Data.MsPerBeat)
            if mspb <= 0:
                extreme = True
                break
            bpm = 60000.0 / mspb
            if bpm <= config.sv_extreme_bpm_min or bpm >= config.sv_extreme_bpm_max:
                extreme = True
                break
            if prev_mspb is not None:
                ratio = max(prev_mspb / mspb, mspb / prev_mspb)
                if ratio >= config.sv_extreme_bpm_ratio:
                    extreme = True
                    break
            prev_mspb = mspb

    if extreme:
        return max(total, config.sv_amount_threshold + 1.0)
    return total