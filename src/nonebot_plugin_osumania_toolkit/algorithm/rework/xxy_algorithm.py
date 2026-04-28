'''
该文件来源于 https://github.com/sunnyxxy/Star-Rating-Rebirth/blob/main/algorithm.py
为适配功能做了一些改动，并应用了向量化优化。
'''
from ...parser.osu_file_parser import osu_file
from collections import defaultdict
import numpy as np
import pandas as pd
import bisect
import math

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
    idx = np.clip(idx, 0, len(x)-2)
    return F[idx] + f[idx] * (q_arr - x[idx])

def smooth_on_corners(x, f, window, scale=1.0, mode='sum'):
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

    if mode == 'avg':
        span = b - a
        return np.where(span > 0, val / span, 0.0)
    return scale * val

def interp_values(new_x, old_x, old_vals):
    """summary: 通过线性插值计算新位置的值。"""
    return np.interp(new_x, old_x, old_vals)

def step_interp(new_x, old_x, old_vals):
    """
    summary:
        对每个查询点返回其左侧最近采样点的值。
    Args:
        new_x: 新查询点。
        old_x: 原始采样点。
        old_vals: 原始采样值。
    Returns:
        零阶保持插值结果。
    """
    indices = np.searchsorted(old_x, new_x, side='right') - 1
    indices = np.clip(indices, 0, len(old_vals)-1)
    return old_vals[indices]

def rescale_high(sr):
    if sr <= 9:
        return sr
    return 9 + (sr - 9) * (1 / 1.2)

def find_next_note_in_column(note, times, note_seq_by_column):
    k, h, t = note
    idx = bisect.bisect_left(times, h)
    return note_seq_by_column[k][idx+1] if idx+1 < len(note_seq_by_column[k]) else (0, 10**9, 10**9)

# ----- 原始 stream_booster（保留） -----
def stream_booster(delta):
    return 1 + 1.7e-7 * ((7.5 / delta) - 160) * ((7.5 / delta) - 360)**2 if 160 < (7.5 / delta) < 360 else 1

# ===== 辅助函数结束 =====

def preprocess_file(file_path, speed_rate, od_flag, cvt_flag):
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
            od = 6.462+0.715*p[5]
        case "EZ":
            od = -20.761+2.566*p[5]
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
    x = 0.3 * ((64.5 - math.ceil(od * 3)) / 500)**0.5
    x = min(x, 0.6*(x-0.09)+0.09)
    note_seq.sort(key=lambda tup: (tup[1], tup[0]))

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
    T = max( max(n[1] for n in note_seq),
             max(n[2] for n in note_seq)) + 1

    status = "OK"
    return status, x, K, T, note_seq, note_seq_by_column, LN_seq, tail_seq, LN_seq_by_column, LN_ratio, column_count

def get_corners(T, note_seq):
    corners_base = set()
    for (_, h, t) in note_seq:
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
    for (_, h, t) in note_seq:
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

def get_key_usage(K, T, note_seq, base_corners):
    key_usage = {k: np.zeros(len(base_corners), dtype=bool) for k in range(K)}
    for (k, h, t) in note_seq:
        startTime = max(h - 150, 0)
        endTime = (h + 150) if t < 0 else min(t + 150, T-1)
        left_idx = np.searchsorted(base_corners, startTime, side='left')
        right_idx = np.searchsorted(base_corners, endTime, side='left')
        key_usage[k][left_idx:right_idx] = True
    return key_usage

def get_key_usage_400(K, T, note_seq, base_corners):
    key_usage_400 = {k: np.zeros(len(base_corners), dtype=float) for k in range(K)}
    for (k, h, t) in note_seq:
        startTime = max(h, 0)
        endTime = h if t < 0 else min(t, T-1)
        left400_idx = np.searchsorted(base_corners, startTime - 400, side='left')
        left_idx = np.searchsorted(base_corners, startTime, side='left')
        right_idx = np.searchsorted(base_corners, endTime, side='left')
        right400_idx = np.searchsorted(base_corners, endTime + 400, side='left')

        # 主体区间
        idx_main = np.arange(left_idx, right_idx)
        key_usage_400[k][idx_main] += 3.75 + np.minimum(endTime - startTime, 1500)/150

        # 左侧尾部（二次衰减）
        idx_left = np.arange(left400_idx, left_idx)
        if len(idx_left) > 0:
            t_left = base_corners[idx_left]
            key_usage_400[k][idx_left] += 3.75 - 3.75/400**2 * (t_left - startTime)**2

        # 右侧尾部
        idx_right = np.arange(right_idx, right400_idx)
        if len(idx_right) > 0:
            t_right = base_corners[idx_right]
            key_usage_400[k][idx_right] += 3.75 - 3.75/400**2 * (t_right - endTime)**2
    return key_usage_400

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

    for (k, h, t) in LN_seq:
        t0 = min(h + 60, t)
        t1 = min(h + 120, t)
        diff[t0] = diff.get(t0, 0) + 1.3
        diff[t1] = diff.get(t1, 0) + (-1.3 + 1)  # t1 的净变化：先减 1.3，再加 1
        diff[t]  = diff.get(t, 0) - 1

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
        seg_length = points[i+1] - points[i]
        cumsum.append(cumsum[-1] + seg_length * v)
    return points, cumsum, values

def LN_sum(a, b, LN_rep):
    points, cumsum, values = LN_rep
    # 定位包含 a 和 b 的分段。
    i = bisect.bisect_right(points, a) - 1
    j = bisect.bisect_right(points, b) - 1

    total = 0.0
    if i == j:
        # a 和 b 落在同一分段。
        total = (b - a) * values[i]
    else:
        # 第一段：从 a 到第 i 段末尾。
        total += (points[i+1] - a) * values[i]
        # 中间的完整分段：i+1 到 j-1。
        total += cumsum[j] - cumsum[i+1]
        # 最后一段：从第 j 段起点到 b。
        total += (b - points[j]) * values[j]
    return total

def compute_Jbar(K, T, x, note_seq_by_column, base_corners):
    J_ks = {k: np.zeros(len(base_corners)) for k in range(K)}
    delta_ks = {k: np.full(len(base_corners), 1e9) for k in range(K)}
    jack_nerfer = lambda delta: 1 - 7e-5 * (0.15 + np.abs(delta - 0.08))**(-4)

    for k in range(K):
        notes = note_seq_by_column[k]
        if len(notes) < 2:
            continue
        starts = np.array([n[1] for n in notes[:-1]], dtype=float)
        ends = np.array([n[1] for n in notes[1:]], dtype=float)
        deltas = 0.001 * (ends - starts)
        vals = (deltas**(-1)) * (deltas + 0.11 * x**0.25)**(-1) * jack_nerfer(deltas)

        for start, end, delta, val in zip(starts, ends, deltas, vals):
            li = np.searchsorted(base_corners, start, side='left')
            ri = np.searchsorted(base_corners, end, side='left')
            if ri > li:
                J_ks[k][li:ri] = val
                delta_ks[k][li:ri] = delta

    Jbar_ks = {
        k: smooth_on_corners(base_corners, J_ks[k], window=500, scale=0.001, mode='sum')
        for k in range(K)
    }

    Jbar_stack = np.stack([Jbar_ks[k] for k in range(K)], axis=0)
    delta_stack = np.stack([delta_ks[k] for k in range(K)], axis=0)
    weights = 1.0 / delta_stack
    num = np.sum(np.maximum(Jbar_stack, 0) ** 5 * weights, axis=0)
    den = np.sum(weights, axis=0)
    Jbar = (num / np.maximum(den, 1e-9)) ** 0.2

    return delta_ks, Jbar

def compute_Xbar(K, T, x, note_seq_by_column, active_columns, base_corners):
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
        [0.325, 0.55, 0.45, 0.35, 0.25, 0.05, 0.25, 0.35, 0.45, 0.55, 0.325]
    ]
    X_ks = {k: np.zeros(len(base_corners)) for k in range(K+1)}
    fast_cross = {k: np.zeros(len(base_corners)) for k in range(K+1)}
    cross_coeff = cross_matrix[K]

    for k in range(K+1):
        if k == 0:
            notes_in_pair = note_seq_by_column[0]
        elif k == K:
            notes_in_pair = note_seq_by_column[K-1]
        else:
            notes_in_pair = sorted(
                note_seq_by_column[k-1] + note_seq_by_column[k], key=lambda t: t[1]
            )
        for i in range(1, len(notes_in_pair)):
            start = notes_in_pair[i-1][1]
            end = notes_in_pair[i][1]
            li = np.searchsorted(base_corners, start, side='left')
            ri = np.searchsorted(base_corners, end, side='left')
            if ri <= li:
                continue
            delta = 0.001 * (notes_in_pair[i][1] - notes_in_pair[i-1][1])
            val = 0.16 * max(x, delta) ** -2

            left_inactive = (k-1) not in active_columns[li] and (k-1) not in active_columns[ri]
            right_inactive = k not in active_columns[li] and k not in active_columns[ri]
            if left_inactive or right_inactive:
                val *= 1 - cross_coeff[k]

            X_ks[k][li:ri] = val
            fast_cross[k][li:ri] = max(0, 0.4 * max(delta, 0.06, 0.75*x) ** -2 - 80)

    X_base = np.zeros(len(base_corners))
    for i in range(len(base_corners)):
        X_base[i] = sum(X_ks[k][i] * cross_coeff[k] for k in range(K+1)) + \
                    sum(np.sqrt(fast_cross[k][i]*cross_coeff[k]*fast_cross[k+1][i]*cross_coeff[k+1]) for k in range(K))

    return smooth_on_corners(base_corners, X_base, window=500, scale=0.001, mode='sum')

def compute_Pbar(K, T, x, note_seq, LN_rep, anchor, base_corners):
    P_step = np.zeros(len(base_corners))

    for i in range(len(note_seq) - 1):
        h_l = note_seq[i][1]
        h_r = note_seq[i+1][1]
        delta_time = h_r - h_l

        if delta_time < 1e-9:
            spike = 1000 * (0.02 * (4 / x - 24)) ** 0.25
            li = np.searchsorted(base_corners, h_l, side='left')
            ri = np.searchsorted(base_corners, h_l, side='right')
            if ri > li:
                P_step[li:ri] += spike
            continue

        li = np.searchsorted(base_corners, h_l, side='left')
        ri = np.searchsorted(base_corners, h_r, side='left')
        if ri <= li:
            continue

        delta = 0.001 * delta_time
        v = 1 + 6 * 0.001 * LN_sum(h_l, h_r, LN_rep)
        b_val = stream_booster(delta)  # 原始版本
        if delta < 2 * x / 3:
            inc = delta**(-1) * (0.08 * x**(-1) * (1 - 24 * x**(-1) * (delta - x/2)**2)) ** 0.25 * max(b_val, v)
        else:
            inc = delta**(-1) * (0.08 * x**(-1) * (1 - 24 * x**(-1) * (x/6)**2)) ** 0.25 * max(b_val, v)

        seg_anchor = anchor[li:ri]
        P_step[li:ri] += np.minimum(inc * seg_anchor, np.maximum(inc, inc*2-10))

    return smooth_on_corners(base_corners, P_step, window=500, scale=0.001, mode='sum')

def compute_Abar(K, T, x, note_seq_by_column, active_columns, delta_ks, A_corners, base_corners):
    dks = {k: np.zeros(len(base_corners)) for k in range(K-1)}
    for i in range(len(base_corners)):
        cols = active_columns[i]
        for j in range(len(cols) - 1):
            k0, k1 = cols[j], cols[j+1]
            dks[k0][i] = abs(delta_ks[k0][i] - delta_ks[k1][i]) + 0.4 * max(0, max(delta_ks[k0][i], delta_ks[k1][i]) - 0.11)

    A_step = np.ones(len(A_corners))
    bc_idx = np.clip(np.searchsorted(base_corners, A_corners), 0, len(base_corners)-1)

    for i in range(len(A_corners)):
        idx = bc_idx[i]
        cols = active_columns[idx]
        for j in range(len(cols) - 1):
            k0, k1 = cols[j], cols[j+1]
            d_val = dks[k0][idx]
            dk0, dk1 = delta_ks[k0][idx], delta_ks[k1][idx]
            if d_val < 0.02:
                A_step[i] *= min(0.75 + 0.5 * max(dk0, dk1), 1)
            elif d_val < 0.07:
                A_step[i] *= min(0.65 + 5*d_val + 0.5 * max(dk0, dk1), 1)

    return smooth_on_corners(A_corners, A_step, window=250, mode='avg')

def compute_Rbar(K, T, x, note_seq_by_column, tail_seq, base_corners):
    I_arr = np.zeros(len(base_corners))
    R_step = np.zeros(len(base_corners))

    times_by_column = {i: [note[1] for note in column]
                       for i, column in enumerate(note_seq_by_column)}

    # Release 指标
    I_list = []
    for i in range(len(tail_seq)):
        k, h_i, t_i = tail_seq[i]
        _, h_j, _ = find_next_note_in_column((k, h_i, t_i), times_by_column[k], note_seq_by_column)
        I_h = 0.001 * abs(t_i - h_i - 80) / x
        I_t = 0.001 * abs(h_j - t_i - 80) / x
        I_list.append(2 / (2 + math.exp(-5*(I_h-0.75)) + math.exp(-5*(I_t-0.75))))

    # 在相邻尾点之间的每个区间内，赋值 I 和 R。
    for i in range(len(tail_seq)-1):
        t_start = tail_seq[i][2]
        t_end = tail_seq[i+1][2]
        left_idx = np.searchsorted(base_corners, t_start, side='left')
        right_idx = np.searchsorted(base_corners, t_end, side='left')
        idx = np.arange(left_idx, right_idx)
        if len(idx) == 0:
            continue
        I_arr[idx] = 1 + I_list[i]
        delta_r = 0.001 * (tail_seq[i+1][2] - tail_seq[i][2])
        R_step[idx] = 0.08 * (delta_r)**(-0.5) * x**(-1) * (1 + 0.8*(I_list[i] + I_list[i+1]))

    return smooth_on_corners(base_corners, R_step, window=500, scale=0.001, mode='sum')

def compute_C_and_Ks(K, T, note_seq, key_usage, base_corners):
    # C(s)：500 ms 内的 note 数
    note_hit_times = np.array(sorted(n[1] for n in note_seq), dtype=float)
    lo = np.searchsorted(note_hit_times, base_corners - 500, side='left')
    hi = np.searchsorted(note_hit_times, base_corners + 500, side='left')
    C_step = (hi - lo).astype(float)

    # Ks：局部按键使用数量（至少为 1）
    usage_stack = np.stack([key_usage[k] for k in range(K)], axis=0)
    Ks_step = np.maximum(usage_stack.sum(axis=0), 1).astype(float)

    return C_step, Ks_step

def calculate(file_path, speed_rate = 1.0, od_flag = None, cvt_flag = None):
    # === 基础设置与解析 ===
    status, x, K, T, note_seq, note_seq_by_column, LN_seq, tail_seq, LN_seq_by_column, LN_ratio, column_count = preprocess_file(file_path, speed_rate, od_flag, cvt_flag)

    if status == "Fail":
        return -1
    if status == "NotMania":
        return -2

    all_corners, base_corners, A_corners = get_corners(T, note_seq)

    # 对每一列，记录其在时间轴上的使用状态（150 ms 内是否有物件）。示例：key_usage[k][idx]。
    key_usage = get_key_usage(K, T, note_seq, base_corners)
    # 在 base_corners 的每个时间点，构建当前处于活跃状态的列列表：
    active_columns = [ [k for k in range(K) if key_usage[k][i]] for i in range(len(base_corners)) ]

    key_usage_400 = get_key_usage_400(K, T, note_seq, base_corners)
    anchor = compute_anchor(K, key_usage_400, base_corners)

    delta_ks, Jbar = compute_Jbar(K, T, x, note_seq_by_column, base_corners)
    Jbar = interp_values(all_corners, base_corners, Jbar)

    Xbar = compute_Xbar(K, T, x, note_seq_by_column, active_columns, base_corners)
    Xbar = interp_values(all_corners, base_corners, Xbar)

    # 构建累计 LN 主体的稀疏表示。
    LN_rep = LN_bodies_count_sparse_representation(LN_seq, T)

    Pbar = compute_Pbar(K, T, x, note_seq, LN_rep, anchor, base_corners)
    Pbar = interp_values(all_corners, base_corners, Pbar)

    Abar = compute_Abar(K, T, x, note_seq_by_column, active_columns, delta_ks, A_corners, base_corners)
    Abar = interp_values(all_corners, A_corners, Abar)

    Rbar = compute_Rbar(K, T, x, note_seq_by_column, tail_seq, base_corners)
    Rbar = interp_values(all_corners, base_corners, Rbar)

    C_step, Ks_step = compute_C_and_Ks(K, T, note_seq, key_usage, base_corners)
    C_arr = step_interp(all_corners, base_corners, C_step)
    Ks_arr = step_interp(all_corners, base_corners, Ks_step)

    # === 最终计算 ===
    # 在 all_corners 上计算难度 D：
    S_all = ((0.4 * (Abar**(3/ Ks_arr) * np.minimum(Jbar, 8+0.85*Jbar))**1.5) +
             ((1-0.4) * (Abar**(2/3) * (0.8*Pbar + Rbar*35/(C_arr+8)))**1.5))**(2/3)
    T_all = (Abar**(3/ Ks_arr) * Xbar) / (Xbar + S_all + 1)
    D_all = 2.7 * (S_all**0.5) * (T_all**1.5) + S_all * 0.27

    df_corners = pd.DataFrame({
        'time': all_corners,
        'Jbar': Jbar,
        'Xbar': Xbar,
        'Pbar': Pbar,
        'Abar': Abar,
        'Rbar': Rbar,
        'C': C_arr,
        'Ks': Ks_arr,
        'D': D_all
    })

    # 向量化计算相邻时间点之间的间隔。
    # 对于内部点，有效间隔取左右间隔的平均值。
    gaps = np.empty_like(all_corners, dtype=float)
    gaps[0] = (all_corners[1] - all_corners[0]) / 2.0
    gaps[-1] = (all_corners[-1] - all_corners[-2]) / 2.0
    gaps[1:-1] = (all_corners[2:] - all_corners[:-2]) / 2.0

    # 每个角点的有效权重是密度与间隔的乘积。
    effective_weights = C_arr * gaps
    df_sorted = df_corners.sort_values('D')
    D_sorted = df_sorted['D'].values
    sorted_indices = df_sorted.index.to_numpy()
    w_sorted = effective_weights[sorted_indices]

    # 计算有效权重的累计和。
    cum_weights = np.cumsum(w_sorted)
    total_weight = cum_weights[-1]
    norm_cum_weights = cum_weights / total_weight

    target_percentiles = np.array([0.945, 0.935, 0.925, 0.915, 0.845, 0.835, 0.825, 0.815])

    indices = np.searchsorted(norm_cum_weights, target_percentiles, side='left')

    percentile_93 = np.mean(D_sorted[indices[:4]])
    percentile_83 = np.mean(D_sorted[indices[4:8]])

    weighted_mean = (np.sum(D_sorted**5 * w_sorted) / np.sum(w_sorted))**(1 / 5)

    # 最终星数计算
    SR = (0.88 * percentile_93) * 0.25 + (0.94 * percentile_83) * 0.2 + weighted_mean * 0.55
    SR = SR**(1.0) / (8**1.0) * 8

    total_notes = len(note_seq) + 0.5*sum(np.minimum((t-h), 1000)/200 for (k, h, t) in LN_seq)
    SR *= total_notes / (total_notes + 60)

    SR = rescale_high(SR)
    SR *= 0.975

    return SR, LN_ratio, column_count