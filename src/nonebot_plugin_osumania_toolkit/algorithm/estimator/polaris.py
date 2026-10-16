"""Polaris 表修正 —— ``js/estimator/polarisCorrection.js`` 与
``js/estimator/polarisEstimator.js`` 的逐段直译。

定位：Sunny 的 star→段位表映射存在系统性偏差，Polaris 以 Sunny 为基线，对
"star→level 连续映射"叠加行为数据拟合的平滑修正后输出标签：

    level = star_to_level(表, star)
                + compute_polaris_correction(side, level, rate, ln_ratio)

本模块只移植 **校准半边**：目标平台没有 Polaris 的算法选择面（``/mapview`` 恒走
Mixed），而 Mixed 消费的正是这里的 ``calibrate_table_halves``——它产出表映射两半的
校准结果，供 Mixed 取用 LN 半标签、并在 7K 上整条接管 RC 半。独立的
``runPolarisEstimatorFromText`` 入口没有消费者，故不移植。

曲线集（与 JS ``has_polaris_curve`` 同一张表）：**7K 专用**——RC / LN 两半各一套；
其余键数（含 4K）一律无曲线。4K 曾有 LN 半曲线，实机测试后随 4K 侧全部回退（曲线集已删，
其拟合系数与验证数字保留在 git 历史中）。

修正模型：``corr(side, level, rate, ln_ratio)``
    ``= B(level) + R(level)·f(rate) + H(ln_ratio)``
    - ``B``：速率 1.0x 下的层级基线（表映射 star→level 的系统偏差）
    - ``R``：DT 增量曲线（``f(rate) = clamp((rate − 1) / 0.5, 0, 1)``）
    - ``H``：LN 侧的 lnRatio 项（全 LN / 反手释放群的额外低估）
    - rate < 1.0 不修正（HT 侧两种统计口径方向不一致、幅度小，见 JS 侧文档）

系数来源：Mania Tracker 行为数据集（2026-10 快照），经联合（backfitting）拟合 +
按谱面分组 CV 验证；曲线结点间距 0.5 level，连续线性插值、端外截断。调整系数时
同步跑 JS 侧拟合脚本与 CV——**禁止改成逐图/逐样本特判**。

本仓库不提供区间表的 extended 变体：与 ``sunny.est_diff`` 同一范围决策（目标平台
的调用面从不启用 ``extendedEstimationRange``），故校准只读 default 表。
"""

from __future__ import annotations

import re
import math
from typing import Any
from bisect import bisect_right

from ...data.intervals import sr_intervals_data

POLARIS_LEVEL_KNOTS = (
    -0.75,
    -0.25,
    0.25,
    0.75,
    1.25,
    1.75,
    2.25,
    2.75,
    3.25,
    3.75,
    4.25,
    4.75,
    5.25,
    5.75,
    6.25,
    6.75,
    7.25,
    7.75,
    8.25,
    8.75,
    9.25,
    9.75,
    10.25,
    10.75,
    11.25,
    11.75,
    12.25,
    12.75,
    13.25,
)

_B_RC_FIT = (
    -0.376,
    -0.376,
    -0.228,
    0.003,
    0.116,
    0.164,
    0.252,
    0.397,
    0.486,
    0.36,
    0.143,
    0.042,
    0.11,
    0.209,
    0.229,
    0.223,
    0.238,
    0.212,
    0.09,
    -0.033,
    -0.05,
    0.012,
    0.041,
    0.039,
    0.032,
    0.0,
    -0.014,
    -0.036,
    -0.087,
)

_R_RC_FIT = (
    0.022,
    0.022,
    0.0,
    0.0,
    0.077,
    0.0,
    0.0,
    0.0,
    0.123,
    0.441,
    0.567,
    0.492,
    0.678,
    0.945,
    0.914,
    0.833,
    0.926,
    1.064,
    1.133,
    1.166,
    1.098,
    0.957,
    0.833,
    0.729,
    0.633,
    0.511,
    0.42,
    0.324,
    0.187,
)

_B_LN_FIT = (
    -0.054,
    -0.054,
    -0.054,
    -0.054,
    -0.068,
    -0.066,
    -0.051,
    -0.023,
    0.057,
    0.044,
    -0.017,
    0.053,
    0.13,
    0.174,
    0.118,
    -0.113,
    -0.251,
    -0.228,
    -0.225,
    -0.296,
    -0.312,
    -0.182,
    -0.043,
    0.01,
    -0.007,
    -0.084,
    -0.172,
    -0.191,
    -0.165,
)

_R_LN_FIT = (
    0.144,
    0.144,
    0.144,
    0.144,
    0.144,
    0.144,
    0.144,
    0.144,
    0.144,
    0.144,
    0.144,
    0.144,
    0.144,
    0.144,
    0.144,
    0.144,
    0.144,
    0.144,
    0.18,
    0.253,
    0.289,
    0.289,
    0.303,
    0.29,
    0.277,
    0.236,
    0.155,
    0.241,
    0.381,
)

# LN 侧 lnRatio 项：(lnRatio, 修正量)，首末结点外截断。
# 7K 版在 lnRatio < 0.375 的 LN 半边修正趋近于 0。
_H_LN = (
    (0.4375, 0.06),
    (0.575, 0.264),
    (0.725, 0.306),
    (0.85, 0.136),
    (0.935, 0.429),
    (0.99, 1.001),
)

_TIER_OFFSETS = {
    "low": -0.4,
    "mid/low": -0.2,
    "mid": 0.0,
    "mid/high": 0.2,
    "high": 0.4,
}

_INT_DIGITS = re.compile(r"^[0-9]+$")

# keyCount → {侧: 表}。与 JS DAN_INDEX 的键集对齐到本仓库支持的 4/6/7；
# 10K 无区间表（同 sunny.est_diff 的范围决策），键不存在 ⇒
# calibrate_table_halves 返回 None。
_KEY_TABLES: dict[int, dict[str, list[tuple[float, float, str]]]] = {
    4: {
        "RC": sr_intervals_data.RC_intervals_4K,
        "LN": sr_intervals_data.LN_intervals_4K,
    },
    6: {
        "RC": sr_intervals_data.RC_intervals_6K,
        "LN": sr_intervals_data.LN_intervals_6K,
    },
    7: {
        "RC": sr_intervals_data.RC_intervals_7K,
        "LN": sr_intervals_data.LN_intervals_7K,
    },
}

# ── 单调性不变量（Monotonicity Invariant）──────────────────────────────────
# Polaris 输出的是"表映射 level + 修正量"，所以两条单调性是对**复合曲线**的要求：
#
#   g(l) = l + B(l) + R(l)·f        f = clamp((rate − 1) / 0.5, 0, 1) ∈ [0, 1]
#
#   1) ∂level/∂star > 0：g 在 l 上严格递增。star→level 本身非降，修正量不得把它压回去。
#   2) ∂level/∂rate >= 0：g 对 f 单调，且 f 对 rate 单调 ⇒ 只需 R(l) >= 0。
#
# 两条都能在模块加载时被**构造性地**保证，而不是靠事后检查：
#   - 每条曲线都是结点间的线性插值 ⇒ 逐段线性，只要相邻结点增量 Δg > 0，全曲线就递增；
#   - Δg 对 f 是线性的 ⇒ 只需端点 f = 0 与 f = 1 成立，中间所有 f 自动成立；
#   - 因此把 B 按最不利的那个端点向上抬、把负的 R 钳到 0，即可一次修好、无需迭代。
#
# 结点外（l 超出首末结点）插值为常数，g 的斜率在那里恒为 1，天然递增——边界外推安全。
#
# 运行时修复只会在**拟合出的系数本身逆序**时改变数值。原始系数是否需要修复另行导出
# （POLARIS_MONOTONICITY["rawViolations"]）：它非空就说明样条在某处逆序，应当回到拟合
# 脚本处理，而不是依赖运行时兜住。
POLARIS_MIN_LEVEL_STEP = 0.05


def _repair_polaris_curve(
    side: str, fit_b: tuple[float, ...], fit_r: tuple[float, ...]
) -> dict[str, Any]:
    violations: list[dict[str, Any]] = []
    r_values: list[float] = []
    for index, value in enumerate(fit_r):
        if value >= 0:
            r_values.append(value)
        else:
            violations.append(
                {
                    "side": side,
                    "kind": "rate",
                    "level": POLARIS_LEVEL_KNOTS[index],
                    "value": value,
                }
            )
            r_values.append(0.0)

    b_values = list(fit_b)
    for index in range(1, len(POLARIS_LEVEL_KNOTS)):
        span = POLARIS_LEVEL_KNOTS[index] - POLARIS_LEVEL_KNOTS[index - 1]
        # Δg 在 f = 1 时最小（ΔR < 0），否则在 f = 0 时最小
        required = (
            POLARIS_MIN_LEVEL_STEP
            - span
            - min(0.0, r_values[index] - r_values[index - 1])
        )
        actual = b_values[index] - b_values[index - 1]
        if actual < required:
            violations.append(
                {
                    "side": side,
                    "kind": "level",
                    "level": POLARIS_LEVEL_KNOTS[index],
                    "step": span + actual,
                }
            )
            b_values[index] = b_values[index - 1] + required

    return {"B": tuple(b_values), "R": tuple(r_values), "violations": violations}


_REPAIRED = {
    "7K:RC": _repair_polaris_curve("RC", _B_RC_FIT, _R_RC_FIT),
    "7K:LN": _repair_polaris_curve("LN", _B_LN_FIT, _R_LN_FIT),
}

# 本模块加载时对**原始拟合系数**的单调性诊断。violations 为空即系数本身合规；
# 非空表示拟合出的样条逆序、运行时已把它抬正——应当回到拟合脚本而不是依赖兜底。
POLARIS_MONOTONICITY = {
    "minLevelStep": POLARIS_MIN_LEVEL_STEP,
    "rawViolations": [
        {"curve": name, **violation}
        for name, curves in _REPAIRED.items()
        for violation in curves["violations"]
    ],
    "repaired": any(curves["violations"] for curves in _REPAIRED.values()),
}


def verify_polaris_monotonicity() -> list[dict[str, Any]]:
    """校验**实际生效**的全部曲线满足单调性不变量。

    恒应返回空列表（用于测试与自检）；非空即说明不变量被破坏，属需要修复的缺陷。
    """
    out: list[dict[str, Any]] = []
    tolerance = 1e-9
    for name, curves in _REPAIRED.items():
        b_values, r_values = curves["B"], curves["R"]
        for index, value in enumerate(r_values):
            if value < 0:
                out.append(
                    {
                        "curve": name,
                        "kind": "rate",
                        "level": POLARIS_LEVEL_KNOTS[index],
                        "value": value,
                    }
                )
        for f in (0.0, 1.0):
            for index in range(1, len(POLARIS_LEVEL_KNOTS)):
                step = (
                    (POLARIS_LEVEL_KNOTS[index] - POLARIS_LEVEL_KNOTS[index - 1])
                    + (b_values[index] - b_values[index - 1])
                    + f * (r_values[index] - r_values[index - 1])
                )
                if step < POLARIS_MIN_LEVEL_STEP - tolerance:
                    out.append(
                        {
                            "curve": name,
                            "f": f,
                            "level": POLARIS_LEVEL_KNOTS[index],
                            "step": step,
                        }
                    )
    return out


def _number(value: Any) -> float:
    """参数位上的 ``Number()``：``None`` 视为**未提供**（JS 的 ``undefined``）⇒ NaN。

    与 ``shared.js_number`` 的区别是刻意的：那个用于**结果字段**，字段上的 ``None``
    对应 JS 的 ``null``（``Number(null) === 0``）；这里的入参在 JS 侧没有默认值，
    省略即 ``undefined`` ⇒ ``Number(undefined) === NaN``，而"未提供"必须走不校准
    分支、不能被当成 0 参与查表。两者不可互换。
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def _curve_for(key_count: Any, side: str) -> dict[str, Any] | None:
    """按 (键数, 侧) 取生效曲线；None = 该组合不做修正。

    只有两套曲线，对应两组拟合人群：**7K 的 RC/LN 两半**与 **4K 的 LN 半**。
    其余组合一律 None——曲线是按各自键数的行为数据拟合的，套到别的键数上没有依据：
      - 4K RC：最终答案来自 Mixed 的路由链，不是表映射；
      - 6K / 10K：没有拟合数据（区间表存在，但没有对应曲线）。
    注意不能写成"非 4K 即 7K 曲线"：那样 6K 会被 7K 曲线静默校准。
    """
    if _number(key_count) != 7:
        return None
    return _REPAIRED["7K:LN"] if side == "LN" else _REPAIRED["7K:RC"]


def has_polaris_curve(key_count: Any, side: str) -> bool:
    """该 (键数, 侧) 是否存在生效曲线。消费方以此判断"这一半是否被校准过"。"""
    return _curve_for(key_count, side) is not None


# 与顶点一一对应的曲线插值（线性、端外截断）
def _interp_curve(values: tuple[float, ...], x: float) -> float:
    knots = POLARIS_LEVEL_KNOTS
    if x <= knots[0]:
        return values[0]
    if x >= knots[-1]:
        return values[-1]
    for index in range(len(knots) - 1):
        if knots[index] <= x <= knots[index + 1]:
            t = (x - knots[index]) / (knots[index + 1] - knots[index])
            return values[index] + (values[index + 1] - values[index]) * t
    return values[-1]


# LN 项插值（(x, y) 结点对，端外截断）
def _interp_knots(pairs: tuple[tuple[float, float], ...], x: float) -> float:
    if x <= pairs[0][0]:
        return pairs[0][1]
    if x >= pairs[-1][0]:
        return pairs[-1][1]
    for index in range(len(pairs) - 1):
        x0, y0 = pairs[index]
        x1, y1 = pairs[index + 1]
        if x0 <= x <= x1:
            t = (x - x0) / (x1 - x0) if x1 > x0 else 0.0
            return y0 + (y1 - y0) * t
    return pairs[-1][1]


def compute_polaris_correction(
    side: str, level: Any, rate: Any, ln_ratio: Any = 0.0, key_count: Any = 7
) -> float:
    """计算 Polaris 修正量（numeric 单位）。

    单调性：见文件头「单调性不变量」——``level + 返回值`` 在 level 上严格递增、在 rate
    上非降；两个方向都由生效系数保证，可用 ``verify_polaris_monotonicity()`` 自检。

    :param side: 谱面侧（"RC" / "LN"，与 Mixed、数据集的 0.375 lnRatio 切分同语义）
    :param level: 表映射得到的连续 level（star_to_level 的输出；
        4K LN 侧对应数据集 leo_numeric）
    :param rate: 速率（speedRate；1.0 = NM，1.5 = DT）
    :param ln_ratio: LN 侧使用；RC 侧忽略
    :param key_count: 键数（4 / 7）；其余键数与 4K 的 RC 侧无曲线，返回 0
    :return: 修正量（可为负）；rate < 1.0 或无曲线时返回 0
    """
    lv = _number(level)
    r = _number(rate)
    if not math.isfinite(lv) or not math.isfinite(r) or r < 1.0:
        return 0.0
    curve = _curve_for(key_count, side)
    if curve is None:
        return 0.0

    corr = _interp_curve(curve["B"], lv)
    if r > 1.0:
        corr += _interp_curve(curve["R"], lv) * min(1.0, (r - 1.0) / 0.5)
    if side == "LN":
        corr += _interp_knots(_H_LN, _number(ln_ratio))
    return corr


def _build_level_map(table: Any) -> dict[str, Any]:
    """区间表 → 连续数值映射（与 Mania Tracker 拟合所用的 star_to_numeric 同构）。

    每个 band ``(lo, hi, label)`` 给出两个点 ``(lo, n−0.1)``、``(hi, n+0.1)``；相邻 band
    端点值相等（连续）。``n`` 由 label 导出：层级 = 数字 token（Intro 减 3）
    或"新前缀 = 上一层 +1"，再加 tier 偏移。
    """
    seen: dict[str, int] = {}
    xs: list[float] = []
    ys: list[float] = []
    band_levels: list[float] = []
    band_labels: list[str] = []
    prev_level: int | None = None

    for lo, hi, label in table:
        parts = str(label).split(" ")
        tier = parts[-1]
        base = " ".join(parts[:-1])
        if base not in seen:
            token = base.split(" ")[-1]
            if _INT_DIGITS.match(token) and not base.startswith("Wild"):
                level = int(token) - 3 if base.startswith("Intro") else int(token)
            else:
                level = 0 if prev_level is None else prev_level + 1
            seen[base] = level
            prev_level = level

        # 表的标签都带合法 tier（数据由 data/intervals.py 持有）；缺 tier 视为表损坏，
        # 直接抛 KeyError 而不是像 JS 那样静默产出 NaN 并跳点。
        value = seen[base] + _TIER_OFFSETS[tier]
        for x, y in ((lo, value - 0.1), (hi, value + 0.1)):
            if not xs or x > xs[-1]:
                xs.append(x)
                ys.append(y)
        band_levels.append(value)
        band_labels.append(str(label))

    # 端点外推斜率（与拟合脚本同式：首/末 10 个结点的平均斜率）
    last = len(xs) - 1
    i0 = min(10, last)
    i1 = max(0, last - 10)
    s0 = (ys[i0] - ys[0]) / (xs[i0] - xs[0]) if xs[i0] > xs[0] else 0.0
    s1 = (ys[last] - ys[i1]) / (xs[last] - xs[i1]) if xs[last] > xs[i1] else 0.0
    return {
        "xs": xs,
        "ys": ys,
        "s0": s0,
        "s1": s1,
        "bandLevels": band_levels,
        "bandLabels": band_labels,
    }


# 表 → level map 缓存。键取 id(table) 并同时持有表引用，避免 id 被回收后重用。
_LEVEL_MAP_CACHE: dict[int, tuple[Any, dict[str, Any]]] = {}


def _get_level_map(table: Any) -> dict[str, Any]:
    key = id(table)
    cached = _LEVEL_MAP_CACHE.get(key)
    if cached is not None and cached[0] is table:
        return cached[1]
    built = _build_level_map(table)
    _LEVEL_MAP_CACHE[key] = (table, built)
    return built


def _star_to_level(level_map: dict[str, Any], star: float) -> float:
    """star → 连续 level（分段落线性；表范围外按端点斜率线性延伸）。"""
    xs, ys = level_map["xs"], level_map["ys"]
    x = _number(star)
    if x <= xs[0]:
        return ys[0] + (x - xs[0]) * level_map["s0"]
    last = len(xs) - 1
    if x >= xs[last]:
        return ys[last] + (x - xs[last]) * level_map["s1"]
    lo = bisect_right(xs, x) - 1
    hi = lo + 1
    t = (x - xs[lo]) / (xs[hi] - xs[lo])
    return ys[lo] + (ys[hi] - ys[lo]) * t


def _level_to_label(
    level_map: dict[str, Any], level: float, star: float, table: Any
) -> str:
    """连续 level → 区间标签（最近 band 中心；表范围外沿用 ``<`` / ``>`` 边界语义）。"""
    first = table[0]
    last = table[-1]
    if star < first[0]:
        return f"< {first[2]}"
    if star > last[1]:
        return f"> {last[2]}"

    best = 0
    best_distance = math.inf
    for index, band_level in enumerate(level_map["bandLevels"]):
        distance = abs(level - band_level)
        if distance < best_distance:
            best_distance = distance
            best = index
    return level_map["bandLabels"][best]


def _calibrate_half(
    table: Any, star: float, rate: float, ln_ratio: float, side: str, key_count: Any
) -> dict[str, Any] | None:
    """单个半段的表校准：star → level →（加 Polaris 修正）→ 标签。

    无表、或该 (键数, 侧) 没有曲线时返回 None —— 没有曲线的"校准结果"与表值逐位相同，
    返回非 None 会让消费方误以为"这一半被校准过"（Mixed 的 6K 曾因此被标成 Polaris）。
    ``inRange`` 与数值输出口径一致：star 落在表范围内才给外推数值（表外沿用
    ``<`` / ``>`` 边界标签语义）。
    """
    if not table or not has_polaris_curve(key_count, side):
        return None

    level_map = _get_level_map(table)
    base = _star_to_level(level_map, star)
    level = base + compute_polaris_correction(
        side, base, rate, ln_ratio=ln_ratio, key_count=key_count
    )
    return {
        "label": _level_to_label(level_map, level, star, table),
        "base": base,
        "level": level,
        "inRange": table[0][0] <= star <= table[-1][1],
    }


def calibrate_table_halves(
    column_count: Any, star: Any, rate: Any, ln_ratio: Any
) -> dict[str, Any] | None:
    """某一个键数下**表映射两半**的 Polaris 校准结果（Mixed 与 JS 侧共用同一份实现）。

    两半在混合路由里都只是"表映射产物"，因此这是它们唯一的校准入口。哪一半返回非 None
    由**曲线集**决定（``has_polaris_curve``）：4K 只有 LN 半边（RC 的最终答案来自路由链，
    不是表），7K 两半都有，**6K 都没有**——它有区间表但没有拟合曲线，因此两半都是 None，
    消费方据此保持原表映射（Mixed 的 6K 即走 Sunny）。

    :param column_count: 键数
    :param star: Sunny 原始 sr
    :param rate: 速率
    :param ln_ratio: Sunny lnRatio（LN 项 H 的查找键）
    :return: ``{"rc": ... | None, "ln": ... | None}``；无该键数的表或输入非有限时返回 None
    """
    key = _number(column_count)
    tables = _KEY_TABLES.get(int(key)) if math.isfinite(key) else None
    s = _number(star)
    r = _number(rate)
    lr = _number(ln_ratio)
    if tables is None or not (
        math.isfinite(s) and math.isfinite(r) and math.isfinite(lr)
    ):
        return None
    return {
        "rc": _calibrate_half(tables.get("RC"), s, r, lr, "RC", key),
        "ln": _calibrate_half(tables.get("LN"), s, r, lr, "LN", key),
    }
