import bisect
from collections import Counter

import numpy as np
from nonebot import get_plugin_config

from ...config import Config
from .types import Signal

config = get_plugin_config(Config)


def detect_gap_ghost_context_v2(
    replay_events: list[tuple[int, float]],
    note_times_by_col: dict[int, list[float]],
    matched_pairs: list[tuple[int, float, float]],
) -> Signal | None:
    """在长空段上下文中对空敲进行时序评分。"""

    if not replay_events:
        return None

    all_notes = [t for times in note_times_by_col.values() for t in times]
    if len(all_notes) < 40:
        return None

    min_note = min(all_notes)
    max_note = max(all_notes)
    buffer = 5000
    considered = [(col, t) for col, t in replay_events if min_note - buffer <= t <= max_note + buffer]
    if len(considered) < 120:
        return None

    matched_press_set = {(col, press) for col, _, press in matched_pairs}
    unmatched = [(col, t) for col, t in considered if (col, t) not in matched_press_set]

    sorted_notes = sorted(all_notes)
    long_gaps: list[tuple[float, float]] = []
    for i in range(1, len(sorted_notes)):
        start = sorted_notes[i - 1]
        end = sorted_notes[i]
        if end - start >= config.delta_gap_v2_min_gap_ms:
            long_gaps.append((start + config.delta_gap_v2_inner_margin_ms, end - config.delta_gap_v2_inner_margin_ms))
    if not long_gaps:
        return None

    starts = [g[0] for g in long_gaps]
    gap_events: list[tuple[int, float]] = []
    gap_relative_positions: list[float] = []
    for col, t in unmatched:
        idx = bisect.bisect_right(starts, t) - 1
        if idx >= 0:
            gs, ge = long_gaps[idx]
            if gs <= t <= ge:
                gap_events.append((col, t))
                width = max(1.0, ge - gs)
                gap_relative_positions.append((t - gs) / width)

    if len(gap_events) < 8:
        return None

    total_considered = len(considered)
    unmatched_ratio = len(unmatched) / total_considered
    gap_ratio = len(gap_events) / total_considered

    gap_events.sort(key=lambda x: x[1])
    times = np.array([t for _, t in gap_events], dtype=float)
    if len(times) >= 3:
        ioi = np.diff(times)
        ioi = ioi[(ioi > 30) & (ioi < 600)]
    else:
        ioi = np.array([], dtype=float)

    regularity = 0.0
    if len(ioi) >= 6:
        q = config.delta_gap_v2_ioi_quant_ms
        quantized = np.round(ioi / q) * q
        cv = float(np.std(quantized) / np.mean(quantized)) if np.mean(quantized) > 1e-9 else 1.0
        regularity = max(0.0, 1.0 - min(1.0, cv / 0.8))

    col_counts = Counter(col for col, _ in gap_events)
    probs = np.array([v / len(gap_events) for v in col_counts.values()], dtype=float)
    entropy = float(-np.sum(probs * np.log2(probs))) if len(probs) > 0 else 0.0
    max_entropy = np.log2(max(2, len(note_times_by_col)))
    entropy_penalty = max(0.0, 1.0 - (entropy / max_entropy))

    score = (
        config.delta_gap_v2_weight_unmatched * min(1.0, unmatched_ratio / 0.7)
        + config.delta_gap_v2_weight_gap * min(1.0, gap_ratio / 0.4)
        + config.delta_gap_v2_weight_regular * regularity
        + config.delta_gap_v2_weight_entropy * entropy_penalty
    )

    motive_uniformity = 0.0
    if len(gap_relative_positions) >= 10:
        bins = np.histogram(gap_relative_positions, bins=5, range=(0.0, 1.0))[0].astype(float)
        probs_u = bins / np.sum(bins) if np.sum(bins) > 0 else np.zeros_like(bins)
        uni = np.ones_like(probs_u) / len(probs_u)
        motive_uniformity = 1.0 - 0.5 * float(np.sum(np.abs(probs_u - uni)))
    score += config.delta_gap_v2_weight_uniform * motive_uniformity

    if score >= config.delta_gap_v2_hard_score:
        return Signal(
            rule_id="delta_gap_v2_hard",
            cheat=False,
            sus=True,
            risk=2,
            reason=(
                "长空段空敲时序画像异常(v2)"
                f"(score={score:.2f}, 未匹配率={unmatched_ratio*100:.1f}%, "
                f"长空段占比={gap_ratio*100:.1f}%, 规律度={regularity:.2f}, 位置均匀度={motive_uniformity:.2f})"
            ),
        )
    if score >= config.delta_gap_v2_soft_score:
        return Signal(
            rule_id="delta_gap_v2_soft",
            cheat=False,
            sus=True,
            risk=1,
            reason=(
                "长空段空敲时序画像可疑(v2)"
                f"(score={score:.2f}, 未匹配率={unmatched_ratio*100:.1f}%, "
                f"长空段占比={gap_ratio*100:.1f}%, 位置均匀度={motive_uniformity:.2f})"
            ),
        )
    return None
