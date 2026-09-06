"""
该文件来源于 https://github.com/sunnyxxy/Star-Rating-Rebirth/blob/main/algorithm.py
为适配功能做了一些改动，并应用了向量化优化。

向量化手法（批量 np.searchsorted / np.add.at / X_base 广播求和 / Abar 前缀计数差分 /
Pbar 平铺 bincount 累加）移植自 Dan-Overlay 3.1.0 (MIT) 的 sr_core/algorithm.py，
LN/Rbar/speed_rate/od/cvt 语义与原实现逐位一致。
"""

from __future__ import annotations

import math
import bisect
from collections import defaultdict

import numpy as np

from ...parser.osu_file_parser import osu_file

# ===== 辅助函数 =====


def cumulative_sum(x, f):
    """
    summary:
        计算分段常量函数的累计积分前缀。
    Args:
        x: 排序后的分段点。
        f: 各区间上的函数值。
    Returns:
        累计积分数组。
    """
    F = np.zeros(len(x))
    F[1:] = np.cumsum(f[:-1] * np.diff(x))
    return F


def query_cumsum_vec(q_arr, x, F, f):
    """summary: 在任意查询点上返回累计积分值。"""
    idx = np.searchsorted(x, q_arr) - 1
    idx = np.clip(idx, 0, len(x) - 2)
    return F[idx] + f[idx] * (q_arr - x[idx])


def smooth_on_corners(x, f, window, scale=1.0, mode="sum"):
    """
    summary:
        计算分段常量函数在滑动窗口上的积分或平均值。
    Args:
        x: 采样点。
        f: 对应函数值。
        window: 窗口半宽。
        scale: 积分缩放系数。
        mode: sum 返回积分，avg 返回平均值。
    Returns:
        平滑后的数组。
    """
    x = np.asarray(x, dtype=float)
    f = np.asarray(f, dtype=float)
    F = cumulative_sum(x, f)

    a = np.clip(x - window, x[0], x[-1])
    b = np.clip(x + window, x[0], x[-1])

    val = query_cumsum_vec(b, x, F, f) - query_cumsum_vec(a, x, F, f)

    if mode == "avg":
        span = b - a
        return np.where(span > 0, val / span, 0.0)
    return scale * val


def interp_values(new_x, old_x, old_vals):
    """summary: 通过线性插值计算新位置的值。"""
    return np.interp(new_x, old_x, old_vals)


def step_interp(new_x, old_x, old_vals):
    """
    summary:
        对每个查询点返回其左侧最近采样点的值（严格小于语义）。
    Args:
        new_x: 新查询点。
        old_x: 原始采样点。
        old_vals: 原始采样值。
    Returns:
        零阶保持插值结果（精确命中取前一个采样；daniel 用 side='right' 勿混）。
    """
    # side='left' 给出第一个 >= new_x 的插入位；减一即"最后一个严格小于 new_x"的元素。
    indices = np.searchsorted(old_x, new_x, side="left") - 1
    indices = np.clip(indices, 0, len(old_vals) - 1)
    return old_vals[indices]


def rescale_high(sr):
    if sr <= 9:
        return sr
    return 9 + (sr - 9) * (1 / 1.2)


def find_next_note_in_column(note, times, note_seq_by_column):
    k, h, t = note
    idx = bisect.bisect_left(times, h)
    return (
        note_seq_by_column[k][idx + 1]
        if idx + 1 < len(note_seq_by_column[k])
        else (0, 10**9, 10**9)
    )


def stream_booster_vec(deltas):
    """summary: 原始 stream_booster 的向量化版本（对 delta 数组整体求值）。"""
    bpm = 7.5 / deltas
    inside = (bpm > 160) & (bpm < 360)
    return np.where(inside, 1 + 1.7e-7 * (bpm - 160) * (bpm - 360) ** 2, 1.0)


# ===== 预处理 =====


def preprocess_file(file_path, speed_rate, od_flag, cvt_flag, *, chart=None):
    # chart 非 None 时跳过解析；IN/HO 会改写物件结构，故防御性 clone。
    if chart is not None:
        p_obj = chart.clone()
    else:
        p_obj = osu_file(file_path)
        p_obj.process()
    p = p_obj.get_parsed_data()
    LN_ratio = p[8]
    if cvt_flag:
        if "IN" in cvt_flag:
            try:
                p_obj.mod_IN()
                LN_ratio = p_obj.get_LN_ratio()
            except Exception:
                pass
        if "HO" in cvt_flag:
            try:
                p_obj.mod_HO()
                LN_ratio = p_obj.get_LN_ratio()
            except Exception:
                pass

    # IN/HO 改写了物件结构，后续计算必须读取更新后的快照
    p_obj.note_times = p_obj.get_note_times()
    p_obj.object_intervals = p_obj.get_object_intervals()
    p = p_obj.get_parsed_data()
    LN_ratio = p_obj.get_LN_ratio()

    column_count = p_obj.get_column_count()

    if p[7] == "Fail":
        return "Fail", 0, 0, 0, [], [], [], [], [], LN_ratio, column_count
    if p[7] == "NotMania":
        return "NotMania", 0, 0, 0, [], [], [], [], [], LN_ratio, column_count

    match od_flag:
        case None:
            od = p[5]
        case "HR":
            od = 6.462 + 0.715 * p[5]
        case "EZ":
            od = -20.761 + 2.566 * p[5]
        case _:
            od = float(od_flag)
    time_scale = 1.0 / speed_rate if speed_rate != 0 else 1.0

    # 将 note_seq 构建为 (列, 起始时间, 结束时间) 的元组列表
    note_seq = []
    for i in range(len(p[1])):
        k = p[1][i]
        h = p[2][i]
        # note_type bit 7 表示 LN；其余情况下视作普通 note。
        t = p[3][i] if (p[4][i] & 128) != 0 else -1
        h = int(math.floor(h * time_scale))
        t = int(math.floor(t * time_scale)) if t >= 0 else t
        note_seq.append((k, h, t))

    # 命中容错 x
    x = 0.3 * ((64.5 - math.ceil(od * 3)) / 500) ** 0.5
    x = min(x, 0.6 * (x - 0.09) + 0.09)
    note_seq.sort(key=lambda tup: (tup[1], tup[0]))
    # js preprocessFile：排序后 shift() 丢掉最早音符，再构建全部派生结构。
    if note_seq:
        note_seq = note_seq[1:]

    # 空谱面（含垃圾文件被解析成 0 物件）直接返回，由 calculate 兜底为 -1；
    # 否则下方 T 的 max() 会对空序列崩溃。
    if not note_seq:
        return "OK", x, 0, 1, [], [], [], [], [], LN_ratio, column_count

    # 按列分组
    note_dict = defaultdict(list)
    for tup in note_seq:
        note_dict[tup[0]].append(tup)
    note_seq_by_column = sorted(list(note_dict.values()), key=lambda lst: lst[0][0])

    # 长按（LN）是指存在尾点（t >= 0）的物件
    LN_seq = [n for n in note_seq if n[2] >= 0]
    tail_seq = sorted(LN_seq, key=lambda tup: tup[2])

    LN_dict = defaultdict(list)
    for tup in LN_seq:
        LN_dict[tup[0]].append(tup)
    LN_seq_by_column = sorted(list(LN_dict.values()), key=lambda lst: lst[0][0])

    K = p[0]
    T = max(max(n[1] for n in note_seq), max(n[2] for n in note_seq)) + 1

    status = "OK"
    return (
        status,
        x,
        K,
        T,
        note_seq,
        note_seq_by_column,
        LN_seq,
        tail_seq,
        LN_seq_by_column,
        LN_ratio,
        column_count,
    )


def get_corners(T, note_seq):
    corners_base = set()
    for _, h, t in note_seq:
        corners_base.add(h)
        if t >= 0:
            corners_base.add(t)
    for s in list(corners_base):
        corners_base.add(s + 501)
        corners_base.add(s - 499)
        corners_base.add(s + 1)  # 用于精确处理 note 位置处的 Dirac-Delta 增量
    corners_base.add(0)
    corners_base.add(T)
    corners_base = sorted(s for s in corners_base if 0 <= s <= T)

    # 对 Abar 来说，未平滑值（KU 和 A）通常会在 note 边界前后 ±500 处变化，因此整体需要扩展到 ±1000。
    corners_A = set()
    for _, h, t in note_seq:
        corners_A.add(h)
        if t >= 0:
            corners_A.add(t)
    for s in list(corners_A):
        corners_A.add(s + 1000)
        corners_A.add(s - 1000)
    corners_A.add(0)
    corners_A.add(T)
    corners_A = sorted(s for s in corners_A if 0 <= s <= T)

    # 最终取所有角点的并集用于插值
    all_corners = sorted(set(corners_base) | set(corners_A))
    all_corners = np.array(all_corners, dtype=float)
    base_corners = np.array(corners_base, dtype=float)
    A_corners = np.array(corners_A, dtype=float)
    return all_corners, base_corners, A_corners


# ===== 向量化：key_usage =====


def get_key_usage(K, T, note_seq, base_corners):
    """区间标记的差分 + 前缀和实现：批量 searchsorted 一次定位全部区间端点。"""
    bc = np.asarray(base_corners, dtype=float)
    n = len(bc)
    if not note_seq or K <= 0:
        return {k: np.zeros(n, dtype=bool) for k in range(K)}
    m = len(note_seq)
    ks = np.fromiter((k for (k, h, t) in note_seq), dtype=np.int64, count=m)
    hs = np.fromiter((h for (k, h, t) in note_seq), dtype=float, count=m)
    ts = np.fromiter((t for (k, h, t) in note_seq), dtype=float, count=m)
    is_normal = ts < 0
    # 基线语义：普通音符 endTime = h+150（不钳位，越界交给切片截断）；
    # 仅 LN 尾点 endTime = min(t+150, T-1)。
    starts = np.maximum(hs - 150.0, 0.0)
    ends = np.where(is_normal, hs + 150.0, np.minimum(ts + 150.0, float(T) - 1.0))
    lis = np.searchsorted(bc, starts, side="left")
    ris = np.searchsorted(bc, ends, side="left")
    # 末列多留一格承接 ris == n 的差分，随后裁掉。
    diff = np.zeros((K, n + 1), dtype=np.int32)
    np.add.at(diff, (ks, np.minimum(lis, n)), 1)
    np.add.at(diff, (ks, np.minimum(ris, n)), -1)
    usage2d = np.cumsum(diff, axis=1)[:, :n] > 0
    return {k: usage2d[k] for k in range(K)}


def get_key_usage_400(K, T, note_seq, base_corners):
    """批量 searchsorted 后按音符做纯切片累加，消除逐音符标量 searchsorted。"""
    bc = np.asarray(base_corners, dtype=float)
    n = len(bc)
    arr = np.zeros((K, n), dtype=float)
    inv_400_sq = 3.75 / 400**2
    if not note_seq or K <= 0:
        return {k: arr[k] for k in range(K)}
    m = len(note_seq)
    ks = np.fromiter((k for (k, h, t) in note_seq), dtype=np.int64, count=m)
    starts = np.fromiter((max(h, 0) for (k, h, t) in note_seq), dtype=float, count=m)
    ends = np.fromiter(
        ((h if t < 0 else min(t, T - 1)) for (k, h, t) in note_seq), dtype=float, count=m
    )
    lis = np.searchsorted(bc, starts - 400.0, side="left")
    mids = np.searchsorted(bc, starts, side="left")
    ris = np.searchsorted(bc, ends, side="left")
    r400s = np.searchsorted(bc, ends + 400.0, side="left")

    for i in range(m):
        li = lis[i]
        mid = mids[i]
        ri = ris[i]
        r4 = r400s[i]
        row = arr[ks[i]]
        st = starts[i]
        en = ends[i]
        if ri > mid:
            # LN 主体区间
            row[mid:ri] += 3.75 + min(en - st, 1500.0) / 150.0
        if mid > li:
            seg = bc[li:mid]
            row[li:mid] += 3.75 - inv_400_sq * (seg - st) ** 2
        if r4 > ri:
            seg = bc[ri:r4]
            row[ri:r4] += 3.75 - inv_400_sq * (seg - en) ** 2
    return {k: arr[k] for k in range(K)}


def compute_anchor(K, key_usage_400, base_corners):
    # 向量化计算 anchor
    counts = np.stack([key_usage_400[k] for k in range(K)], axis=1)
    counts_sorted = np.sort(counts, axis=1)[:, ::-1]  # 每行按降序排列

    nonzero_mask = counts_sorted > 0
    n_nz = nonzero_mask.sum(axis=1)

    # 为 walk 计算做准备
    c0 = counts_sorted[:, :-1]
    c1 = counts_sorted[:, 1:]
    safe_c0 = np.where(c0 > 0, c0, 1.0)
    ratio = np.where(c0 > 0, c1 / safe_c0, 0.0)
    weight = 1 - 4 * (0.5 - ratio) ** 2

    pair_valid = nonzero_mask[:, :-1] & nonzero_mask[:, 1:]
    walk = np.sum(np.where(pair_valid, c0 * weight, 0.0), axis=1)
    max_walk = np.sum(np.where(pair_valid, c0, 0.0), axis=1)

    raw_anchor = np.where(n_nz > 1, walk / np.maximum(max_walk, 1e-9), 0.0)
    anchor = 1 + np.minimum(raw_anchor - 0.18, 5 * (raw_anchor - 0.22) ** 3)
    return anchor


def LN_bodies_count_sparse_representation(LN_seq, T):
    diff = {}  # 字典：索引 -> LN_bodies 的变化量（转换前）

    for k, h, t in LN_seq:
        t0 = min(h + 60, t)
        t1 = min(h + 120, t)
        diff[t0] = diff.get(t0, 0) + 1.3
        diff[t1] = diff.get(t1, 0) + (-1.3 + 1)  # t1 的净变化：先减 1.3，再加 1
        diff[t] = diff.get(t, 0) - 1

    # 分段点是发生变化的时间点。
    points = sorted(set([0, T] + list(diff.keys())))

    # 构建分段常量值（转换后）及其前缀和。
    values = []
    cumsum = [0]  # 分段点处的累计和
    curr = 0.0

    for i in range(len(points) - 1):
        t = points[i]
        # 如果 t 处存在变化，则更新当前值。
        if t in diff:
            curr += diff[t]

        v = min(curr, 2.5 + 0.5 * curr)
        values.append(v)
        # 计算区间 [points[i], points[i+1]) 上的累计和
        seg_length = points[i + 1] - points[i]
        cumsum.append(cumsum[-1] + seg_length * v)
    return points, cumsum, values


def LN_sum_vec(a_arr, b_arr, LN_rep):
    """LN_sum 的向量化版本：对成对查询数组整体求 LN 主体积分。"""
    points, cumsum, values = LN_rep
    pts = np.asarray(points, dtype=float)
    cums = np.asarray(cumsum, dtype=float)
    vals = np.asarray(values, dtype=float)
    i_idx = np.searchsorted(pts, a_arr, side="right") - 1
    j_idx = np.searchsorted(pts, b_arr, side="right") - 1
    same = i_idx == j_idx
    same_val = (b_arr - a_arr) * vals[i_idx]
    diff_val = (
        (pts[i_idx + 1] - a_arr) * vals[i_idx]
        + (cums[j_idx] - cums[i_idx + 1])
        + (b_arr - pts[j_idx]) * vals[j_idx]
    )
    return np.where(same, same_val, diff_val)


def compute_Jbar(K, T, x, note_seq_by_column, base_corners):
    bc = np.asarray(base_corners, dtype=float)
    J_ks = {k: np.zeros(len(base_corners)) for k in range(K)}
    delta_ks = {k: np.full(len(base_corners), 1e9) for k in range(K)}

    for k in range(K):
        notes = note_seq_by_column[k]
        if len(notes) < 2:
            continue
        starts = np.array([n[1] for n in notes[:-1]], dtype=float)
        ends = np.array([n[1] for n in notes[1:]], dtype=float)
        deltas = 0.001 * (ends - starts)
        vals = (
            (deltas ** (-1))
            * (deltas + 0.11 * x**0.25) ** (-1)
            * (1 - 7e-5 * (0.15 + np.abs(deltas - 0.08)) ** (-4))
        )

        lis = np.searchsorted(bc, starts, side="left")
        ris = np.searchsorted(bc, ends, side="left")
        J_row = J_ks[k]
        d_row = delta_ks[k]
        for li, ri, delta, val in zip(lis, ris, deltas, vals):
            if ri > li:
                J_row[li:ri] = val
                d_row[li:ri] = delta

    Jbar_stack = np.stack(
        [
            smooth_on_corners(base_corners, J_ks[k], window=500, scale=0.001, mode="sum")
            for k in range(K)
        ],
        axis=0,
    )
    delta_stack = np.stack([delta_ks[k] for k in range(K)], axis=0)
    weights = 1.0 / delta_stack
    num = np.sum(np.maximum(Jbar_stack, 0) ** 5 * weights, axis=0)
    den = np.sum(weights, axis=0)
    Jbar = (num / np.maximum(den, 1e-9)) ** 0.2

    return delta_ks, Jbar


def compute_Xbar(K, T, x, note_seq_by_column, key_usage, base_corners):
    cross_matrix = [
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
    X_ks = {k: np.zeros(len(base_corners)) for k in range(K + 1)}
    fast_cross = {k: np.zeros(len(base_corners)) for k in range(K + 1)}
    cross_coeff = cross_matrix[K]
    bc = np.asarray(base_corners, dtype=float)

    for k in range(K + 1):
        if k == 0:
            notes_in_pair = note_seq_by_column[0]
        elif k == K:
            notes_in_pair = note_seq_by_column[K - 1]
        else:
            notes_in_pair = sorted(
                note_seq_by_column[k - 1] + note_seq_by_column[k], key=lambda t: t[1]
            )
        if len(notes_in_pair) < 2:
            continue
        starts = np.array([n[1] for n in notes_in_pair[:-1]], dtype=float)
        ends = np.array([n[1] for n in notes_in_pair[1:]], dtype=float)
        deltas = 0.001 * (ends - starts)
        vals = 0.16 * np.maximum(x, deltas) ** -2
        fc_vals = np.maximum(0, 0.4 * np.maximum(deltas, max(0.06, 0.75 * x)) ** -2 - 80)
        lis = np.searchsorted(bc, starts, side="left")
        ris = np.searchsorted(bc, ends, side="left")

        X_row = X_ks[k]
        fc_row = fast_cross[k]
        ku_left = key_usage[k - 1] if k >= 1 else None
        ku_right = key_usage[k] if 1 <= k < K else None
        for li, ri, val, fc in zip(lis, ris, vals, fc_vals):
            if ri <= li:
                continue
            # 基线语义：k==0 时 (k-1)=-1 永不在 active_columns → left 恒无效；
            # k==K 时 k 永不在 active_columns → right 恒无效。两者均恒缩放。
            if k == 0 or k == K:
                inactive = True
            else:
                left_inactive = (not ku_left[li]) and (not ku_left[ri])
                right_inactive = (not ku_right[li]) and (not ku_right[ri])
                inactive = left_inactive or right_inactive
            if inactive:
                val = val * (1 - cross_coeff[k])
            X_row[li:ri] = val
            fc_row[li:ri] = fc

    # X_base 广播求和：替代 O(角点×K) 的逐角点 Python 循环。
    X_ks_arr = np.stack([X_ks[k] for k in range(K + 1)], axis=0)
    coeff_arr = np.asarray(cross_coeff, dtype=float)[:, np.newaxis]
    X_base = np.sum(X_ks_arr * coeff_arr, axis=0)

    fc_arr = np.stack([fast_cross[k] for k in range(K + 1)], axis=0)
    cc = np.asarray(cross_coeff, dtype=float)
    X_base += np.sum(
        np.sqrt(fc_arr[:-1] * cc[:-1, np.newaxis] * fc_arr[1:] * cc[1:, np.newaxis]),
        axis=0,
    )

    return smooth_on_corners(base_corners, X_base, window=500, scale=0.001, mode="sum")


def _flat_cols(starts, lens):
    """把若干 [starts[i], starts[i]+lens[i]) 区间展开成一维平坦索引数组。"""
    total = int(lens.sum())
    idx_starts = np.repeat(starts, lens)
    offsets = np.arange(total) - np.repeat(np.cumsum(lens) - lens, lens)
    return idx_starts + offsets


def compute_Pbar(K, T, x, note_seq, LN_rep, anchor, base_corners):
    bc = np.asarray(base_corners, dtype=float)
    n = len(bc)
    P_step = np.zeros(n)

    if len(note_seq) > 1:
        hs = np.array([note[1] for note in note_seq], dtype=float)
        h_ls = hs[:-1]
        h_rs = hs[1:]
        delta_times = h_rs - h_ls
        lis = np.searchsorted(bc, h_ls, side="left")
        ris = np.searchsorted(bc, h_rs, side="left")

        # spike 分支（delta_time < 1e-9）：区间为精确命中 h_l 的角点。
        spike_mask = delta_times < 1e-9
        if np.any(spike_mask):
            spike_val = 1000 * (0.02 * (4 / x - 24)) ** 0.25
            lis_spike = lis[spike_mask]
            ris_spike = np.searchsorted(bc, h_ls[spike_mask], side="right")
            lens = np.maximum(ris_spike - lis_spike, 0)
            total = int(lens.sum())
            if total > 0:
                cols = _flat_cols(lis_spike, lens)
                P_step += np.bincount(
                    cols, weights=np.full(total, spike_val), minlength=n
                )

        body = (~spike_mask) & (ris > lis)
        if np.any(body):
            h_l_b = h_ls[body]
            li_b = lis[body]
            ri_b = ris[body]
            delta_b = 0.001 * delta_times[body]
            v_b = 1 + 6 * 0.001 * LN_sum_vec(h_l_b, h_rs[body], LN_rep)
            b_val = stream_booster_vec(delta_b)
            # 两分支整体求值后由 where 选取；未选中分支的内层式可能为负，
            # 幂运算产生 NaN 属预期，用 errstate 抑制告警。
            with np.errstate(invalid="ignore"):
                inc = np.where(
                    delta_b < 2 * x / 3,
                    delta_b ** (-1)
                    * (0.08 * x ** (-1) * (1 - 24 * x ** (-1) * (delta_b - x / 2) ** 2))
                    ** 0.25,
                    delta_b ** (-1)
                    * (0.08 * x ** (-1) * (1 - 24 * x ** (-1) * (x / 6) ** 2)) ** 0.25,
                )
            inc = inc * np.maximum(b_val, v_b)

            lens = ri_b - li_b
            cols = _flat_cols(li_b, lens)
            inc_rep = np.repeat(inc, lens)
            anchor_flat = anchor[cols]
            seg_vals = np.minimum(
                inc_rep * anchor_flat, np.maximum(inc_rep, inc_rep * 2 - 10)
            )
            P_step += np.bincount(cols, weights=seg_vals, minlength=n)

    return smooth_on_corners(base_corners, P_step, window=500, scale=0.001, mode="sum")


def compute_Abar(
    K, T, x, note_seq_by_column, key_usage, delta_ks, A_corners, base_corners
):
    bc = np.asarray(base_corners, dtype=float)
    n = len(bc)
    dks = np.zeros((max(K - 1, 0), n))
    ku = (
        np.stack([key_usage[k] for k in range(K)], axis=0)
        if K > 0
        else np.zeros((0, n), dtype=bool)
    )

    dk_rows = [delta_ks[k] for k in range(K)]
    # 前缀计数差分定位"相邻活跃列对"：严格介于 a、b 之间的活跃列数 = cnt[b-1] - cnt[a]
    # （计数可减；OR 前缀差分会把同时在 <=a 区间活跃的中间列误判为无，不可用）。
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
                0, np.maximum(dka, dkb) - 0.11
            )

    A_corners = np.asarray(A_corners, dtype=float)
    bc_idx = np.clip(np.searchsorted(bc, A_corners), 0, n - 1)
    ku_A = ku[:, bc_idx]  # (K, len(A_corners))
    dkA = (
        np.stack([dk_rows[k][bc_idx] for k in range(K)], axis=0)
        if K > 0
        else np.zeros((0, len(A_corners)))
    )
    dksA = (
        np.stack([dks[k][bc_idx] for k in range(max(K - 1, 0))], axis=0)
        if K > 1
        else np.zeros((max(K - 1, 0), len(A_corners)))
    )
    cnt_A = cnt[:, bc_idx]

    A_step = np.ones(len(A_corners))
    for a in range(K - 1):
        for b in range(a + 1, K):
            mask = ku_A[a] & ku_A[b] & ((cnt_A[b - 1] - cnt_A[a]) == 0)
            if not np.any(mask):
                continue
            d_val = dksA[a][mask]
            mx = np.maximum(dkA[a][mask], dkA[b][mask])
            factor = np.where(
                d_val < 0.02,
                np.minimum(0.75 + 0.5 * mx, 1),
                np.where(d_val < 0.07, np.minimum(0.65 + 5 * d_val + 0.5 * mx, 1), 1.0),
            )
            A_step[mask] *= factor

    return smooth_on_corners(A_corners, A_step, window=250, mode="avg")


def compute_Rbar(K, T, x, note_seq_by_column, tail_seq, base_corners):
    bc = np.asarray(base_corners, dtype=float)
    I_arr = np.zeros(len(base_corners))
    R_step = np.zeros(len(base_corners))

    times_by_column = {
        i: [note[1] for note in column] for i, column in enumerate(note_seq_by_column)
    }

    if len(tail_seq) > 0:
        # Release 指标：向量化 I 列表计算，保留逐尾点的二分定位。
        t_is = np.array([t[2] for t in tail_seq], dtype=float)
        h_j = np.empty(len(tail_seq))
        for i, (k, h_i, t_i) in enumerate(tail_seq):
            times = times_by_column[k]
            idx = bisect.bisect_left(times, h_i)
            h_j[i] = (
                note_seq_by_column[k][idx + 1][1]
                if idx + 1 < len(note_seq_by_column[k])
                else 10**9
            )
        I_h = (
            0.001
            * np.abs(t_is - np.array([t[1] for t in tail_seq], dtype=float) - 80)
            / x
        )
        I_t = 0.001 * np.abs(h_j - t_is - 80) / x
        I_list = 2 / (2 + np.exp(-5 * (I_h - 0.75)) + np.exp(-5 * (I_t - 0.75)))

        # 在相邻尾点之间的每个区间内，赋值 I 和 R。
        t_starts = t_is[:-1]
        t_ends = t_is[1:]
        lis = np.searchsorted(bc, t_starts, side="left")
        ris = np.searchsorted(bc, t_ends, side="left")
        for i in range(len(tail_seq) - 1):
            idx = np.arange(lis[i], ris[i])
            if len(idx) == 0:
                continue
            I_arr[idx] = 1 + I_list[i]
            delta_r = 0.001 * (t_ends[i] - t_starts[i])
            R_step[idx] = (
                0.08
                * (delta_r) ** (-0.5)
                * x ** (-1)
                * (1 + 0.8 * (I_list[i] + I_list[i + 1]))
            )

    return smooth_on_corners(base_corners, R_step, window=500, scale=0.001, mode="sum")


def compute_C_and_Ks(K, T, note_seq, key_usage, base_corners):
    # C(s)：500 ms 窗口内的 head 数（heads-only）
    note_hit_times = np.array(sorted(n[1] for n in note_seq), dtype=float)
    lo = np.searchsorted(note_hit_times, base_corners - 500, side="left")
    hi = np.searchsorted(note_hit_times, base_corners + 500, side="left")
    C_step = (hi - lo).astype(float)

    # C(s) V2：heads + LN tails（tail >= 0 才并入）；effectiveWeights 恒用 V2，
    # 对应 js sunnyAlgorithm 恒为 Classic 开启的行为。
    note_hit_times_v2 = np.array(
        sorted(t for n in note_seq for t in ((n[1],) if n[2] < 0 else (n[1], n[2]))),
        dtype=float,
    )
    lo_v2 = np.searchsorted(note_hit_times_v2, base_corners - 500, side="left")
    hi_v2 = np.searchsorted(note_hit_times_v2, base_corners + 500, side="left")
    C_step_v2 = (hi_v2 - lo_v2).astype(float)

    # Ks：局部按键使用数量（至少为 1）
    usage_stack = np.stack([key_usage[k] for k in range(K)], axis=0)
    Ks_step = np.maximum(usage_stack.sum(axis=0), 1).astype(float)

    return C_step, C_step_v2, Ks_step


def calculate(file_path, speed_rate=1.0, od_flag=None, cvt_flag=None, *, chart=None):
    # === 基础设置与解析 ===
    (
        status,
        x,
        K,
        T,
        note_seq,
        note_seq_by_column,
        LN_seq,
        tail_seq,
        LN_seq_by_column,
        LN_ratio,
        column_count,
    ) = preprocess_file(file_path, speed_rate, od_flag, cvt_flag, chart=chart)

    if status == "Fail":
        return -1
    if status == "NotMania":
        return -2
    # 对齐 js L885：D3 shift 后 note_seq 可能为空（单音符图），JS 返回 -1。
    if not note_seq or K <= 0:
        return -1

    all_corners, base_corners, A_corners = get_corners(T, note_seq)

    # 对每一列，记录其在时间轴上的使用状态（150 ms 内是否有物件）。示例：key_usage[k][idx]。
    key_usage = get_key_usage(K, T, note_seq, base_corners)
    key_usage_400 = get_key_usage_400(K, T, note_seq, base_corners)
    anchor = compute_anchor(K, key_usage_400, base_corners)

    delta_ks, Jbar = compute_Jbar(K, T, x, note_seq_by_column, base_corners)
    Jbar = interp_values(all_corners, base_corners, Jbar)

    Xbar = compute_Xbar(K, T, x, note_seq_by_column, key_usage, base_corners)
    Xbar = interp_values(all_corners, base_corners, Xbar)

    # 构建累计 LN 主体的稀疏表示。
    LN_rep = LN_bodies_count_sparse_representation(LN_seq, T)

    Pbar = compute_Pbar(K, T, x, note_seq, LN_rep, anchor, base_corners)
    Pbar = interp_values(all_corners, base_corners, Pbar)

    Abar = compute_Abar(
        K, T, x, note_seq_by_column, key_usage, delta_ks, A_corners, base_corners
    )
    Abar = interp_values(all_corners, A_corners, Abar)

    Rbar = compute_Rbar(K, T, x, note_seq_by_column, tail_seq, base_corners)
    Rbar = interp_values(all_corners, base_corners, Rbar)

    C_step, C_step_v2, Ks_step = compute_C_and_Ks(K, T, note_seq, key_usage, base_corners)
    C_arr = step_interp(all_corners, base_corners, C_step)
    C_arr_v2 = step_interp(all_corners, base_corners, C_step_v2)
    Ks_arr = step_interp(all_corners, base_corners, Ks_step)

    # === 最终计算 ===
    # 在 all_corners 上计算难度 D：
    S_all = (
        (0.4 * (Abar ** (3 / Ks_arr) * np.minimum(Jbar, 8 + 0.85 * Jbar)) ** 1.5)
        + ((1 - 0.4) * (Abar ** (2 / 3) * (0.8 * Pbar + Rbar * 35 / (C_arr + 8))) ** 1.5)
    ) ** (2 / 3)
    T_all = (Abar ** (3 / Ks_arr) * Xbar) / (Xbar + S_all + 1)
    D_all = 2.7 * (S_all**0.5) * (T_all**1.5) + S_all * 0.27

    # 向量化计算相邻时间点之间的间隔。
    # 对于内部点，有效间隔取左右间隔的平均值。
    gaps = np.empty_like(all_corners, dtype=float)
    gaps[0] = (all_corners[1] - all_corners[0]) / 2.0
    gaps[-1] = (all_corners[-1] - all_corners[-2]) / 2.0
    gaps[1:-1] = (all_corners[2:] - all_corners[:-2]) / 2.0

    # 每个角点的有效权重是密度与间隔的乘积；恒用 V2（heads+tails 计数），
    # 对应 js sunny 恒为 Classic 开启的行为。S 公式中的 C_arr 保持 heads-only。
    effective_weights = C_arr_v2 * gaps
    sorted_indices = np.argsort(D_all)
    D_sorted = D_all[sorted_indices]
    w_sorted = effective_weights[sorted_indices]

    # 计算有效权重的累计和。
    cum_weights = np.cumsum(w_sorted)
    total_weight = cum_weights[-1]
    norm_cum_weights = cum_weights / total_weight

    target_percentiles = np.array(
        [0.945, 0.935, 0.925, 0.915, 0.845, 0.835, 0.825, 0.815]
    )

    indices = np.searchsorted(norm_cum_weights, target_percentiles, side="left")

    # clamp：对齐 js L957-958 的 Math.min(idx, DSorted.length-1) 保护。
    n_d = len(D_sorted)
    percentile_93 = np.mean(D_sorted[np.minimum(indices[:4], n_d - 1)])
    percentile_83 = np.mean(D_sorted[np.minimum(indices[4:8], n_d - 1)])

    weighted_mean = (np.sum(D_sorted**5 * w_sorted) / np.sum(w_sorted)) ** (1 / 5)

    # 最终星数计算
    SR = (
        (0.88 * percentile_93) * 0.25
        + (0.94 * percentile_83) * 0.2
        + weighted_mean * 0.55
    )
    SR = SR ** (1.0) / (8**1.0) * 8

    total_notes = len(note_seq) + 0.5 * sum(
        np.minimum((t - h), 1000) / 200 for (k, h, t) in LN_seq
    )
    SR *= total_notes / (total_notes + 60)

    SR = rescale_high(SR)
    SR *= 0.975

    return SR, LN_ratio, column_count
