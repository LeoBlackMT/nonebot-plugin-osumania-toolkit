from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class LaneEvent:
    col: int
    result: int
    offset: float
    time: float = 0.0
    part: str = ""
