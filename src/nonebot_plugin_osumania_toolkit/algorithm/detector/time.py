from collections import Counter

import numpy as np
from nonebot import get_plugin_config
from scipy.signal import find_peaks
from scipy.stats import gaussian_kde, lognorm

from ...config import Config
from .helpers import is_mr_replay, normalize_histogram, safe_sample_rate
from .types import AnalysisResult, Signal

config = get_plugin_config(Config)


def detect_press_duration_shape(non_empty_pressset: list[list[int]], max_time: int) -> Signal | None:
    """检测按压时长分布形态是否异常。

    Args:
        non_empty_pressset: 过滤后的按压时长分列数据。
        max_time: 统计上限毫秒值。

    Returns:
        命中时返回 Signal，否则返回 None。

    Raises:
        无显式抛出；内部统计异常会被吞掉并跳过该列。
    """

    suspicious_cols = 0
    fit_scores: list[float] = []
    smooth_scores: list[float] = []

    for col_data in non_empty_pressset:
        arr = np.array(col_data, dtype=float)
        arr = arr[(arr > 1) & (arr < max_time)]
        if len(arr) < 140:
            continue

        try:
            kde = gaussian_kde(arr, bw_method="scott")
        except Exception:
            continue

        xs = np.linspace(max(1.0, float(np.percentile(arr, 1))), float(np.percentile(arr, 99)), 64)
        kde_y = kde(xs)
        if np.max(kde_y) <= 1e-12:
            continue

        kde_y = kde_y / np.max(kde_y)
        sign_changes = np.sum(np.diff(np.sign(np.diff(kde_y))) != 0)
        smoothness = 1.0 - min(1.0, sign_changes / 40.0)

        try:
            shape, loc, scale = lognorm.fit(arr, floc=0)
            pdf = lognorm.pdf(xs, shape, loc=loc, scale=scale)
            if np.max(pdf) > 1e-12:
                pdf = pdf / np.max(pdf)
                fit_mse = float(np.mean((kde_y - pdf) ** 2))
            else:
                fit_mse = 1.0
        except Exception:
            fit_mse = 1.0

        fit_scores.append(1.0 - min(1.0, fit_mse / 0.05))
        smooth_scores.append(smoothness)

        if (smoothness >= config.time_shape_smoothness_hard or smoothness <= config.time_shape_smoothness_low) and fit_mse <= config.time_shape_fit_mse_hard:
            suspicious_cols += 1
        elif (smoothness >= config.time_shape_smoothness_soft or smoothness <= config.time_shape_smoothness_low) and fit_mse <= config.time_shape_fit_mse_soft:
            suspicious_cols += 1

    if suspicious_cols >= 2 and fit_scores and smooth_scores:
        return Signal(
            rule_id="time_shape",
            cheat=False,
            sus=True,
            risk=1,
            reason=(
                "按压时长分布形态异常"
                f"(异常列={suspicious_cols}, 平滑度中位={np.median(smooth_scores):.2f}, "
                f"理论贴合度中位={np.median(fit_scores):.2f})"
            ),
        )
    return None


def detect_duration_hidden_frequency(non_empty_pressset: list[list[int]]) -> Signal | None:
    """检测各列按压时长序列是否存在共同隐频。

    Args:
        non_empty_pressset: 过滤后的按压时长分列数据。

    Returns:
        命中时返回 Signal，否则返回 None。
    """

    peak_bins: list[int] = []
    strengths: list[float] = []

    for col_data in non_empty_pressset:
        arr = np.array(col_data, dtype=float)
        if len(arr) < 128:
            continue
        arr = arr - np.mean(arr)
        spec = np.abs(np.fft.rfft(arr))
        if len(spec) < 12:
            continue
        search = spec[2:min(40, len(spec))]
        if len(search) == 0:
            continue
        idx = int(np.argmax(search)) + 2
        base = float(np.mean(search)) if np.mean(search) > 1e-9 else 1.0
        strength = float(spec[idx] / base)
        peak_bins.append(idx)
        strengths.append(strength)

    if len(peak_bins) < 3:
        return None

    _, dominant_count = Counter(peak_bins).most_common(1)[0]
    dominant_ratio = dominant_count / len(peak_bins)
    median_strength = float(np.median(strengths))

    if dominant_ratio >= config.time_duration_freq_common_ratio and median_strength >= config.time_duration_freq_strength:
        return Signal(
            rule_id="time_hidden_freq",
            cheat=False,
            sus=True,
            risk=1,
            reason=f"按压时长序列存在共同隐频(共峰比={dominant_ratio*100:.1f}%, 频谱强度中位={median_strength:.2f})",
        )
    return None


def analyze_time_domain(data: dict) -> dict:
    """执行时域与按压时长分布分析。

    Args:
        data: osr.get_data() 返回字典。

    Returns:
        兼容旧接口的字典结果，包含 cheat/sus/reason/signals。
    """

    pressset = data["pressset"]
    sample_rate = safe_sample_rate(data)
    mr_flag = is_mr_replay(data)

    max_time = config.bin_max_time
    short_band = (0, 25)
    long_band = (100, max_time)

    abnormal_peak = False
    cheat = False
    suspicious = False
    reasons: list[str] = []
    signals: list[Signal] = []

    non_empty = [p for p in pressset if len(p) > 5]
    if len(non_empty) < 2:
        return {
            "percent": 0.0,
            "SR": 0,
            "cheat": False,
            "sus": False,
            "reason": "有效轨道少于2个，无法分析",
            "signals": [],
        }

    all_data = np.concatenate(non_empty)

    coarse_bins = int(max_time / 10)
    hist_list: list[np.ndarray] = []
    for press_data in non_empty:
        hist, _ = np.histogram(press_data, bins=coarse_bins, range=(0, max_time))
        hist_list.append(normalize_histogram(hist))

    n = len(hist_list)
    pair_sum = 0.0
    pair_count = 0
    norms = [float(np.linalg.norm(h)) for h in hist_list]
    for i in range(n):
        for j in range(i + 1, n):
            denom = norms[i] * norms[j]
            cos_sim = (float(np.dot(hist_list[i], hist_list[j])) / denom) if denom > 1e-12 else 0.0
            pair_sum += cos_sim
            pair_count += 1

    avg_sim = (pair_sum / pair_count) if pair_count > 0 else 0.0
    similarity_percent = avg_sim * 100

    if sample_rate > config.low_sample_rate_threshold and not mr_flag:
        bins = int(max_time / config.bin_width)
        hist_all, bin_edges = np.histogram(all_data, bins=bins, range=(0, max_time))
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

        def check_band(band_start: int, band_end: int, threshold_ratio: float, min_count: int = 10):
            """检测指定区间内是否有异常尖峰。

            Args:
                band_start: 区间起点。
                band_end: 区间终点。
                threshold_ratio: 尖峰占比阈值。
                min_count: 最小样本数。

            Returns:
                (是否异常, 峰值计数, 峰值位置)
            """
            band_mask = (bin_centers >= band_start) & (bin_centers < band_end)
            band_counts = hist_all[band_mask]
            if band_counts.sum() == 0:
                return False, None, None
            max_count = int(band_counts.max())
            max_idx = int(np.argmax(band_counts) + np.where(band_mask)[0][0])
            if max_count > threshold_ratio * band_counts.sum() and max_count > min_count:
                return True, max_count, float(bin_centers[max_idx])
            return False, None, None

        short_abnormal, short_count, short_time = check_band(short_band[0], short_band[1], config.abnormal_peak_threshold)
        if short_abnormal:
            abnormal_peak = True
            reasons.append(f"{short_time:.0f}ms出现异常高峰({short_count}次)")

        long_abnormal, long_count, long_time = check_band(long_band[0], long_band[1], config.abnormal_peak_threshold)
        if long_abnormal:
            abnormal_peak = True
            reasons.append(f"{long_time:.0f}ms出现异常高峰({long_count}次)")

        if not abnormal_peak:
            peaks, properties = find_peaks(hist_all, height=0.1 * np.max(hist_all), distance=5)
            peak_heights = properties["peak_heights"]
            if len(peaks) >= 2:
                sorted_idx = np.argsort(peak_heights)[::-1]
                main_peak = peaks[sorted_idx[0]]
                second_peak = peaks[sorted_idx[1]]
                main_height = peak_heights[sorted_idx[0]]
                second_height = peak_heights[sorted_idx[1]]
                main_center = bin_centers[main_peak]
                second_center = bin_centers[second_peak]
                if (second_height > 0.2 * main_height) and (abs(second_center - main_center) > 50):
                    abnormal_peak = True
                    reasons.append(f"整体分布出现双峰({main_center:.0f}ms和{second_center:.0f}ms)")

    shape_signal = detect_press_duration_shape(non_empty, max_time)
    if shape_signal is not None:
        suspicious = True
        signals.append(shape_signal)
        reasons.append(shape_signal.reason)

    freq_signal = detect_duration_hidden_frequency(non_empty)
    if freq_signal is not None:
        suspicious = True
        signals.append(freq_signal)
        reasons.append(freq_signal.reason)

    if avg_sim > config.sim_right_cheat_threshold:
        cheat = True
        suspicious = True
        signals.append(Signal("time_sim_high_cheat", True, True, 3, f"轨道相似度极高({similarity_percent:.1f}%)"))
        reasons.append(f"轨道相似度极高({similarity_percent:.1f}%)")
    if avg_sim < config.sim_left_cheat_threshold:
        cheat = True
        suspicious = True
        signals.append(Signal("time_sim_low_cheat", True, True, 3, f"轨道相似度极低({similarity_percent:.1f}%)"))
        reasons.append(f"轨道相似度极低({similarity_percent:.1f}%)")
    if avg_sim > config.sim_right_sus_threshold and not cheat:
        suspicious = True
        signals.append(Signal("time_sim_high_sus", False, True, 1, f"轨道相似度过高({similarity_percent:.1f}%)"))
        reasons.append(f"轨道相似度过高({similarity_percent:.1f}%)")
    if avg_sim < config.sim_left_sus_threshold and not cheat:
        suspicious = True
        signals.append(Signal("time_sim_low_sus", False, True, 1, f"轨道相似度过低({similarity_percent:.1f}%)"))
        reasons.append(f"轨道相似度过低({similarity_percent:.1f}%)")
    if abnormal_peak:
        suspicious = True
        signals.append(Signal("time_abnormal_peak", False, True, 1, "时长分布存在异常尖峰"))

    reason = "时域与按压时长分析：正常" if (not suspicious and not cheat) else "时域与按压时长分析： " + "; ".join(reasons)
    result = AnalysisResult(cheat=cheat, sus=suspicious, reason=reason, signals=signals)
    return {
        "cheat": result.cheat,
        "sus": result.sus,
        "reason": result.reason,
        "signals": [s.__dict__ for s in result.signals],
    }
