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


def _smooth_on_corners(
    x: np.ndarray, f: np.ndarray, window: float, scale: float = 1.0, mode: str = "sum"
) -> np.ndarray:
    F = _cumulative_sum(x, f)
    g = np.zeros(len(x), dtype=np.float64)
    a = np.clip(x - window, x[0], x[-1])
    b = np.clip(x + window, x[0], x[-1])
    # Vectorized queryCumsum
    val = np.array([_query_cumsum(b[i], x, F, f) - _query_cumsum(a[i], x, F, f) for i in range(len(x))])
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
    file_path: str, speed_rate: float
) -> dict[str, Any]:
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
    key_usage: dict[int, np.ndarray] = {k: np.zeros(len(base_corners), dtype=np.uint8) for k in range(K)}
    for k, h in note_seq:
        start_time = max(h - 150, 0)
        end_time = min(h + 150, T - 1)
        left_idx = _bisect_left(base_corners, start_time)
        right_idx = _bisect_left(base_corners, end_time)
        key_usage[k][left_idx:right_idx] = 1
    return key_usage


def _get_key_usage_400(
    K: int, note_seq: list, base_corners: np.ndarray
) -> dict[int, np.ndarray]:
    key_usage_400: dict[int, np.ndarray] = {k: np.zeros(len(base_corners), dtype=np.float64) for k in range(K)}
    for k, h in note_seq:
        left400_idx = _bisect_left(base_corners, h - 400)
        center_idx = _bisect_left(base_corners, h)
        right400_idx = _bisect_left(base_corners, h + 400)

        if 0 <= center_idx < len(base_corners):
            key_usage_400[k][center_idx] += 3.75

        for idx in range(left400_idx, center_idx):
            offset = float(base_corners[idx]) - float(h)
            key_usage_400[k][idx] += 3.75 - (3.75 / (400 * 400)) * (offset * offset)

        for idx in range(center_idx + 1, right400_idx):
            offset = float(base_corners[idx]) - float(h)
            key_usage_400[k][idx] += 3.75 - (3.75 / (400 * 400)) * (offset * offset)

    return key_usage_400


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
    J_ks: dict[int, np.ndarray] = {k: np.zeros(len(base_corners)) for k in range(K)}
    delta_ks: dict[int, np.ndarray] = {k: np.full(len(base_corners), 1e9) for k in range(K)}

    for k in range(K):
        notes = note_seq_by_column[k]
        if len(notes) < 2:
            continue
        for i in range(len(notes) - 1):
            start = notes[i][1]
            end = notes[i + 1][1]
            if end <= start:
                continue
            left_idx = _bisect_left(base_corners, start)
            right_idx = _bisect_left(base_corners, end)
            if left_idx >= right_idx:
                continue
            delta = 0.001 * (end - start)
            val = (delta ** -1) * ((delta + 0.11 * (x ** 0.25)) ** -1) * _jack_nerfer(delta)
            J_ks[k][left_idx:right_idx] = val
            delta_ks[k][left_idx:right_idx] = delta

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
    K: int, x: float, note_seq_by_column: list, active_columns: list, base_corners: np.ndarray
) -> np.ndarray:
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

        for i in range(1, len(notes_in_pair)):
            start = notes_in_pair[i - 1][1]
            end = notes_in_pair[i][1]
            if end <= start:
                continue
            left_idx = _bisect_left(base_corners, start)
            right_idx = _bisect_left(base_corners, end)
            if right_idx <= left_idx:
                continue

            delta = 0.001 * (end - start)
            val = 0.16 * (max(x, delta) ** -2)

            left_inactive = (k - 1) not in active_columns[left_idx] and (k - 1) not in active_columns[right_idx]
            right_inactive = k not in active_columns[left_idx] and k not in active_columns[right_idx]

            if left_inactive or right_inactive:
                val *= 1.0 - cross_coeff[k]

            fast_val = max(0.0, 0.4 * (max(delta, 0.06, 0.75 * x) ** -2) - 80.0)

            X_ks[k][left_idx:right_idx] = val
            fast_cross[k][left_idx:right_idx] = fast_val

    X_base = np.zeros(len(base_corners))
    for i in range(len(base_corners)):
        sum1 = sum(X_ks[k][i] * cross_coeff[k] for k in range(K + 1))
        sum2 = 0.0
        for k in range(K):
            pair = fast_cross[k][i] * cross_coeff[k] * fast_cross[k + 1][i] * cross_coeff[k + 1]
            if pair > 0:
                sum2 += math.sqrt(pair)
        X_base[i] = sum1 + sum2

    return _smooth_on_corners(base_corners, X_base, window=500.0, scale=0.001, mode="sum")


def _stream_booster_daniel(delta: float) -> float:
    """Daniel-specific sigmoid-based stream booster."""
    bpm = max(0.0, min(7.5 / max(delta, 1e-9), 420.0))
    primary = 0.10 / (1.0 + math.exp(-0.06 * (bpm - 175.0)))
    secondary = 0.30 * (1.0 - math.exp(-0.02 * (bpm - 200.0))) if (200.0 <= bpm <= 350.0) else 0.0
    return 1.0 + primary + secondary


def _compute_pbar(
    x: float, note_seq: list, anchor: np.ndarray, base_corners: np.ndarray
) -> np.ndarray:
    P_step = np.zeros(len(base_corners))

    for i in range(len(note_seq) - 1):
        h_l = note_seq[i][1]
        h_r = note_seq[i + 1][1]
        delta_time = h_r - h_l

        if delta_time < 1e-9:
            spike = 1000.0 * (0.02 * (4.0 / x - 24.0)) ** 0.25
            left_idx = _bisect_left(base_corners, h_l)
            right_idx = _bisect_right(base_corners, h_l)
            P_step[left_idx:right_idx] += spike
            continue

        left_idx = _bisect_left(base_corners, h_l)
        right_idx = _bisect_left(base_corners, h_r)
        if right_idx <= left_idx:
            continue

        delta = 0.001 * delta_time
        b_val = _stream_booster_daniel(delta)
        base_inc = (0.08 * (x ** -1) * (1.0 - 24.0 * (x ** -1) * ((x / 6.0) ** 2))) ** 0.25

        if delta < (2.0 * x) / 3.0:
            inc = (delta ** -1) * (0.08 * (x ** -1) * (1.0 - 24.0 * (x ** -1) * ((delta - x / 2.0) ** 2))) ** 0.25 * max(b_val, 1.0)
        else:
            inc = (delta ** -1) * base_inc * max(b_val, 1.0)

        seg_anchor = anchor[left_idx:right_idx]
        P_step[left_idx:right_idx] += np.minimum(inc * seg_anchor, np.maximum(inc, inc * 2.0 - 10.0))

    return _smooth_on_corners(base_corners, P_step, window=500.0, scale=0.001, mode="sum")


def _compute_abar(
    K: int, active_columns: list, delta_ks: dict[int, np.ndarray],
    a_corners: np.ndarray, base_corners: np.ndarray
) -> np.ndarray:
    dks: dict[int, np.ndarray] = {k: np.zeros(len(base_corners)) for k in range(K - 1)}

    for i in range(len(base_corners)):
        cols = active_columns[i]
        for j in range(len(cols) - 1):
            k0 = cols[j]
            k1 = cols[j + 1]
            dks[k0][i] = abs(delta_ks[k0][i] - delta_ks[k1][i]) + 0.4 * max(0.0, max(delta_ks[k0][i], delta_ks[k1][i]) - 0.11)

    A_step = np.ones(len(a_corners))

    for i in range(len(a_corners)):
        idx = _bisect_left(base_corners, float(a_corners[i]))
        idx = max(0, min(idx, len(base_corners) - 1))
        cols = active_columns[idx]
        for j in range(len(cols) - 1):
            k0 = cols[j]
            k1 = cols[j + 1]
            d_val = dks[k0][idx]
            dk0 = delta_ks[k0][idx]
            dk1 = delta_ks[k1][idx]
            if d_val < 0.02:
                A_step[i] *= min(0.75 + 0.5 * max(dk0, dk1), 1.0)
            elif d_val < 0.07:
                A_step[i] *= min(0.65 + 5.0 * d_val + 0.5 * max(dk0, dk1), 1.0)

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
    source: Any, speed_rate: float = 1.0, od_flag: Any = None, with_graph: bool = False
):
    """calculateDaniel(osuText, speedRate, odFlag, {withGraph})."""
    path = source
    if isinstance(source, Path):
        path = str(source)

    pre = _preprocess_daniel(str(path), speed_rate)

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
    active_columns = [[k for k in range(K) if key_usage[k][i]] for i in range(len(base_corners))]

    key_usage_400 = _get_key_usage_400(K, note_seq, base_corners)
    anchor = _compute_anchor(K, key_usage_400, base_corners)

    delta_ks, Jbar_base = _compute_jbar(K, x, note_seq_by_column, base_corners)
    Jbar = _interp_values(all_corners, base_corners, Jbar_base)

    Xbar_base = _compute_xbar(K, x, note_seq_by_column, active_columns, base_corners)
    Xbar = _interp_values(all_corners, base_corners, Xbar_base)

    Pbar_base = _compute_pbar(x, note_seq, anchor, base_corners)
    Pbar = _interp_values(all_corners, base_corners, Pbar_base)

    Abar_base = _compute_abar(K, active_columns, delta_ks, a_corners, base_corners)
    Abar = _interp_values(all_corners, a_corners, Abar_base)

    C_step, Ks_step = _compute_c_and_ks(K, note_seq, key_usage, base_corners)
    C_arr = _step_interp(all_corners, base_corners, C_step)
    Ks_arr = _step_interp(all_corners, base_corners, Ks_step)

    # D_all computation
    D_all = np.zeros(len(all_corners))
    for i in range(len(all_corners)):
        left_part = 0.4 * ((Abar[i] ** (3.0 / Ks_arr[i]) * min(Jbar[i], 8.0 + 0.85 * Jbar[i])) ** 1.5)
        right_part = 0.6 * ((Abar[i] ** (2.0 / 3.0) * (0.8 * Pbar[i])) ** 1.5)
        S_all = (left_part + right_part) ** (2.0 / 3.0)
        T_all = (Abar[i] ** (3.0 / Ks_arr[i]) * Xbar[i]) / (Xbar[i] + S_all + 1.0)
        D_all[i] = 2.7 * (S_all ** 0.5) * (T_all ** 1.5) + S_all * 0.27

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
