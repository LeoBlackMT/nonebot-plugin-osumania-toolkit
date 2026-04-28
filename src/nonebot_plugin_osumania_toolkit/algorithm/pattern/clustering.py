# -*- coding: utf-8 -*-
"""
对应 prelude/src/Calculator/Patterns/Clustering.fs
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from nonebot import get_plugin_config

from ...config import Config
from .find_patterns import FoundPattern
from .patterns_def import CorePattern, resolve_rating_multiplier

config = get_plugin_config(Config)


@dataclass
class Cluster:
    Pattern: CorePattern
    SpecificTypes: List[Tuple[str, float]]
    RatingMultiplier: float
    BPM: int
    Mixed: bool
    Amount: float  # ms

    @property
    def Importance(self) -> float:
        return self.Amount * self.RatingMultiplier * float(self.BPM)

    def Format(self, rate: float) -> str:
        if len(self.SpecificTypes) > 0 and self.SpecificTypes[0][1] >= config.cluster_specific_name_min_ratio:
            name = self.SpecificTypes[0][0]
        else:
            name = self.Pattern.value
        if self.Mixed:
            return f"~{float(self.BPM) * rate:.0f}BPM Mixed {name}"
        return f"{float(self.BPM) * rate:.0f}BPM {name}"


@dataclass
class _ClusterBuilder:
    SumMs: float
    OriginalMsPerBeat: float
    Count: int
    BPM: Optional[int]

    def Add(self, value: float) -> None:
        self.Count += 1
        self.SumMs += value

    def Calculate(self) -> None:
        average = self.SumMs / float(self.Count)
        if average <= 0.0:
            bpm = 0
        else:
            bpm = int(round(60000.0 / average))
        self.BPM = bpm

    @property
    def Value(self) -> int:
        assert self.BPM is not None
        return self.BPM


def _pattern_amount(sorted_starts_ends: List[Tuple[float, float]]) -> float:
    total_time = 0.0
    current_start, current_end = sorted_starts_ends[0]

    for start, end in sorted_starts_ends:
        if current_end < end:
            total_time += (current_end - current_start)
            current_start = start
            current_end = end
        else:
            current_end = max(current_end, end)

    total_time += (current_end - current_start)
    return total_time


def assign_clusters(patterns: List[FoundPattern]) -> List[Tuple[FoundPattern, _ClusterBuilder]]:
    bpms_non_mixed: List[_ClusterBuilder] = []
    bpms_mixed: Dict[CorePattern, _ClusterBuilder] = {}

    def add_to_cluster(ms_per_beat: float) -> _ClusterBuilder:
        for c in bpms_non_mixed:
            if abs(c.OriginalMsPerBeat - ms_per_beat) < config.bpm_cluster_threshold:
                c.Add(ms_per_beat)
                return c
        newc = _ClusterBuilder(SumMs=ms_per_beat, OriginalMsPerBeat=ms_per_beat, Count=1, BPM=None)
        bpms_non_mixed.append(newc)
        return newc

    def add_to_mixed_cluster(pattern: CorePattern, value: float) -> _ClusterBuilder:
        if pattern in bpms_mixed:
            c = bpms_mixed[pattern]
            c.Add(value)
            return c
        newc = _ClusterBuilder(SumMs=value, OriginalMsPerBeat=value, Count=1, BPM=None)
        bpms_mixed[pattern] = newc
        return newc

    patterns_with_clusters: List[Tuple[FoundPattern, _ClusterBuilder]] = []
    for p in patterns:
        if p.Mixed:
            c = add_to_mixed_cluster(p.Pattern, p.MsPerBeat)
        else:
            c = add_to_cluster(p.MsPerBeat)
        patterns_with_clusters.append((p, c))

    for c in bpms_non_mixed:
        c.Calculate()
    for c in bpms_mixed.values():
        c.Calculate()

    return patterns_with_clusters


def specific_clusters(
    patterns_with_clusters: List[Tuple[FoundPattern, _ClusterBuilder]],
    mode_tag: str = "Mix",
) -> List[Cluster]:
    groups: Dict[Tuple[CorePattern, bool, int], List[Tuple[FoundPattern, _ClusterBuilder]]] = {}
    for p, c in patterns_with_clusters:
        key = (p.Pattern, p.Mixed, c.Value)
        groups.setdefault(key, []).append((p, c))

    out: List[Cluster] = []
    for (pattern, mixed, bpm), data in groups.items():
        starts_ends = sorted([(m.Start, m.End) for (m, _) in data], key=lambda x: x[0])

        data_count = float(len(data))
        # 统计具体类型占比
        counter: Dict[str, int] = {}
        for m, _ in data:
            if m.SpecificType is not None:
                counter[m.SpecificType] = counter.get(m.SpecificType, 0) + 1
        specific_types = sorted([(k, v / data_count) for k, v in counter.items()], key=lambda x: x[1], reverse=True)
        dominant_specific = specific_types[0][0] if len(specific_types) > 0 else None

        out.append(
            Cluster(
                Pattern=pattern,
                SpecificTypes=specific_types,
                RatingMultiplier=resolve_rating_multiplier(pattern, dominant_specific, mode_tag),
                BPM=bpm,
                Mixed=mixed,
                Amount=_pattern_amount(starts_ends) if len(starts_ends) > 0 else 0.0,
            )
        )

    has_dw = any(c.Pattern in {CorePattern.Density, CorePattern.Wildcard} for c in out)
    if has_dw and config.release_with_dw_multiplier != 1.0:
        for c in out:
            if any(name == "Release" and ratio > 0.0 for name, ratio in c.SpecificTypes):
                c.RatingMultiplier *= config.release_with_dw_multiplier

    return out


def calculate_clustered_patterns(patterns: List[FoundPattern], mode_tag: str = "Mix") -> List[Cluster]:
    pwc = assign_clusters(patterns)
    return specific_clusters(pwc, mode_tag)