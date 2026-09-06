from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from ...parser.osu_file_parser import osu_file


BREAK_ZERO_THRESHOLD_MS = 400
GRAPH_RESAMPLE_INTERVAL_MS = 100
SMOOTH_SIGMA_MS = 800


def _bisect_left(arr: np.ndarray, target: float) -> int:
    return int(np.searchsorted(arr, target, side="left"))


def _bisect_right(arr: np.ndarray, target: float) -> int:
    return int(np.searchsorted(arr, target, side="right"))


def _cumulative_sum(x: np.ndarray, f: np.ndarray) -> np.ndarray:
    F = np.zeros(len(x), dtype=np.float64)
    F[1:] = np.cumsum(f[:-1] * np.diff(x))
    return F


def _query_cumsum(q: float, x: np.ndarray, F: np.ndarray, f: np.ndarray) -> float:
    if q <= x[0]:
        return 0.0
    if q >= x[-1]:
        return float(F[-1])
    i = _bisect_right(x, q) - 1
    return float(F[i] + f[i] * (q - x[i]))


def _query_cumsum_vec(q_arr: np.ndarray, x: np.ndarray, F: np.ndarray, f: np.ndarray) -> np.ndarray:
    """_query_cumsum 的向量化版本（边界语义一致：q<=x[0]→0，q>=x[-1]→F[-1]）。"""
    i = np.searchsorted(x, q_arr, side="right") - 1
    i_clamped = np.clip(i, 0, len(x) - 1)
    vals = F[i_clamped] + f[i_clamped] * (q_arr - x[i_clamped])
    vals = np.where(q_arr <= x[0], 0.0, vals)
    vals = np.where(q_arr >= x[-1], F[-1], vals)
    return vals


def _smooth_on_corners(
    x: np.ndarray, f: np.ndarray, window: float, scale: float = 1.0, mode: str = "sum"
) -> np.ndarray:
    F = _cumulative_sum(x, f)
    a = np.clip(x - window, x[0], x[-1])
    b = np.clip(x + window, x[0], x[-1])
    # Vectorized queryCumsum
    val = _query_cumsum_vec(b, x, F, f) - _query_cumsum_vec(a, x, F, f)
    if mode == "avg":
        span = b - a
        return np.where(span > 0, val / span, 0.0)
    return scale * val


def _interp_values(new_x: np.ndarray, old_x: np.ndarray, old_vals: np.ndarray) -> np.ndarray:
    return np.interp(new_x, old_x, old_vals)


def _step_interp(new_x: np.ndarray, old_x: np.ndarray, old_vals: np.ndarray) -> np.ndarray:
    indices = np.searchsorted(old_x, new_x, side="right") - 1
    indices = np.clip(indices, 0, len(old_vals) - 1)
    return old_vals[indices]


def _gaussian_filter_1d(data: list[float], sigma_samples: float) -> list[float]:
    if not math.isfinite(sigma_samples) or sigma_samples <= 0:
        return list(data)
    radius = max(1, int(4.0 * sigma_samples + 0.5))
    kernel_size = radius * 2 + 1
    kernel = np.array([math.exp(-0.5 * ((i - radius) / sigma_samples) ** 2) for i in range(kernel_size)])
    kernel /= kernel.sum()
    padded = np.pad(data, (radius, radius), mode="edge")
    out = np.convolve(padded, kernel, mode="valid")
    return list(out[: len(data)])


def _rescale_high(sr: float) -> float:
    if sr <= 9.0:
        return sr
    return 9.0 + (sr - 9.0) * (1.0 / 1.2)


def _preprocess_daniel(
    file_path: str, speed_rate: float, *, chart: Any = None
) -> dict[str, Any]:
    # chart 非 None 时跳过解析，clone 防御。
    if chart is not None:
        p_obj = chart.clone()
    else:
        p_obj = osu_file(file_path)
        p_obj.process()
    parsed = p_obj.get_parsed_data()
    # parsed: [column_count, columns, note_starts, note_ends, note_types, od, GameMode, status, LN_ratio, meta_data, breaks, object_intervals]

    ln_ratio = float(parsed[8] or 0)
    column_count = int(parsed[0] or 0)
    status = str(parsed[7] or "")

    if status == "Fail":
        return {"status": "Fail", "x": 0.0, "K": 0, "T": 0, "noteSeq": [], "noteSeqByColumn": [], "lnRatio": ln_ratio, "columnCount": column_count}
    if status == "NotMania":
        return {"status": "NotMania", "x": 0.0, "K": 0, "T": 0, "noteSeq": [], "noteSeqByColumn": [], "lnRatio": ln_ratio, "columnCount": column_count}
    if column_count != 4:
        return {"status": "UnsupportedKeys", "x": 0.0, "K": column_count, "T": 0, "noteSeq": [], "noteSeqByColumn": [], "lnRatio": ln_ratio, "columnCount": column_count}

    # OD is hardcoded to 9 for Daniel
    od = 9

    time_scale = 1.0 / speed_rate if speed_rate != 0 else 1.0

    # Build noteSeq: (column, head_time) — Daniel only uses starts, no LN ends
    note_seq = []
    columns = parsed[1]
    note_starts = parsed[2]

    for i in range(len(columns)):
        k = columns[i]
        h = note_starts[i]
        h = int(math.floor(h * time_scale))
        note_seq.append((k, h))

    note_seq.sort(key=lambda t: (t[1], t[0]))

    K = column_count
    note_seq_by_column_dict = defaultdict(list)
    for n in note_seq:
        col = n[0]
        if 0 <= col < K:
            note_seq_by_column_dict[col].append(n)
    note_seq_by_column = [note_seq_by_column_dict[k] for k in range(K)]

    # x = hit tolerance
    x_val = 0.3 * math.sqrt((64.5 - math.ceil(od * 3)) / 500)
    x_val = min(x_val, 0.6 * (x_val - 0.09) + 0.09)

    T = note_seq[-1][1] + 1 if note_seq else 0

    return {
        "status": "OK",
        "x": x_val,
        "K": K,
        "T": T,
        "noteSeq": note_seq,
        "noteSeqByColumn": note_seq_by_column,
        "lnRatio": ln_ratio,
        "columnCount": column_count,
    }


# ═══════════════════════════════════════════════════════════════════
# Corner & usage computation
# ═══════════════════════════════════════════════════════════════════

def _get_corners(T: int, note_seq: list) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    corners_base: set[int] = set()
    for _, h in note_seq:
        corners_base.add(h)
        corners_base.add(h + 501)
        corners_base.add(h - 499)
        corners_base.add(h + 1)
    corners_base.add(0)
    corners_base.add(T)

    base_corners = sorted(s for s in corners_base if 0 <= s <= T)
    base_corners_arr = np.array(base_corners, dtype=float)

    corners_a: set[int] = set()
    for _, h in note_seq:
        corners_a.add(h)
        corners_a.add(h + 1000)
        corners_a.add(h - 1000)
    corners_a.add(0)
    corners_a.add(T)

    a_corners = sorted(s for s in corners_a if 0 <= s <= T)
    a_corners_arr = np.array(a_corners, dtype=float)

    all_corners = sorted(set(base_corners) | set(a_corners))
    all_corners_arr = np.array(all_corners, dtype=float)

    return all_corners_arr, base_corners_arr, a_corners_arr


def _get_key_usage(
    K: int, T: int, note_seq: list, base_corners: np.ndarray
) -> dict[int, np.ndarray]:
    """差分 + 前缀和实现：批量 searchsorted 一次定位全部区间端点。
    Daniel 语义：所有音符 end 一律 min(h+150, T-1) 钳位（无 LN 区分）。"""
    bc = np.asarray(base_corners, dtype=float)
    n = len(bc)
    empty = {k: np.zeros(n, dtype=np.uint8) for k in range(K)}
    if not note_seq or K <= 0:
        return empty
    m = len(note_seq)
    ks = np.fromiter((k for (k, h) in note_seq), dtype=np.int64, count=m)
    hs = np.fromiter((h for (k, h) in note_seq), dtype=float, count=m)
    starts = np.maximum(hs - 150.0, 0.0)
    ends = np.minimum(hs + 150.0, float(T) - 1.0)
    lis = np.searchsorted(bc, starts, side="left")
    ris = np.searchsorted(bc, ends, side="left")
    diff = np.zeros((K, n + 1), dtype=np.int32)
    np.add.at(diff, (ks, np.minimum(lis, n)), 1)
    np.add.at(diff, (ks, np.minimum(ris, n)), -1)
    usage2d = np.cumsum(diff, axis=1)[:, :n] > 0
    return {k: usage2d[k].astype(np.uint8) for k in range(K)}


def _get_key_usage_400(
    K: int, note_seq: list, base_corners: np.ndarray
) -> dict[int, np.ndarray]:
    """批量 searchsorted 后按音符做纯切片累加，消除逐音符标量 bisect 与纯 Python 内层循环。"""
    bc = np.asarray(base_corners, dtype=float)
    n = len(bc)
    arr = np.zeros((K, n), dtype=np.float64)
    inv_400_sq = 3.75 / (400 * 400)
    if not note_seq or K <= 0:
        return {k: arr[k] for k in range(K)}
    m = len(note_seq)
    ks = np.fromiter((k for (k, h) in note_seq), dtype=np.int64, count=m)
    hs = np.fromiter((h for (k, h) in note_seq), dtype=float, count=m)
    left400s = np.searchsorted(bc, hs - 400.0, side="left")
    centers = np.searchsorted(bc, hs, side="left")
    right400s = np.searchsorted(bc, hs + 400.0, side="left")

    for i in range(m):
        k = ks[i]
        h = hs[i]
        center = centers[i]
        row = arr[k]
        if 0 <= center < n:
            row[center] += 3.75
        l400 = left400s[i]
        if center > l400:
            seg = bc[l400:center]
            row[l400:center] += 3.75 - inv_400_sq * (seg - h) ** 2
        r400 = right400s[i]
        if r400 > center + 1:
            seg = bc[center + 1:r400]
            row[center + 1:r400] += 3.75 - inv_400_sq * (seg - h) ** 2

    return {k: arr[k] for k in range(K)}


# ═══════════════════════════════════════════════════════════════════
# Strain components
# ═══════════════════════════════════════════════════════════════════

def _compute_anchor(
    K: int, key_usage_400: dict[int, np.ndarray], base_corners: np.ndarray
) -> np.ndarray:
    counts = np.stack([key_usage_400[k] for k in range(K)], axis=1)
    counts_sorted = -np.sort(-counts, axis=1)  # descending sort

    nonzero_mask = counts_sorted > 0
    n_nz = nonzero_mask.sum(axis=1)

    c0 = counts_sorted[:, :-1]
    c1 = counts_sorted[:, 1:]
    safe_c0 = np.where(c0 > 0, c0, 1.0)
    ratio = np.where(c0 > 0, c1 / safe_c0, 0.0)
    weight = 1.0 - 4.0 * (0.5 - ratio) ** 2

    pair_valid = nonzero_mask[:, :-1] & nonzero_mask[:, 1:]
    walk = np.sum(np.where(pair_valid, c0 * weight, 0.0), axis=1)
    max_walk = np.sum(np.where(pair_valid, c0, 0.0), axis=1)

    raw_anchor = np.where(n_nz > 1, walk / np.maximum(max_walk, 1e-9), 0.0)
    anchor = 1.0 + np.minimum(raw_anchor - 0.18, 5.0 * (raw_anchor - 0.22) ** 3)
    return anchor


def _jack_nerfer(delta: float) -> float:
    return 1.0 - 7e-5 * (0.15 + abs(delta - 0.08)) ** (-4)


def _compute_jbar(
    K: int, x: float, note_seq_by_column: list, base_corners: np.ndarray
) -> tuple[dict[int, np.ndarray], np.ndarray]:
    bc = np.asarray(base_corners, dtype=float)
    J_ks: dict[int, np.ndarray] = {k: np.zeros(len(base_corners)) for k in range(K)}
    delta_ks: dict[int, np.ndarray] = {k: np.full(len(base_corners), 1e9) for k in range(K)}

    for k in range(K):
        notes = note_seq_by_column[k]
        if len(notes) < 2:
            continue
        starts = np.array([notes[i][1] for i in range(len(notes) - 1)], dtype=float)
        ends = np.array([notes[i + 1][1] for i in range(len(notes) - 1)], dtype=float)
        valid = ends > starts
        starts = starts[valid]
        ends = ends[valid]
        if len(starts) == 0:
            continue
        deltas = 0.001 * (ends - starts)
        # _jack_nerfer 向量化：1 - 7e-5 * (0.15 + |delta - 0.08|)^-4
        vals = (deltas ** -1) * ((deltas + 0.11 * (x ** 0.25)) ** -1) * (
            1.0 - 7e-5 * (0.15 + np.abs(deltas - 0.08)) ** (-4)
        )
        lis = np.searchsorted(bc, starts, side="left")
        ris = np.searchsorted(bc, ends, side="left")
        J_row = J_ks[k]
        d_row = delta_ks[k]
        for left_idx, right_idx, delta, val in zip(lis, ris, deltas, vals):
            if left_idx >= right_idx:
                continue
            J_row[left_idx:right_idx] = val
            d_row[left_idx:right_idx] = delta

    Jbar_ks = {k: _smooth_on_corners(base_corners, J_ks[k], window=500.0, scale=0.001, mode="sum") for k in range(K)}

    Jbar_stack = np.stack([Jbar_ks[k] for k in range(K)], axis=0)
    delta_stack = np.stack([delta_ks[k] for k in range(K)], axis=0)
    weights = 1.0 / np.maximum(delta_stack, 1e-9)
    num = np.sum(np.maximum(Jbar_stack, 0) ** 5 * weights, axis=0)
    den = np.sum(weights, axis=0)
    Jbar = (num / np.maximum(den, 1e-9)) ** 0.2

    return delta_ks, Jbar


_CROSS_MATRIX = [
    [-1],
    [0.075, 0.075],
    [0.125, 0.05, 0.125],
    [0.125, 0.125, 0.125, 0.125],
    [0.175, 0.25, 0.05, 0.25, 0.175],
    [0.175, 0.25, 0.175, 0.175, 0.25, 0.175],
    [0.225, 0.35, 0.25, 0.05, 0.25, 0.35, 0.225],
    [0.225, 0.35, 0.25, 0.225, 0.225, 0.25, 0.35, 0.225],
    [0.275, 0.45, 0.35, 0.25, 0.05, 0.25, 0.35, 0.45, 0.275],
    [0.275, 0.45, 0.35, 0.25, 0.275, 0.275, 0.25, 0.35, 0.45, 0.275],
    [0.325, 0.55, 0.45, 0.35, 0.25, 0.05, 0.25, 0.35, 0.45, 0.55, 0.325],
]


def _compute_xbar(
    K: int, x: float, note_seq_by_column: list, key_usage: dict[int, np.ndarray], base_corners: np.ndarray
) -> np.ndarray:
    bc = np.asarray(base_corners, dtype=float)
    cross_coeff = _CROSS_MATRIX[K]
    X_ks: dict[int, np.ndarray] = {k: np.zeros(len(base_corners)) for k in range(K + 1)}
    fast_cross: dict[int, np.ndarray] = {k: np.zeros(len(base_corners)) for k in range(K + 1)}

    for k in range(K + 1):
        if k == 0:
            notes_in_pair = note_seq_by_column[0] if K > 0 else []
        elif k == K:
            notes_in_pair = note_seq_by_column[K - 1] if K > 0 else []
        else:
            notes_in_pair = sorted(note_seq_by_column[k - 1] + note_seq_by_column[k], key=lambda t: t[1])
        if len(notes_in_pair) < 2:
            continue

        starts = np.array([notes_in_pair[i - 1][1] for i in range(1, len(notes_in_pair))], dtype=float)
        ends = np.array([notes_in_pair[i][1] for i in range(1, len(notes_in_pair))], dtype=float)
        valid = ends > starts
        starts = starts[valid]
        ends = ends[valid]
        if len(starts) == 0:
            continue
        deltas = 0.001 * (ends - starts)
        vals = 0.16 * (np.maximum(x, deltas) ** -2)
        fast_vals = np.maximum(0.0, 0.4 * (np.maximum(np.maximum(deltas, 0.06), 0.75 * x) ** -2) - 80.0)
        lis = np.searchsorted(bc, starts, side="left")
        ris = np.searchsorted(bc, ends, side="left")

        X_row = X_ks[k]
        fc_row = fast_cross[k]
        ku_left = key_usage[k - 1] if k >= 1 else None
        ku_right = key_usage[k] if 1 <= k < K else None
        for left_idx, right_idx, val, fast_val in zip(lis, ris, vals, fast_vals):
            if right_idx <= left_idx:
                continue
            # 基线语义：k==0 时 (k-1)=-1 永不在 active_columns → left 恒无效；
            # k==K 时 k 永不在 active_columns → right 恒无效。两者均恒缩放。
            if k == 0 or k == K:
                inactive = True
            else:
                left_inactive = ku_left[left_idx] == 0 and ku_left[right_idx] == 0
                right_inactive = ku_right[left_idx] == 0 and ku_right[right_idx] == 0
                inactive = left_inactive or right_inactive
            if inactive:
                val = val * (1.0 - cross_coeff[k])
            X_row[left_idx:right_idx] = val
            fc_row[left_idx:right_idx] = fast_val

    # X_base 广播求和：替代 O(角点×K) 的逐角点 Python 循环。
    # 基线 sum2 对 pair<=0 跳过；fast_cross>=0 且 cross_coeff>=0（K>=1），乘积非负，sqrt 安全，
    # pair==0 时 sqrt(0)=0 与跳过等价。
    X_ks_arr = np.stack([X_ks[k] for k in range(K + 1)], axis=0)
    coeff_arr = np.asarray(cross_coeff, dtype=float)[:, np.newaxis]
    X_base = np.sum(X_ks_arr * coeff_arr, axis=0)

    fc_arr = np.stack([fast_cross[k] for k in range(K + 1)], axis=0)
    cc = np.asarray(cross_coeff, dtype=float)
    X_base += np.sum(
        np.sqrt(fc_arr[:-1] * cc[:-1, np.newaxis] * fc_arr[1:] * cc[1:, np.newaxis]), axis=0
    )

    return _smooth_on_corners(base_corners, X_base, window=500.0, scale=0.001, mode="sum")


def _stream_booster_daniel(delta: float) -> float:
    """Daniel-specific sigmoid-based stream booster."""
    bpm = max(0.0, min(7.5 / max(delta, 1e-9), 420.0))
    primary = 0.10 / (1.0 + math.exp(-0.06 * (bpm - 175.0)))
    secondary = 0.30 * (1.0 - math.exp(-0.02 * (bpm - 200.0))) if (200.0 <= bpm <= 350.0) else 0.0
    return 1.0 + primary + secondary


def _stream_booster_daniel_vec(deltas: np.ndarray) -> np.ndarray:
    """_stream_booster_daniel 的向量化版本。"""
    bpm = np.clip(7.5 / np.maximum(deltas, 1e-9), 0.0, 420.0)
    primary = 0.10 / (1.0 + np.exp(-0.06 * (bpm - 175.0)))
    secondary = np.where(
        (bpm >= 200.0) & (bpm <= 350.0),
        0.30 * (1.0 - np.exp(-0.02 * (bpm - 200.0))),
        0.0,
    )
    return 1.0 + primary + secondary


def _compute_pbar(
    x: float, note_seq: list, anchor: np.ndarray, base_corners: np.ndarray
) -> np.ndarray:
    bc = np.asarray(base_corners, dtype=float)
    P_step = np.zeros(len(base_corners))

    if len(note_seq) > 1:
        hs = np.array([note[1] for note in note_seq], dtype=float)
        h_ls = hs[:-1]
        h_rs = hs[1:]
        delta_times = h_rs - h_ls
        lis = np.searchsorted(bc, h_ls, side="left")
        ris = np.searchsorted(bc, h_rs, side="left")
        ris_right = np.searchsorted(bc, h_ls, side="right")
        base_inc = (0.08 * (x ** -1) * (1.0 - 24.0 * (x ** -1) * ((x / 6.0) ** 2))) ** 0.25

        spike_mask = delta_times < 1e-9
        body_mask = ~spike_mask
        delta_b = 0.001 * delta_times[body_mask]
        b_val = _stream_booster_daniel_vec(delta_b)
        # 两分支整体求值后由 where 选取；未选中分支的内层式可能为负，
        # 幂运算产生 NaN 属预期，用 errstate 抑制告警。
        with np.errstate(invalid="ignore"):
            inc = np.where(
                delta_b < (2.0 * x) / 3.0,
                (delta_b ** -1)
                * (0.08 * (x ** -1) * (1.0 - 24.0 * (x ** -1) * ((delta_b - x / 2.0) ** 2))) ** 0.25,
                (delta_b ** -1) * base_inc,
            )
        inc = inc * np.maximum(b_val, 1.0)

        li_b = lis[body_mask]
        ri_b = ris[body_mask]
        inc_b = inc
        spike_l = lis[spike_mask]
        spike_r = ris_right[spike_mask]
        spike_val = 1000.0 * (0.02 * (4.0 / x - 24.0)) ** 0.25

        # 按基线的音符顺序逐段累加（保持浮点累加次序一致）。
        bi = 0
        si = 0
        for i in range(len(note_seq) - 1):
            if spike_mask[i]:
                left_idx = spike_l[si]
                right_idx = spike_r[si]
                si += 1
                if right_idx > left_idx:
                    P_step[left_idx:right_idx] += spike_val
                continue
            left_idx = li_b[bi]
            right_idx = ri_b[bi]
            inc_i = inc_b[bi]
            bi += 1
            if right_idx <= left_idx:
                continue
            seg_anchor = anchor[left_idx:right_idx]
            P_step[left_idx:right_idx] += np.minimum(
                inc_i * seg_anchor, np.maximum(inc_i, inc_i * 2.0 - 10.0)
            )

    return _smooth_on_corners(base_corners, P_step, window=500.0, scale=0.001, mode="sum")


def _compute_abar(
    K: int, key_usage: dict[int, np.ndarray], delta_ks: dict[int, np.ndarray],
    a_corners: np.ndarray, base_corners: np.ndarray
) -> np.ndarray:
    bc = np.asarray(base_corners, dtype=float)
    n = len(bc)
    dks = np.zeros((max(K - 1, 0), n))
    ku = (
        np.stack([key_usage[k] for k in range(K)], axis=0)
        if K > 0
        else np.zeros((0, n), dtype=bool)
    ).astype(bool)

    dk_rows = [delta_ks[k] for k in range(K)]
    # 前缀计数差分定位"相邻活跃列对"：严格介于 a、b 之间的活跃列数 = cnt[b-1] - cnt[a]。
    # ku 形状为 (列, 角点)，沿列轴（axis=0）累计每角点的活跃列数。
    cnt = np.cumsum(ku, axis=0, dtype=np.int32)

    for a in range(K - 1):
        for b in range(a + 1, K):
            mask = ku[a] & ku[b] & ((cnt[b - 1] - cnt[a]) == 0)
            if not np.any(mask):
                continue
            dka = dk_rows[a][mask]
            dkb = dk_rows[b][mask]
            dks[a][mask] = np.abs(dka - dkb) + 0.4 * np.maximum(
                0.0, np.maximum(dka, dkb) - 0.11
            )

    a_corners = np.asarray(a_corners, dtype=float)
    idx_arr = np.clip(np.searchsorted(bc, a_corners, side="left"), 0, n - 1)
    ku_A = ku[:, idx_arr]
    dkA = (
        np.stack([dk_rows[k][idx_arr] for k in range(K)], axis=0)
        if K > 0
        else np.zeros((0, len(a_corners)))
    )
    dksA = (
        np.stack([dks[k][idx_arr] for k in range(max(K - 1, 0))], axis=0)
        if K > 1
        else np.zeros((max(K - 1, 0), len(a_corners)))
    )
    cnt_A = cnt[:, idx_arr]

    A_step = np.ones(len(a_corners))
    for a in range(K - 1):
        for b in range(a + 1, K):
            mask = ku_A[a] & ku_A[b] & ((cnt_A[b - 1] - cnt_A[a]) == 0)
            if not np.any(mask):
                continue
            d_val = dksA[a][mask]
            mx = np.maximum(dkA[a][mask], dkA[b][mask])
            factor = np.where(
                d_val < 0.02,
                np.minimum(0.75 + 0.5 * mx, 1.0),
                np.where(d_val < 0.07, np.minimum(0.65 + 5.0 * d_val + 0.5 * mx, 1.0), 1.0),
            )
            A_step[mask] *= factor

    return _smooth_on_corners(a_corners, A_step, window=250.0, scale=1.0, mode="avg")


def _compute_c_and_ks(
    K: int, note_seq: list, key_usage: dict[int, np.ndarray], base_corners: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    note_hit_times = np.array(sorted(n[1] for n in note_seq), dtype=float)

    lo = np.searchsorted(note_hit_times, base_corners - 500.0, side="left")
    hi = np.searchsorted(note_hit_times, base_corners + 500.0, side="left")
    C_step = (hi - lo).astype(np.float64)

    usage_stack = np.stack([key_usage[k].astype(np.float64) for k in range(K)], axis=0)
    Ks_step = np.maximum(usage_stack.sum(axis=0), 1.0)

    return C_step, Ks_step


# ═══════════════════════════════════════════════════════════════════
# Graph smoothing (only needed for graph output)
# ═══════════════════════════════════════════════════════════════════

def _apply_proximity_envelope(
    all_corners: np.ndarray, D_all: np.ndarray, note_seq: list
) -> list[float]:
    if not note_seq:
        return list(D_all)

    note_times = np.array(sorted(n[1] for n in note_seq), dtype=float)
    if len(note_times) == 0:
        return list(D_all)

    proximity_fade_ms = 500.0
    out = np.zeros(len(all_corners))
    for i in range(len(all_corners)):
        t = float(all_corners[i])
        idx = _bisect_left(note_times, t)
        after = abs(float(note_times[idx]) - t) if idx < len(note_times) else float("inf")
        before = abs(float(note_times[idx - 1]) - t) if idx > 0 else float("inf")
        d = min(after, before)
        ratio = max(0.0, min(d / proximity_fade_ms, 1.0))
        envelope = 0.5 * (1.0 + math.cos(math.pi * ratio))
        out[i] = D_all[i] * envelope
    return list(out)


def _smooth_d_for_graph(
    all_corners: np.ndarray, D_all: np.ndarray, note_seq: list
) -> list[float]:
    if len(all_corners) == 0 or len(D_all) == 0:
        return []

    t_start = float(all_corners[0])
    t_end = float(all_corners[-1])
    uniform_times = []
    t = t_start
    while t <= t_end + GRAPH_RESAMPLE_INTERVAL_MS:
        uniform_times.append(t)
        t += GRAPH_RESAMPLE_INTERVAL_MS
    uniform_x = np.array(uniform_times, dtype=float)

    note_times = np.array(sorted(n[1] for n in note_seq), dtype=float)

    uniform_d = _interp_values(uniform_x, all_corners, D_all)

    if len(note_times) > 0:
        for i in range(len(uniform_times)):
            t_val = float(uniform_times[i])
            idx = _bisect_left(note_times, t_val)
            after = abs(float(note_times[idx]) - t_val) if idx < len(note_times) else float("inf")
            before = abs(float(note_times[idx - 1]) - t_val) if idx > 0 else float("inf")
            dist = min(after, before)
            if dist > BREAK_ZERO_THRESHOLD_MS:
                uniform_d[i] = 0.0

    sigma_samples = SMOOTH_SIGMA_MS / GRAPH_RESAMPLE_INTERVAL_MS
    smoothed = _gaussian_filter_1d(list(uniform_d), sigma_samples)

    if len(note_times) > 0:
        for i in range(len(uniform_times)):
            t_val = float(uniform_times[i])
            idx = _bisect_left(note_times, t_val)
            after = abs(float(note_times[idx]) - t_val) if idx < len(note_times) else float("inf")
            before = abs(float(note_times[idx - 1]) - t_val) if idx > 0 else float("inf")
            dist = min(after, before)
            if dist > BREAK_ZERO_THRESHOLD_MS:
                smoothed[i] = 0.0

    return list(_interp_values(all_corners, uniform_x, np.array(smoothed, dtype=float)))


# ═══════════════════════════════════════════════════════════════════
# Main calculateDaniel entry point
# ═══════════════════════════════════════════════════════════════════

def calculate_daniel(
    source: Any, speed_rate: float = 1.0, od_flag: Any = None, with_graph: bool = False,
    *, chart: Any = None,
):
    """calculateDaniel(osuText, speedRate, odFlag, {withGraph})."""
    path = source
    if isinstance(source, Path):
        path = str(source)

    pre = _preprocess_daniel(str(path), speed_rate, chart=chart)

    status = pre["status"]
    if status == "Fail":
        return -1
    if status == "NotMania":
        return -2
    if status == "UnsupportedKeys":
        return -3

    x = pre["x"]
    K = pre["K"]
    T = pre["T"]
    note_seq = pre["noteSeq"]
    note_seq_by_column = pre["noteSeqByColumn"]
    ln_ratio = pre["lnRatio"]
    column_count = pre["columnCount"]

    if not note_seq or K <= 0 or T <= 0:
        return -1

    all_corners, base_corners, a_corners = _get_corners(T, note_seq)

    key_usage = _get_key_usage(K, T, note_seq, base_corners)

    key_usage_400 = _get_key_usage_400(K, note_seq, base_corners)
    anchor = _compute_anchor(K, key_usage_400, base_corners)

    delta_ks, Jbar_base = _compute_jbar(K, x, note_seq_by_column, base_corners)
    Jbar = _interp_values(all_corners, base_corners, Jbar_base)

    Xbar_base = _compute_xbar(K, x, note_seq_by_column, key_usage, base_corners)
    Xbar = _interp_values(all_corners, base_corners, Xbar_base)

    Pbar_base = _compute_pbar(x, note_seq, anchor, base_corners)
    Pbar = _interp_values(all_corners, base_corners, Pbar_base)

    Abar_base = _compute_abar(K, key_usage, delta_ks, a_corners, base_corners)
    Abar = _interp_values(all_corners, a_corners, Abar_base)

    C_step, Ks_step = _compute_c_and_ks(K, note_seq, key_usage, base_corners)
    C_arr = _step_interp(all_corners, base_corners, C_step)
    Ks_arr = _step_interp(all_corners, base_corners, Ks_step)

    # D_all computation（向量化，替代逐角点 Python 循环）
    left_part = 0.4 * ((Abar ** (3.0 / Ks_arr) * np.minimum(Jbar, 8.0 + 0.85 * Jbar)) ** 1.5)
    right_part = 0.6 * ((Abar ** (2.0 / 3.0) * (0.8 * Pbar)) ** 1.5)
    S_all = (left_part + right_part) ** (2.0 / 3.0)
    T_all = (Abar ** (3.0 / Ks_arr) * Xbar) / (Xbar + S_all + 1.0)
    D_all = 2.7 * (S_all ** 0.5) * (T_all ** 1.5) + S_all * 0.27

    # Gaps and weighted percentiles
    gaps = np.empty(len(all_corners))
    gaps[0] = (all_corners[1] - all_corners[0]) / 2.0
    gaps[-1] = (all_corners[-1] - all_corners[-2]) / 2.0
    gaps[1:-1] = (all_corners[2:] - all_corners[:-2]) / 2.0

    effective_weights = C_arr * gaps
    sorted_indices = np.argsort(D_all)
    D_sorted = D_all[sorted_indices]
    w_sorted = effective_weights[sorted_indices]

    cum_weights = np.cumsum(w_sorted)
    total_weight = cum_weights[-1]

    if not math.isfinite(total_weight) or total_weight <= 0:
        if with_graph:
            return {
                "star": 0.0,
                "lnRatio": ln_ratio,
                "columnCount": column_count,
                "graph": {"times": list(all_corners), "values": [0.0] * len(all_corners)},
            }
        return [0.0, ln_ratio, column_count]

    norm_cum_weights = cum_weights / total_weight
    target_percentiles = np.array([0.945, 0.935, 0.925, 0.915, 0.845, 0.835, 0.825, 0.815])
    percentile_indices = np.searchsorted(norm_cum_weights, target_percentiles, side="left")
    clamped_indices = np.minimum(percentile_indices, len(D_sorted) - 1)

    first_group = D_sorted[clamped_indices[:4]]
    second_group = D_sorted[clamped_indices[4:8]]

    percentile_93 = float(np.mean(first_group))
    percentile_83 = float(np.mean(second_group))

    num = np.sum(D_sorted ** 5 * w_sorted)
    den = np.sum(w_sorted)
    weighted_mean = (num / max(den, 1e-9)) ** 0.2

    sr = (0.88 * percentile_93) * 0.25 + (0.94 * percentile_83) * 0.2 + weighted_mean * 0.55
    sr *= len(note_seq) / (len(note_seq) + 60)
    sr = _rescale_high(sr) * 0.975

    if with_graph:
        D_pre = _apply_proximity_envelope(all_corners, D_all, note_seq)
        D_graph = _smooth_d_for_graph(all_corners, np.array(D_pre), note_seq)
        return {
            "star": float(sr),
            "lnRatio": float(ln_ratio),
            "columnCount": int(column_count),
            "graph": {"times": list(all_corners), "values": D_graph},
        }

    return [float(sr), float(ln_ratio), int(column_count)]
