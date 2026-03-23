# -*- coding: utf-8 -*-
"""
对应 prelude/src/Calculator/Patterns/Categorise.fs
"""

from __future__ import annotations

from typing import List

from nonebot import get_plugin_config

from ...config import Config
from .clustering import Cluster

config = get_plugin_config(Config)


def is_hybrid_chart(primary: Cluster, secondary: Cluster | None) -> bool:
    """
    Hybrid extension point.
    Keep this function as the single entry to hybrid categorisation rules.
    """
    return False


def categorise_chart(keys: int, ordered_clusters: List[Cluster], sv_amount: float) -> str:
    if len(ordered_clusters) == 0:
        return "SV" if sv_amount >= config.SV_AMOUNT_THRESHOLD else "Uncategorised"

    # important_clusters：Importance / first > 0.5
    first_imp = ordered_clusters[0].Importance
    important = []
    for c in ordered_clusters:
        if c.Importance / first_imp > config.IMPORTANT_CLUSTER_RATIO:
            important.append(c)
        else:
            break

    cluster_1 = important[0]
    cluster_2 = important[1] if len(important) > 1 else None

    is_hybrid = is_hybrid_chart(cluster_1, cluster_2)

    is_tech = cluster_1.Mixed
    is_sv = sv_amount >= config.SV_AMOUNT_THRESHOLD

    if len(cluster_1.SpecificTypes) > 0 and cluster_1.SpecificTypes[0][1] > 0:
        name = cluster_1.SpecificTypes[0][0]
    elif len(cluster_1.SpecificTypes) >= 2 and cluster_1.SpecificTypes[0][0] == "Jumpstream" and cluster_1.SpecificTypes[1][0] == "Handstream":
        a1 = cluster_1.SpecificTypes[0][1]
        a2 = cluster_1.SpecificTypes[1][1]
        name = "Jumpstream/Handstream" if (a2 / a1) > config.CATEGORY_JS_HS_SECONDARY_RATIO else cluster_1.Pattern.value
    else:
        name = cluster_1.Pattern.value

    return f"{name}{' Hybrid' if is_hybrid else ''}{' Tech' if is_tech else ''}{' + SV' if is_sv else ''}"