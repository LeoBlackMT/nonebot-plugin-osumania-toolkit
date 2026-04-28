# -*- coding: utf-8 -*-
"""
谱面内部结构：尽量贴近 prelude/src/Chart.fs
这里只实现 Pattern 分析所需字段：
- Keys
- Notes: list[TimeItem[NoteRow]]
- BPM: list[TimeItem[BPM]]
- SV: list[TimeItem[float]] (速度倍率)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Generic, List, TypeVar

from .time_types import Time


class NoteType(IntEnum):
    NOTHING = 0
    NORMAL = 1
    HOLDHEAD = 2
    HOLDBODY = 3
    HOLDTAIL = 4


NoteRow = List[NoteType]


T = TypeVar("T")


@dataclass
class TimeItem(Generic[T]):
    Time: Time
    Data: T


TimeArray = List[TimeItem[T]]


@dataclass
class BPM:
    Meter: int          # beat 数（基本都是 4）
    MsPerBeat: float    # 每拍毫秒


@dataclass
class Chart:
    Keys: int
    Notes: TimeArray[NoteRow]
    BPM: TimeArray[BPM]
    SV: TimeArray[float]

    @property
    def FirstNote(self) -> Time:
        return self.Notes[0].Time

    @property
    def LastNote(self) -> Time:
        return self.Notes[-1].Time