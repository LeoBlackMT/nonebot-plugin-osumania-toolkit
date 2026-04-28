from collections import Counter

import numpy as np
from nonebot import get_plugin_config

from ...config import Config
from .types import Signal

config = get_plugin_config(Config)


def detect_chord_sync_template(
    chord_groups: list[list[tuple[int, float]]],
    note_to_press: dict[tuple[int, float], float],
) -> Signal | None:
    """检测多押组是否存在同步模板复用。"""

    template_counter: Counter[tuple[int, ...]] = Counter()
    valid_groups = 0
    near_zero_groups = 0

    for group in chord_groups:
        group_press = []
        for col, note in sorted(group, key=lambda x: x[0]):
            if (col, note) not in note_to_press:
                continue
            group_press.append((col, float(note_to_press[(col, note)] - note)))
        if len(group_press) < 2:
            continue

        valid_groups += 1
        offsets = [offset for _, offset in group_press]
        if max(offsets) - min(offsets) <= config.delta_chord_template_span_ms:
            near_zero_groups += 1

        base = offsets[0]
        normalized = [int(round((off - base) / config.delta_chord_template_quant_ms)) for off in offsets]
        template_counter[tuple(normalized)] += 1

    if valid_groups < config.delta_chord_template_min_groups:
        return None

    top_count = template_counter.most_common(1)[0][1] if template_counter else 0
    template_ratio = top_count / valid_groups if valid_groups > 0 else 0.0
    near_zero_ratio = near_zero_groups / valid_groups if valid_groups > 0 else 0.0

    if (
        template_ratio >= config.delta_chord_template_hard_ratio
        and near_zero_ratio >= config.delta_chord_template_hard_zero_ratio
    ):
        return Signal(
            rule_id="delta_chord_template_hard",
            cheat=True,
            sus=True,
            risk=3,
            reason=(
                f"多押同步模板高度复用(模板占比={template_ratio*100:.1f}%, "
                f"组内近同偏移占比={near_zero_ratio*100:.1f}%)"
            ),
        )

    if (
        template_ratio >= config.delta_chord_template_soft_ratio
        and near_zero_ratio >= config.delta_chord_template_soft_zero_ratio
    ):
        return Signal(
            rule_id="delta_chord_template_soft",
            cheat=False,
            sus=True,
            risk=2,
            reason=(
                f"多押同步模板复用偏高(模板占比={template_ratio*100:.1f}%, "
                f"组内近同偏移占比={near_zero_ratio*100:.1f}%)"
            ),
        )
    return None


def detect_chord_near_zero_cluster(chord_spans_arr: np.ndarray) -> Signal | None:
    """检测多押组内差值是否过度聚集在零附近极小区间。"""

    spans = np.array(chord_spans_arr, dtype=float)
    if len(spans) < config.delta_chord_near_zero_min_count:
        return None

    tiny_ratio = float(np.mean(spans <= config.delta_chord_near_zero_ms))
    wide_ratio = float(np.mean(spans >= config.delta_chord_wide_ms))

    if tiny_ratio >= config.delta_chord_near_zero_hard_ratio and wide_ratio <= config.delta_chord_wide_hard_ratio:
        return Signal(
            rule_id="delta_chord_near_zero_hard",
            cheat=True,
            sus=True,
            risk=3,
            reason=(
                f"多押组内差值极端近同步(<= {config.delta_chord_near_zero_ms:.2f}ms 占比={tiny_ratio*100:.1f}%, "
                f"宽差值占比={wide_ratio*100:.1f}%)"
            ),
        )
    if tiny_ratio >= config.delta_chord_near_zero_soft_ratio and wide_ratio <= config.delta_chord_wide_soft_ratio:
        return Signal(
            rule_id="delta_chord_near_zero_soft",
            cheat=False,
            sus=True,
            risk=2,
            reason=f"多押组内差值过度集中(<= {config.delta_chord_near_zero_ms:.2f}ms 占比={tiny_ratio*100:.1f}%)",
        )
    return None
