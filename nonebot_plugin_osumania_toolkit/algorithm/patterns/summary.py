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

config = get_plugin_config(Config)


@dataclass
class PatternReport:
    Clusters: List[Cluster]
    Category: str
    LNPercent: float
    SVAmount: float

    Duration: float

    @property
    def ImportantClusters(self):
        if len(self.Clusters) == 0:
            return []
        importance = self.Clusters[0].Importance
        out = []
        for c in self.Clusters:
            if c.Importance / importance > config.IMPORTANT_CLUSTER_RATIO:
                out.append(c)
            else:
                break
        return out


def from_chart(chart) -> PatternReport:
    patterns = find(chart)

    clusters = [c for c in calculate_clustered_patterns(patterns) if c.BPM > 25 or c.BPM == 0]
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
        LNPercent=ln_percent(chart),
        SVAmount=sv_amount,
        Category=categorise_chart(chart.Keys, pruned_clusters, sv_amount),
        Duration=(chart.LastNote - chart.FirstNote),
    )