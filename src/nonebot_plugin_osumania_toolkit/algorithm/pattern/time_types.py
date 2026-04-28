# -*- coding: utf-8 -*-
"""
时间/倍率等基础类型（对应 F# Prelude/Types + 计算器里用到的单位）
为了方便移植，这里用 float 表示 ms，rate 用 float 表示（例如 DT=1.5）
"""

from __future__ import annotations


Time = float          # 毫秒
Rate = float          # 速度倍率（1.0 为原速）
GameplayTime = float  # 这里同样用 ms（F# 里是带单位的 ms/rate）


def is_finite(x: float) -> bool:
    return x == x and x not in (float("inf"), float("-inf"))