# -*- coding: utf-8 -*-
"""
对应 prelude/src/Calculator/Patterns/Summary.fs
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from nonebot import get_plugin_config

from ...config import Config
from .find_patterns import find
from .clustering import Cluster, calculate_clustered_patterns
from .patterns_def import CorePattern
from .primitives import ln_percent, sv_time
from .categorise import categorise_chart
from .chart import NoteType

config = get_plugin_config(Config)


@dataclass
class PatternReport:
    Clusters: List[Cluster]
    Category: str
    LNPercent: float
    HBRowRatio: float
    ModeTag: str
    SVAmount: float

    Duration: float

    @property
    def ImportantClusters(self):
        if len(self.Clusters) == 0:
            return []
        importance = self.Clusters[0].Importance
        out = []
        for c in self.Clusters:
            if c.Importance / importance > config.important_cluster_ratio:
                out.append(c)
            else:
                break
        return out


LN_CORE_PATTERNS = {
    CorePattern.Coordination,
    CorePattern.Density,
    CorePattern.Wildcard,
}


def _hb_row_ratio(chart) -> float:
    rows = chart.Notes if chart and chart.Notes else []
    if len(rows) == 0:
        return 0.0

    hb_rows = 0
    for row in rows:
        data = list(row.Data) if row and row.Data else []
        has_head = any(n == NoteType.HOLDHEAD for n in data)
        has_normal = any(n == NoteType.NORMAL for n in data)
        if has_head and has_normal:
            hb_rows += 1

    return hb_rows / float(len(rows))


def _resolve_mode_tag(ln_ratio: float, hb_ratio: float) -> str:
    if ln_ratio <= config.ln_mode_low_threshold:
        return "RC"
    if ln_ratio >= config.ln_mode_high_threshold:
        return "LN"
    if hb_ratio >= config.hb_row_ratio_threshold:
        return "HB"
    return "Mix"


def from_chart(chart) -> PatternReport:
    ln_ratio = ln_percent(chart)
    hb_ratio = _hb_row_ratio(chart)
    mode_tag = _resolve_mode_tag(ln_ratio, hb_ratio)

    patterns = find(chart)
    if mode_tag == "RC":
        patterns = [p for p in patterns if p.Pattern not in LN_CORE_PATTERNS]

    clusters = [c for c in calculate_clustered_patterns(patterns, mode_tag) if c.BPM > 25 or c.BPM == 0]
    clusters.sort(key=lambda x: x.Amount, reverse=True)

    def can_be_pruned(cluster: Cluster) -> bool:
        for other in clusters:
            if other.Pattern == cluster.Pattern and other.Amount * 0.5 > cluster.Amount and other.BPM > cluster.BPM:
                return True
        return False

    filtered = [c for c in clusters if not can_be_pruned(c)]

    # 每类最多 3 个（包含新增分类），然后按 Importance 排序
    pruned_clusters: List[Cluster] = []
    for pattern in CorePattern:
        pruned_clusters.extend([c for c in filtered if c.Pattern == pattern][:3])
    pruned_clusters.sort(key=lambda x: x.Importance, reverse=True)

    sv_amount = sv_time(chart)

    return PatternReport(
        Clusters=pruned_clusters,
        LNPercent=ln_ratio,
        HBRowRatio=hb_ratio,
        ModeTag=mode_tag,
        SVAmount=sv_amount,
        Category=categorise_chart(chart.Keys, pruned_clusters, sv_amount),
        Duration=(chart.LastNote - chart.FirstNote),
    )