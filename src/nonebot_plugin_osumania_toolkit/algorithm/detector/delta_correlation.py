import numpy as np
from nonebot import get_plugin_config

from ...config import Config
from .types import Signal

config = get_plugin_config(Config)


def _safe_corrcoef(x: np.ndarray, y: np.ndarray) -> float:
    """计算鲁棒相关系数，避免常量序列导致异常。"""

    if len(x) < 3 or len(y) < 3:
        return 0.0
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    xc = x - float(np.mean(x))
    yc = y - float(np.mean(y))
    nx = float(np.linalg.norm(xc))
    ny = float(np.linalg.norm(yc))
    if nx < 1e-9 or ny < 1e-9:
        return 0.0
    return float(np.dot(xc, yc) / (nx * ny))


def _align_by_sorted_keys(
    keys_a: np.ndarray,
    vals_a: np.ndarray,
    keys_b: np.ndarray,
    vals_b: np.ndarray,
    lag: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """按键值对齐两列序列（双指针，支持 lag 对齐）。"""

    i = 0
    j = 0
    n_a = len(keys_a)
    n_b = len(keys_b)
    idx_a: list[int] = []
    idx_b: list[int] = []

    while i < n_a and j < n_b:
        ka = int(keys_a[i]) + lag
        kb = int(keys_b[j])
        if ka == kb:
            idx_a.append(i)
            idx_b.append(j)
            i += 1
            j += 1
        elif ka < kb:
            i += 1
        else:
            j += 1

    if not idx_a:
        return np.array([], dtype=float), np.array([], dtype=float)

    return vals_a[np.array(idx_a, dtype=int)], vals_b[np.array(idx_b, dtype=int)]


def _build_col_time_delta_series(
    delta_list: list[tuple[int, float]],
    note_times_by_col: dict[int, list[float]],
) -> dict[int, list[tuple[float, float]]]:
    """按列构建 (note_time, delta) 序列。"""

    cursors = {col: 0 for col in note_times_by_col}
    series: dict[int, list[tuple[float, float]]] = {}
    for col, delta in delta_list:
        times = note_times_by_col.get(col)
        if not times:
            continue
        idx = cursors.get(col, 0)
        if idx >= len(times):
            continue
        series.setdefault(col, []).append((float(times[idx]), float(delta)))
        cursors[col] = idx + 1
    return {c: v for c, v in series.items() if len(v) >= 10}


def _extract_chord_times(note_times_by_col: dict[int, list[float]], tol_ms: float = 1.0) -> set[int]:
    """提取多押时间点（按毫秒量化后的桶）。"""

    all_points: list[tuple[float, int]] = []
    for col, times in note_times_by_col.items():
        for t in times:
            all_points.append((float(t), int(col)))
    if len(all_points) < 2:
        return set()

    all_points.sort(key=lambda x: x[0])
    chord_buckets: set[int] = set()
    n = len(all_points)
    i = 0
    while i < n:
        t0 = all_points[i][0]
        cols = {all_points[i][1]}
        j = i + 1
        while j < n and all_points[j][0] - t0 <= tol_ms:
            cols.add(all_points[j][1])
            j += 1
        if len(cols) >= 2:
            for k in range(i, j):
                chord_buckets.add(int(round(all_points[k][0])))
        i = j
    return chord_buckets


def detect_cross_correlation(
    delta_list: list[tuple[int, float]],
    note_times_by_col: dict[int, list[float]],
) -> Signal | None:
    """检测轨道间误差相关性是否异常接近零。"""

    if len(delta_list) < config.delta_cross_corr_min_pairs:
        return None

    series = _build_col_time_delta_series(delta_list, note_times_by_col)
    if len(series) < 2:
        return None

    chord_buckets = _extract_chord_times(note_times_by_col, tol_ms=config.delta_cross_corr_chord_tol_ms)

    per_col_bucket: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    for col, points in series.items():
        bucket_to_vals: dict[int, list[float]] = {}
        for t, d in points:
            bucket = int(round(t))
            if bucket in chord_buckets:
                continue
            bucket_to_vals.setdefault(bucket, []).append(float(d))
        if len(bucket_to_vals) < 10:
            continue
        sorted_keys = np.array(sorted(bucket_to_vals.keys()), dtype=np.int32)
        sorted_vals = np.array([float(np.mean(bucket_to_vals[int(k)])) for k in sorted_keys], dtype=float)
        if len(sorted_keys) >= 10:
            per_col_bucket[col] = (sorted_keys, sorted_vals)

    cols = sorted(per_col_bucket)
    if len(cols) < 2:
        return None

    abs_corrs: list[float] = []
    abs_lag_max: list[float] = []
    used_pairs = 0
    total_pairs_samples = 0

    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            ci, cj = cols[i], cols[j]
            keys_i, vals_i = per_col_bucket[ci]
            keys_j, vals_j = per_col_bucket[cj]

            xi, yj = _align_by_sorted_keys(keys_i, vals_i, keys_j, vals_j, lag=0)
            if len(xi) < 16:
                continue

            c0 = abs(_safe_corrcoef(xi, yj))

            max_lag_corr = c0
            for lag in (-2, -1, 1, 2):
                xx, yy = _align_by_sorted_keys(keys_i, vals_i, keys_j, vals_j, lag=lag)
                if len(xx) < 16:
                    continue
                max_lag_corr = max(max_lag_corr, abs(_safe_corrcoef(xx, yy)))

            used_pairs += 1
            total_pairs_samples += len(xi)
            abs_corrs.append(c0)
            abs_lag_max.append(max_lag_corr)

    if used_pairs < 2 or total_pairs_samples < config.delta_cross_corr_min_pairs:
        return None

    med_abs_corr = float(np.median(abs_corrs)) if abs_corrs else 1.0
    med_abs_lag = float(np.median(abs_lag_max)) if abs_lag_max else 1.0

    if med_abs_corr < config.delta_cross_corr_threshold:
        lag_msg = ""
        if med_abs_lag < config.delta_cross_corr_lag_threshold:
            lag_msg = f", 滞后互相关中位={med_abs_lag:.3f}"
        return Signal(
            rule_id="delta_cross_corr",
            cheat=False,
            sus=True,
            risk=2,
            reason=(
                "轨道间误差相关性过低"
                f"(对数={used_pairs}, 对齐样本={total_pairs_samples}, 零滞后|r|中位={med_abs_corr:.3f}{lag_msg})"
            ),
        )
    return None


def detect_column_autocorr_and_drift(delta_list: list[tuple[int, float]]) -> Signal | None:
    """检测列内偏移序列的自相关与周期漂移异常。"""

    col_delta: dict[int, np.ndarray] = {}
    for col, d in delta_list:
        col_delta.setdefault(col, []).append(float(d))
    col_delta = {c: np.array(v, dtype=float) for c, v in col_delta.items() if len(v) >= 140}

    if len(col_delta) < 2:
        return None

    strong_cols = 0
    suspicious_cols = 0
    peak_lags: list[int] = []
    low_freq_var_ratios: list[float] = []

    for arr in col_delta.values():
        centered = arr - np.mean(arr)
        std = float(np.std(centered))
        if std < 1e-6:
            continue

        n = len(centered)
        sq = centered * centered
        prefix_sq = np.zeros(n + 1, dtype=float)
        prefix_sq[1:] = np.cumsum(sq)

        max_lag = min(n // 3, 48)
        if max_lag < 8:
            continue

        ac_vals = []
        for lag in range(1, max_lag + 1):
            a = centered[:-lag]
            b = centered[lag:]
            norm_a_sq = float(prefix_sq[n - lag] - prefix_sq[0])
            norm_b_sq = float(prefix_sq[n] - prefix_sq[lag])
            denom = float(np.sqrt(max(norm_a_sq, 0.0)) * np.sqrt(max(norm_b_sq, 0.0)))
            ac = float(np.dot(a, b) / denom) if denom > 1e-9 else 0.0
            ac_vals.append(ac)
        ac_arr = np.array(ac_vals, dtype=float)

        best_lag = int(np.argmax(ac_arr)) + 1
        best_ac = float(ac_arr[best_lag - 1])

        fft_vals = np.fft.rfft(centered)
        power = np.abs(fft_vals) ** 2
        if len(power) <= 4:
            continue

        low_power = float(np.sum(power[1:min(5, len(power))]))
        total_power = float(np.sum(power[1:]))
        low_ratio = (low_power / total_power) if total_power > 1e-9 else 0.0

        peak_lags.append(best_lag)
        low_freq_var_ratios.append(low_ratio)

        if best_ac >= config.delta_col_autocorr_hard and low_ratio >= config.delta_col_lowfreq_hard:
            strong_cols += 1
        elif best_ac >= config.delta_col_autocorr_soft and low_ratio >= config.delta_col_lowfreq_soft:
            suspicious_cols += 1

    if strong_cols >= 2:
        return Signal(
            rule_id="delta_col_autocorr_hard",
            cheat=False,
            sus=True,
            risk=2,
            reason=(
                "列内自相关与周期漂移异常"
                f"(强异常列={strong_cols}, 峰值lag中位={np.median(peak_lags):.0f}, "
                f"低频能量比中位={np.median(low_freq_var_ratios):.2f})"
            ),
        )
    if strong_cols + suspicious_cols >= 2:
        return Signal(
            rule_id="delta_col_autocorr_soft",
            cheat=False,
            sus=True,
            risk=1,
            reason=(
                "列内周期结构偏强"
                f"(异常列={strong_cols + suspicious_cols}, 峰值lag中位={np.median(peak_lags):.0f}, "
                f"低频能量比中位={np.median(low_freq_var_ratios):.2f})"
            ),
        )
    return None
