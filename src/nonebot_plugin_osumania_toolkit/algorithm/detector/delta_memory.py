import importlib

import numpy as np
from nonebot import get_plugin_config
from scipy.stats import pearsonr

from ...config import Config
from .types import Signal

config = get_plugin_config(Config)

try:
    _sm_diag = importlib.import_module("statsmodels.stats.diagnostic")
    _sm_stattools = importlib.import_module("statsmodels.tsa.stattools")
    het_arch = getattr(_sm_diag, "het_arch", None)
    bds = getattr(_sm_stattools, "bds", None)
    pacf = getattr(_sm_stattools, "pacf", None)
except Exception:  # pragma: no cover - 可选依赖缺失时降级
    bds = None
    het_arch = None
    pacf = None


def detect_nonlinear_memory(sorted_deltas: np.ndarray) -> Signal | None:
    """检测误差序列是否缺失人类常见的非线性记忆结构。"""

    arr = np.asarray(sorted_deltas, dtype=float)
    if len(arr) < config.delta_nonlinear_min_count:
        return None

    centered = arr - float(np.mean(arr))
    if float(np.var(centered)) < 1e-9:
        return None

    y = centered[1:]
    x = centered[:-1]
    x_mean = float(np.mean(x))
    y_mean = float(np.mean(y))
    denom = float(np.dot(x - x_mean, x - x_mean))
    beta = float(np.dot(x - x_mean, y - y_mean) / denom) if denom > 1e-9 else 0.0
    alpha = y_mean - beta * x_mean
    resid = y - (alpha + beta * x)

    if len(resid) < max(60, config.delta_nonlinear_min_count // 2):
        return None

    bds_trigger = False
    bds_p = 1.0
    fallback_sq_trigger = False
    fallback_p = 1.0

    if bds is not None:
        try:
            eps = float(np.std(resid) * config.delta_nonlinear_bds_eps_scale)
            bds_result = bds(resid, max_dim=2, epsilon=max(1e-6, eps), distance=1.5)
            if isinstance(bds_result, tuple) and len(bds_result) >= 2:
                pvals = np.asarray(bds_result[1], dtype=float)
                bds_p = float(np.min(pvals)) if len(pvals) > 0 else 1.0
            else:
                pvals = np.asarray(getattr(bds_result, "pvalue", [1.0]), dtype=float)
                bds_p = float(np.min(pvals)) if len(pvals) > 0 else 1.0
            bds_trigger = bds_p < config.delta_nonlinear_bds_p
        except Exception:
            bds_trigger = False

    if not bds_trigger:
        sq = resid**2
        if len(sq) >= 20:
            try:
                r, p = pearsonr(sq[:-1], sq[1:])
                fallback_p = float(p)
                fallback_sq_trigger = (abs(float(r)) >= config.delta_nonlinear_sqacf_threshold) and (
                    fallback_p < config.delta_nonlinear_bds_p
                )
            except Exception:
                fallback_sq_trigger = False

    pacf_trigger = False
    pacf_max = 0.0
    if pacf is not None and len(resid) >= 30:
        try:
            pacf_vals = pacf(resid, nlags=5, method="ywm")
            if len(pacf_vals) >= 6:
                tail = np.abs(np.asarray(pacf_vals[2:6], dtype=float))
                pacf_max = float(np.max(tail)) if len(tail) > 0 else 0.0
                pacf_trigger = pacf_max >= config.delta_nonlinear_pacf_threshold
        except Exception:
            pacf_trigger = False

    arch_trigger = False
    arch_p = 1.0
    if het_arch is not None and len(resid) >= 40:
        try:
            lm, lm_p, fval, f_p = het_arch(resid, nlags=5)
            arch_p = float(min(lm_p, f_p))
            arch_trigger = arch_p < config.delta_nonlinear_arch_p
        except Exception:
            arch_trigger = False

    if bds_trigger or fallback_sq_trigger or pacf_trigger or arch_trigger:
        bds_desc = f"BDS-p={bds_p:.3f}" if bds is not None else f"sq-acf-p={fallback_p:.3f}"
        return Signal(
            rule_id="delta_nonlinear_memory",
            cheat=False,
            sus=True,
            risk=2,
            reason=(
                "残差非线性记忆异常"
                f"({bds_desc}, PACF2-5max={pacf_max:.3f}, ARCH-p={arch_p:.3f})"
            ),
        )
    return None


def detect_ar1_memory_pattern(sorted_deltas: np.ndarray) -> Signal | None:
    """检测误差序列是否过于符合固定 AR(1) 指数衰减记忆。"""

    arr = np.array(sorted_deltas, dtype=float)
    if len(arr) < 260:
        return None

    arr = arr - np.mean(arr)
    var = float(np.var(arr))
    if var < 1e-9:
        return None

    max_lag = min(20, len(arr) // 8)
    if max_lag < 6:
        return None

    acf = []
    for lag in range(1, max_lag + 1):
        v = float(np.dot(arr[:-lag], arr[lag:]) / ((len(arr) - lag) * var))
        acf.append(v)
    acf = np.array(acf, dtype=float)

    pos = np.where(acf > 0.02)[0]
    if len(pos) < 5:
        return None

    lags = (pos + 1).astype(float)
    ys = np.log(acf[pos])
    slope, intercept = np.polyfit(lags, ys, 1)
    pred = slope * lags + intercept
    ss_res = float(np.sum((ys - pred) ** 2))
    ss_tot = float(np.sum((ys - np.mean(ys)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0

    if slope < 0 and r2 >= config.delta_ar1_fit_hard_r2:
        return Signal(
            rule_id="delta_ar1_hard",
            cheat=False,
            sus=True,
            risk=2,
            reason=f"误差记忆深度过于规则(AR1指数拟合R2={r2:.3f})",
        )
    if slope < 0 and r2 >= config.delta_ar1_fit_soft_r2:
        return Signal(
            rule_id="delta_ar1_soft",
            cheat=False,
            sus=True,
            risk=1,
            reason=f"误差序列呈固定记忆衰减(AR1指数拟合R2={r2:.3f})",
        )
    return None


def detect_fatigue_trend(sorted_notes: list[float], sorted_deltas: np.ndarray, density_arr: np.ndarray) -> Signal | None:
    """检测疲劳趋势与密度形态响应是否过于规整。"""

    if len(sorted_notes) < 320:
        return None

    notes = np.array(sorted_notes, dtype=float)
    deltas = np.array(sorted_deltas, dtype=float)
    progress = (notes - notes.min()) / max(1.0, notes.max() - notes.min())
    abs_err = np.abs(deltas - np.median(deltas))

    bins = np.linspace(0.0, 1.0, 7)
    seg_std = []
    for i in range(len(bins) - 1):
        mask = (progress >= bins[i]) & (progress < bins[i + 1])
        if np.sum(mask) >= 20:
            seg_std.append(float(np.std(abs_err[mask])))
    if len(seg_std) < 4:
        return None

    seg_std_arr = np.array(seg_std, dtype=float)
    mono_ratio = float(np.mean(np.diff(seg_std_arr) >= 0))

    high_th = np.percentile(density_arr, 85)
    low_th = np.percentile(density_arr, 30)
    high_vals = abs_err[density_arr >= high_th]
    low_vals = abs_err[density_arr <= low_th]
    if len(high_vals) < 60 or len(low_vals) < 60:
        return None

    def shape(arr: np.ndarray) -> np.ndarray:
        qs = np.percentile(arr, [10, 25, 50, 75, 90]).astype(float)
        return qs / max(1e-6, qs[2])

    shape_diff = float(np.mean(np.abs(shape(high_vals) - shape(low_vals))))

    if mono_ratio >= config.delta_fatigue_mono_hard and shape_diff <= config.delta_fatigue_shape_diff_hard:
        return Signal(
            rule_id="delta_fatigue_hard",
            cheat=False,
            sus=True,
            risk=2,
            reason=f"疲劳与密度响应过于固定(单调比={mono_ratio:.2f}, 形状差={shape_diff:.3f})",
        )
    if mono_ratio >= config.delta_fatigue_mono_soft and shape_diff <= config.delta_fatigue_shape_diff_soft:
        return Signal(
            rule_id="delta_fatigue_soft",
            cheat=False,
            sus=True,
            risk=1,
            reason=f"误差趋势可能预设化(单调比={mono_ratio:.2f}, 形状差={shape_diff:.3f})",
        )
    return None
