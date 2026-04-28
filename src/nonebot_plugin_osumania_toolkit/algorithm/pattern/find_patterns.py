# -*- coding: utf-8 -*-
"""
对应 prelude/src/Calculator/Patterns/FindPatterns.fs
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from nonebot import get_plugin_config

from ...config import Config
from .chart import Chart
from .primitives import RowInfo, calculate_primitives
from .patterns_def import (
    CorePattern,
    SpecificPatterns,
    CORE_STREAM,
    CORE_CHORDSTREAM,
    CORE_JACKS,
    CORE_COORDINATION,
    CORE_DENSITY,
    CORE_WILDCARD,
    SPECIFIC_4K,
    SPECIFIC_7K,
    SPECIFIC_OTHER,
)


config = get_plugin_config(Config)

@dataclass
class FoundPattern:
    Pattern: CorePattern
    SpecificType: Optional[str]
    Mixed: bool
    Start: float
    End: float
    MsPerBeat: float

def _pick_specific_first(specific_list, remaining: List[RowInfo]):
    # 旧行为：找到第一个返回非 0 的识别器。
    for name, p in specific_list:
        n = p(remaining)
        if n != 0:
            return n, name
    return None


def _pick_specific_all(specific_list, remaining: List[RowInfo]) -> List[tuple[int, str]]:
    matched: List[tuple[int, str]] = []
    for name, p in specific_list:
        n = p(remaining)
        if n != 0:
            matched.append((n, name))
    return matched


def _resolved_mspb(pattern: CorePattern, specific_type: Optional[str], mean_mspb: float) -> float:
    if pattern == CorePattern.Density and specific_type == "Inverse":
        return 0.0
    return mean_mspb


def _append_found_pattern(
    results: List[FoundPattern],
    pattern: CorePattern,
    specific_type: Optional[str],
    n2: int,
    remaining: List[RowInfo],
    last_note: float,
) -> None:
    d = remaining[:n2]
    mean_mspb = sum(x.MsPerBeat for x in d) / len(d)
    mixed = not all(abs(x.MsPerBeat - mean_mspb) < config.pattern_stability_threshold for x in d)

    start = remaining[0].Time
    if pattern == CorePattern.Jacks:
        end_candidate = remaining[n2].Time if n2 < len(remaining) else last_note
        end = max(remaining[0].Time + remaining[0].MsPerBeat * 0.5, end_candidate)
    else:
        end = remaining[n2].Time if n2 < len(remaining) else last_note

    results.append(
        FoundPattern(
            Pattern=pattern,
            SpecificType=specific_type,
            Mixed=mixed,
            Start=start,
            End=end,
            MsPerBeat=_resolved_mspb(pattern, specific_type, mean_mspb),
        )
    )

def _append_core_matches(
    results: List[FoundPattern],
    pattern: CorePattern,
    core_n: int,
    specific_list,
    remaining: List[RowInfo],
    last_note: float,
) -> None:
    if core_n == 0:
        return

    if config.enable_multi_label_same_window:
        matched = _pick_specific_all(specific_list, remaining)
        if len(matched) == 0:
            _append_found_pattern(results, pattern, None, core_n, remaining, last_note)
            return
        for m, specific_type in matched:
            _append_found_pattern(results, pattern, specific_type, max(core_n, m), remaining, last_note)
        return

    picked = _pick_specific_first(specific_list, remaining)
    if picked is None:
        _append_found_pattern(results, pattern, None, core_n, remaining, last_note)
        return
    m, specific_type = picked
    _append_found_pattern(results, pattern, specific_type, max(core_n, m), remaining, last_note)


def matches(specific_patterns: SpecificPatterns, last_note: float, primitives: List[RowInfo]) -> List[FoundPattern]:
    remaining = primitives[:]
    results: List[FoundPattern] = []

    while len(remaining) > 0:
        # Stream
        _append_core_matches(
            results,
            CorePattern.Stream,
            CORE_STREAM(remaining),
            specific_patterns.Stream,
            remaining,
            last_note,
        )

        # Chordstream
        _append_core_matches(
            results,
            CorePattern.Chordstream,
            CORE_CHORDSTREAM(remaining),
            specific_patterns.Chordstream,
            remaining,
            last_note,
        )

        # Jacks
        _append_core_matches(
            results,
            CorePattern.Jacks,
            CORE_JACKS(remaining),
            specific_patterns.Jack,
            remaining,
            last_note,
        )

        # Coordination
        _append_core_matches(
            results,
            CorePattern.Coordination,
            CORE_COORDINATION(remaining),
            specific_patterns.Coordination,
            remaining,
            last_note,
        )

        # Density
        _append_core_matches(
            results,
            CorePattern.Density,
            CORE_DENSITY(remaining),
            specific_patterns.Density,
            remaining,
            last_note,
        )

        # Wildcard
        _append_core_matches(
            results,
            CorePattern.Wildcard,
            CORE_WILDCARD(remaining),
            specific_patterns.Wildcard,
            remaining,
            last_note,
        )

        remaining = remaining[1:]

    return results


def find(chart: Chart) -> List[FoundPattern]:
    primitives = calculate_primitives(chart)

    if chart.Keys == 4:
        keymode_patterns = SPECIFIC_4K()
    elif chart.Keys == 7:
        keymode_patterns = SPECIFIC_7K()
    else:
        keymode_patterns = SPECIFIC_OTHER()

    return matches(keymode_patterns, chart.LastNote - chart.FirstNote, primitives)