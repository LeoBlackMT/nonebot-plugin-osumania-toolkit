"""XDC1 估计器 —— ``js/estimator/xdc1Estimator.js`` 的直译（4K）。

上游算法：TheBagelOfMan/xdc1 v1.0（MIT）。本模块只复刻插件消费的两项输出：
``rating``（0–100 显示值）与按 ``XDC1_RATING_DAN_KNOTS`` 折线换算的 Reform 段位；
C++ 的 ``rating_rice`` 与 7 项 skillset 不参与 rating/graph，未移植。

作用域：仅 4K；其他键数/解析失败/低于 Alpha Low 返回 ``Unsupported: ...``，
``unsupported=True``，不切换到 Sunny。固定 OD9 判定窗（不读 ``od_flag``）。

Mixed 路由里它出现在三处（见 ``mixed.py``）：
- R3'：Roxy 胜出后与之对称融合（差距 < 0.50）或切向纯 XDC1（≥ 0.50）；
- R4-Hi：高段 Azusa 越界时 XDC1⊕Azusa 对称融合；
- C8'：低难 Azusa⊕Companella 融合后仍显著低于 XDC1（≥ 0.50）时兜底切向 XDC1。
"""

from __future__ import annotations

import math
from typing import Any

from .rc import numeric_to_rc_label
from .shared import js_fixed, resolve_chart_path

# ── 共享网格工具：所有曲线都落在有序时间网格（ms）上，每个值保持到下一个点 ──
WINDOW_MS = 500.0
LN_TAP_MS = 80.0


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _zeros(size: int) -> list[float]:
    return [0.0] * size


def _lower_bound(sorted_values: list[float], value: float) -> int:
    lo = 0
    hi = len(sorted_values)
    while lo < hi:
        mid = (lo + hi) >> 1
        if sorted_values[mid] < value:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _upper_bound(sorted_values: list[float], value: float) -> int:
    lo = 0
    hi = len(sorted_values)
    while lo < hi:
        mid = (lo + hi) >> 1
        if sorted_values[mid] <= value:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _hit_window_unit() -> float:
    """判定窗单位，固定 OD9。"""
    x = 0.3 * math.sqrt((64.5 - math.ceil(9.0 * 3.0)) / 500.0)
    return min(x, 0.6 * (x - 0.09) + 0.09)


def _window_integral(x: list[float], f: list[float], window: float) -> list[float]:
    """分段常数 f 在 [x[i]-window, x[i]+window] 上的积分，裁剪到 x 的范围。"""
    n = len(x)
    out = _zeros(n)
    if n < 2:
        return out
    prefix = _zeros(n)
    for i in range(1, n):
        prefix[i] = prefix[i - 1] + f[i - 1] * (x[i] - x[i - 1])
    ca = 0
    cb = 0
    for i in range(n):
        a = _clamp(x[i] - window, x[0], x[n - 1])
        b = _clamp(x[i] + window, x[0], x[n - 1])
        while ca < n and x[ca] < a:
            ca += 1
        while cb < n and x[cb] < b:
            cb += 1
        ia = ca - 1 if ca else 0
        ib = cb - 1 if cb else 0
        out[i] = (prefix[ib] + f[ib] * (b - x[ib])) - (prefix[ia] + f[ia] * (a - x[ia]))
    return out


def _window_sum(
    x: list[float], f: list[float], window: float, scale: float
) -> list[float]:
    out = _window_integral(x, f, window)
    for i in range(len(out)):
        out[i] *= scale
    return out


def _window_avg(x: list[float], f: list[float], window: float) -> list[float]:
    n = len(x)
    out = _window_integral(x, f, window)
    ca = 0
    cb = 0
    for i in range(n):
        a = _clamp(x[i] - window, x[0], x[n - 1])
        b = _clamp(x[i] + window, x[0], x[n - 1])
        while ca < n and x[ca] < a:
            ca += 1
        while cb < n and x[cb] < b:
            cb += 1
        span = b - a
        out[i] = out[i] / span if span > 0.0 else 0.0
    return out


def _add_span(
    f: list[float], grid: list[float], t0: float, t1: float, val: float
) -> None:
    """把 [t0,t1) 上的常数 val 按网格单元时间平均累加，短跨度也能完整计入。"""
    if len(grid) < 2 or t1 <= t0:
        return
    q = _upper_bound(grid, t0)
    if q > 0:
        q -= 1
    while q + 1 < len(grid) and grid[q] < t1:
        lo = max(t0, grid[q])
        hi = min(t1, grid[q + 1])
        if hi > lo:
            f[q] += val * (hi - lo) / (grid[q + 1] - grid[q])
        q += 1


def _steps_to_grid(
    starts: list[float], vals: list[float], grid: list[float]
) -> list[float]:
    """按 transition 取值：值 i 从 starts[i] 保持到 starts[i+1]。"""
    out = _zeros(len(grid))
    if not vals:
        return out
    c = 0
    for i in range(len(grid)):
        while c < len(vals) and starts[c] <= grid[i]:
            c += 1
        out[i] = vals[c - 1 if c else 0]
    return out


# ── 音符与行 ────────────────────────────────────────────────────────────────
# note: {"k": 列, "h": 头时间, "t": 尾时间（tap 为 -1）}，始终按 (h, k) 排序。


def _head_times(notes: list[dict[str, Any]]) -> list[float]:
    return [note["h"] for note in notes]


def _column_count_of_mask(mask: int) -> int:
    return (mask & 1) + ((mask >> 1) & 1) + ((mask >> 2) & 1) + ((mask >> 3) & 1)


def _build_rows(notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for note in notes:
        if not rows or rows[-1]["t"] != note["h"]:
            rows.append({"t": note["h"], "mask": 0, "size": 0})
        row = rows[-1]
        row["mask"] |= 1 << note["k"]
        row["size"] = _column_count_of_mask(row["mask"])
    return rows


def _row_times(rows: list[dict[str, Any]]) -> list[float]:
    return [row["t"] for row in rows]


# ── 按压 strain（每只手）────────────────────────────────────────────────────
TECH_WINDOW_MS = 244.92
TECH_SCALE = 0.001

MOTION_X_COEF = 0.39104
MOTION_W = 5.7561
MOTION_REPEAT_W = 0.55187
FINGER_MIX_P = 2.3762
FLAM_MS = 11.247
FINGER_JACK_CRIT_MS = 218.21
JACK_FLOOR_MS = 35.809
MINIJACK_MS = 72.836
LN_HOLD_OCC = 0.754
ALT_CRIT_MS = 21.197

WRIST_W = 3.3377
WRIST_CHORD_W = 0.81919
WRIST_GAP_POW = 2.6413
WRIST_GAP_PIVOT_MS = 100.0
STROKE_CAP_MS = 1000.0
STROKE_TIE_FRAC = 0.125

CHORD_PHASE = 0.26009
ANCHOR_RUN_LO = 16.0
ANCHOR_RUN_HI = 48.0
MANIP_TOL_MS = 76.009
MANIP_TOL_POW = 2.6
MANIP_WINDOW = 12
MANIP_PERIOD_MAX = 12
MANIP_PERIOD_COST = 0.02
MANIP_PACE = 0.25
MANIP_PACE_FLOOR_MS = 4.0
MANIP_FLAM_MS = 10.0
MANIP_CONS_LO = 0.15
MANIP_CONS_HI = 0.75
WRIST_BLEND_MS = 64.443

JITTER_ONSET_MS = 95.0
JITTER_POW = 1.5
JITTER_REP_LO = 3.0
JITTER_REP_HI = 7.0


def _soften_gap(gap_ms: float) -> float:
    return math.sqrt(gap_ms * gap_ms + FLAM_MS * FLAM_MS)


def _gap_rate(delta_ms: float, x_term: float) -> float:
    d = 0.001 * delta_ms
    return (1.0 / d) * (1.0 / (d + x_term)) if d > 0.0 else 0.0


def _tech_sum(grid: list[float], f: list[float]) -> list[float]:
    return _window_sum(grid, f, TECH_WINDOW_MS, TECH_SCALE)


def _smoothstep01(u: float) -> float:
    t = _clamp(u, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _minijack_gaps(times: list[float]) -> list[float]:
    count = len(times) - 1 if len(times) > 1 else 0
    gaps = _zeros(count)
    for i in range(count):
        gaps[i] = times[i + 1] - times[i]
    out = list(gaps)
    for i in range(count):
        if gaps[i] >= MINIJACK_MS:
            continue
        before = max(0.5 * (gaps[i - 1] - gaps[i]), 0.0) if i > 0 else MINIJACK_MS
        after = max(0.5 * (gaps[i + 1] - gaps[i]), 0.0) if i + 1 < count else MINIJACK_MS
        out[i] = min(gaps[i] + before + after, MINIJACK_MS)
    return out


def _repeat_cost(hand_notes: list[dict[str, Any]], grid: list[float]) -> list[float]:
    finger_times: list[list[float]] = [[], []]
    for note in hand_notes:
        finger_times[note["f"]].append(note["t"])
    soft_gaps = [_minijack_gaps(finger_times[0]), _minijack_gaps(finger_times[1])]
    index = [0, 0]
    rate = _zeros(len(grid))
    last = [-1.0, -1.0]
    free_at = [0.0, 0.0]
    for note in hand_notes:
        f = note["f"]
        last_time = last[f]
        if last_time >= 0.0 and note["t"] > last_time:
            raw = soft_gaps[f][index[f] - 1]
            gap = _soften_gap(raw - min(LN_HOLD_OCC * free_at[f], raw - 1.0))
            c = FINGER_JACK_CRIT_MS / math.sqrt(gap * gap + JACK_FLOOR_MS * JACK_FLOOR_MS)
            pen = c * c
            _add_span(
                rate,
                grid,
                last_time,
                note["t"],
                (1.0 + pen) * _gap_rate(gap, 0.0) * raw / (note["t"] - last_time),
            )
        index[f] += 1
        last[f] = note["t"]
        free_at[f] = (
            max(note["tail"] - note["t"] - LN_TAP_MS, 0.0)
            if note["tail"] >= note["t"]
            else 0.0
        )
    return _tech_sum(grid, rate)


def _motion_cost(
    x: float, hand_notes: list[dict[str, Any]], grid: list[float]
) -> list[float]:
    times: list[float] = []
    masks: list[int] = []
    for note in hand_notes:
        if times and times[-1] == note["t"]:
            masks[-1] |= 1 << note["f"]
            continue
        times.append(note["t"])
        masks.append(1 << note["f"])
    xt = MOTION_X_COEF * math.pow(x, 0.25)
    rate = _zeros(len(grid))
    for i in range(len(times) - 1):
        gap = _soften_gap(times[i + 1] - times[i])
        if masks[i + 1] == 3:
            w = 1.0
        elif (masks[i + 1] & masks[i]) != 0:
            w = MOTION_REPEAT_W
        else:
            w = 1.0 + (ALT_CRIT_MS / gap) * (ALT_CRIT_MS / gap)
        _add_span(rate, grid, times[i], times[i + 1], w * _gap_rate(gap, xt))
    return _tech_sum(grid, rate)


def _finger_mix(jack: float, motion: float) -> float:
    a = jack
    b = MOTION_W * motion
    hi = max(a, b)
    if hi <= 0.0:
        return 0.0
    return hi * math.pow(1.0 + math.pow(min(a, b) / hi, FINGER_MIX_P), 1.0 / FINGER_MIX_P)


def _group_strokes(hand_notes: list[dict[str, Any]]) -> dict[str, list[Any]]:
    """一次 stroke：和弦，或一个音符加上另一只手在它之前的第一个音（若合适）。"""
    finger_times: list[list[float]] = [[], []]
    for i, note in enumerate(hand_notes):
        chord = (i > 0 and hand_notes[i - 1]["t"] == note["t"]) or (
            i + 1 < len(hand_notes) and hand_notes[i + 1]["t"] == note["t"]
        )
        if not chord:
            finger_times[note["f"]].append(note["t"])

    strokes: dict[str, list[Any]] = {
        "t": [],
        "width": [],
        "size": [],
        "mask": [],
        "lead": [],
        "first": [],
    }
    i = 0
    while i < len(hand_notes):
        j = i + 1
        if (
            j < len(hand_notes)
            and hand_notes[j]["f"] != hand_notes[i]["f"]
            and hand_notes[j]["t"] - hand_notes[i]["t"] <= STROKE_CAP_MS
            and not (
                j + 1 < len(hand_notes)
                and hand_notes[j + 1]["f"] == hand_notes[i]["f"]
                and hand_notes[j + 1]["t"] - hand_notes[j]["t"]
                < (hand_notes[j]["t"] - hand_notes[i]["t"]) * (1.0 - STROKE_TIE_FRAC)
            )
        ):
            j += 1
        strokes["t"].append(0.5 * (hand_notes[i]["t"] + hand_notes[j - 1]["t"]))
        width = hand_notes[j - 1]["t"] - hand_notes[i]["t"]
        if j - i == 1:
            other = finger_times[1 - hand_notes[i]["f"]]
            d = STROKE_CAP_MS
            q = _lower_bound(other, hand_notes[i]["t"])
            if q < len(other):
                d = min(d, other[q] - hand_notes[i]["t"])
            if q > 0:
                d = min(d, hand_notes[i]["t"] - other[q - 1])
            width = d if d < STROKE_CAP_MS else 0.0
        strokes["width"].append(width)
        strokes["size"].append(j - i)
        strokes["lead"].append(hand_notes[i]["f"])
        strokes["first"].append(i)
        mask = 0
        for q in range(i, j):
            mask |= 1 << hand_notes[q]["f"]
        strokes["mask"].append(mask)
        i = j
    return strokes


def _note_consistency(note_times: list[float], note_columns: list[int], i: int) -> float:
    """note i 周围的重复程度：1 减去最佳 lag 的缺失比例，再减去 lag 代价。"""
    n = len(note_times)
    a = i - MANIP_WINDOW if i >= MANIP_WINDOW else 0
    b = min(n, i + MANIP_WINDOW + 1)
    best = 0.0
    for p in range(1, MANIP_PERIOD_MAX + 1):
        if b < a + p + 4:
            break
        miss = 0.0
        count = 0
        q = a
        while q + p < b:
            if q + p + 1 >= b:
                break
            if (
                note_columns[q] != note_columns[q + p]
                or note_columns[q + 1] != note_columns[q + p + 1]
            ):
                miss += 1.0
                count += 1
                q += 1
                continue
            g1 = note_times[q + 1] - note_times[q]
            g2 = note_times[q + p + 1] - note_times[q + p]
            med = 0.5 * (g1 + g2)
            tol = math.sqrt(
                MANIP_PACE * med * MANIP_PACE * med
                + MANIP_PACE_FLOOR_MS * MANIP_PACE_FLOOR_MS
            )
            miss += _smoothstep01(abs(g1 - g2) / tol)
            count += 1
            q += 1
        if count <= 0:
            continue
        best = max(best, 1.0 - miss / count - MANIP_PERIOD_COST * (p - 1))
    return best


def _stroke_consistency(
    hand_notes_by_hand: list[list[dict[str, Any]]],
    strokes_by_hand: list[dict[str, list[Any]]],
) -> list[list[float]]:
    """每个 stroke 的 consistency：其音符的平均值，按双手合并后的序列读取。"""
    all_events: list[dict[str, Any]] = []
    for h in range(2):
        for q, note in enumerate(hand_notes_by_hand[h]):
            all_events.append({"t": note["t"], "c": 2 * h + note["f"], "h": h, "q": q})
    all_events.sort(key=lambda event: (event["t"], event["c"]))

    # 相距 MANIP_FLAM_MS 内的音符共享组首时间，列按顺序排列。
    e = 0
    while e < len(all_events):
        f = e + 1
        while (
            f < len(all_events)
            and all_events[f]["t"] - all_events[e]["t"] <= MANIP_FLAM_MS
        ):
            all_events[f]["t"] = all_events[e]["t"]
            f += 1
        group = sorted(all_events[e:f], key=lambda event: event["c"])
        for k in range(len(group)):
            all_events[e + k] = group[k]
        e = f

    note_times = [event["t"] for event in all_events]
    note_columns = [event["c"] for event in all_events]
    per = [
        _zeros(len(hand_notes_by_hand[0])),
        _zeros(len(hand_notes_by_hand[1])),
    ]
    for e, event in enumerate(all_events):
        per[event["h"]][event["q"]] = _note_consistency(note_times, note_columns, e)

    out: list[list[float]] = []
    for h in range(2):
        strokes = strokes_by_hand[h]
        values = _zeros(len(strokes["t"]))
        for k in range(len(values)):
            total = 0.0
            for q in range(strokes["size"][k]):
                total += per[h][strokes["first"][k] + q]
            values[k] = total / strokes["size"][k]
        out.append(values)
    return out


def _wrist_cost(
    hand_notes: list[dict[str, Any]],
    strokes: dict[str, list[Any]],
    consistency: list[float],
    other_times: list[float],
    grid: list[float],
) -> dict[str, list[float]]:
    n = len(strokes["t"])
    chord = _zeros(n)
    manip = _zeros(n)
    merged = _zeros(n)
    strike = _zeros(n)
    for k in range(n):
        period = 0.0
        if k > 0:
            period = max(period, strokes["t"][k] - strokes["t"][k - 1])
        if k + 1 < n:
            period = max(period, strokes["t"][k + 1] - strokes["t"][k])
        phase = (
            0.0
            if strokes["width"][k] <= 0.0
            else (strokes["width"][k] / period if period > 0.0 else 1.0)
        )
        near = 1.0 - _smoothstep01(phase / CHORD_PHASE)
        pair = strokes["size"][k] == 2 and strokes["width"][k] > 0.0
        chord[k] = 0.0 if pair else near
        # 一对音符之间夹着另一只手的音符时不能合并。
        lo = strokes["t"][k] - 0.5 * strokes["width"][k]
        hi = strokes["t"][k] + 0.5 * strokes["width"][k]
        q = _lower_bound(other_times, lo)
        across = q < len(other_times) and lo < other_times[q] < hi
        manip[k] = (
            1.0
            - (1.0 - near)
            * (
                1.0
                - _smoothstep01(
                    (consistency[k] - MANIP_CONS_LO) / (MANIP_CONS_HI - MANIP_CONS_LO)
                )
            )
            if pair and not across
            else 0.0
        )
        merged[k] = 1.0 - (1.0 - chord[k]) * (1.0 - manip[k])
        strike[k] = (
            1.0 if strokes["size"][k] == 1 else _smoothstep01((merged[k] - 0.2) / 0.6)
        )

    # anchor run：连续 strike 中同一手指一直在场，做软化以让 rate 平滑移动。
    run = _zeros(n)
    f = 1
    while f <= 2:
        forward = _zeros(n)
        backward = _zeros(n)
        for k in range(n):
            if strokes["mask"][k] & f:
                forward[k] = strike[k] * (
                    1.0
                    + (forward[k - 1] if k > 0 and (strokes["mask"][k - 1] & f) else 0.0)
                )
        for k in range(n - 1, -1, -1):
            if strokes["mask"][k] & f:
                backward[k] = strike[k] * (
                    1.0
                    + (
                        backward[k + 1]
                        if k + 1 < n and (strokes["mask"][k + 1] & f)
                        else 0.0
                    )
                )
        for k in range(n):
            if strokes["mask"][k] & f:
                run[k] = max(run[k], forward[k] + backward[k] - strike[k])
        f <<= 1

    # jitter 的 repeat run：取手内行序列与 stroke 序列中较长者；只有真正的休息才打断。
    rep = [1.0] * n
    row_times_list: list[float] = []
    row_masks: list[int] = []
    row_of = _zeros(len(hand_notes))
    for q, note in enumerate(hand_notes):
        if not row_times_list or note["t"] != row_times_list[-1]:
            row_times_list.append(note["t"])
            row_masks.append(0)
        row_masks[-1] |= 1 << note["f"]
        row_of[q] = len(row_times_list) - 1
    nr = len(row_times_list)
    jacked = [False] * nr
    for k in range(nr):
        jacked[k] = (k > 0 and row_masks[k - 1] == row_masks[k]) or (
            k + 1 < nr and row_masks[k + 1] == row_masks[k]
        )

    def pace(g1: float, g2: float) -> float:
        return 1.0 - _smoothstep01(max(g1, g2) / max(min(g1, g2), 1.0) - 2.0)

    same = _zeros(nr)
    for k in range(1, nr):
        if row_masks[k] == row_masks[k - 1] or (
            jacked[k] and jacked[k - 1] and row_masks[k] != 3 and row_masks[k - 1] != 3
        ):
            same[k] = pace(
                (
                    row_times_list[k - 1] - row_times_list[k - 2]
                    if k >= 2
                    else row_times_list[k] - row_times_list[k - 1]
                ),
                row_times_list[k] - row_times_list[k - 1],
            )
    forward_rows = _zeros(nr)
    backward_rows = _zeros(nr)
    for k in range(1, nr):
        forward_rows[k] = same[k] * (1.0 + forward_rows[k - 1])
    for k in range(nr - 1, 0, -1):
        backward_rows[k - 1] = same[k] * (1.0 + backward_rows[k])

    stroke_same = _zeros(n)
    for k in range(1, n):
        if strokes["mask"][k] == strokes["mask"][k - 1]:
            stroke_same[k] = pace(
                (
                    strokes["t"][k - 1] - strokes["t"][k - 2]
                    if k >= 2
                    else strokes["t"][k] - strokes["t"][k - 1]
                ),
                strokes["t"][k] - strokes["t"][k - 1],
            )
    stroke_forward = _zeros(n)
    stroke_backward = _zeros(n)
    for k in range(1, n):
        stroke_forward[k] = stroke_same[k] * (1.0 + stroke_forward[k - 1])
    for k in range(n - 1, 0, -1):
        stroke_backward[k - 1] = stroke_same[k] * (1.0 + stroke_backward[k])

    for k in range(n):
        r = int(row_of[strokes["first"][k]])
        rep[k] = 1.0 + max(
            forward_rows[r] + backward_rows[r],
            stroke_forward[k] + stroke_backward[k],
        )

    rate = _zeros(len(grid))
    rate_manip = _zeros(len(grid))
    able = _zeros(len(grid))
    manip_curve = _zeros(len(grid))
    jitter_weight = _zeros(len(grid))
    for i in range(n - 1):
        gap = strokes["t"][i + 1] - strokes["t"][i]
        r = (
            _smoothstep01((run[i] - ANCHOR_RUN_LO) / (ANCHOR_RUN_HI - ANCHOR_RUN_LO))
            if (strokes["mask"][i + 1] & strokes["mask"][i]) != 0
            else 0.0
        )
        a = 1.0 - (1.0 - chord[i]) * (1.0 - r)
        _add_span(able, grid, strokes["t"][i], strokes["t"][i + 1], a)
        _add_span(manip_curve, grid, strokes["t"][i], strokes["t"][i + 1], manip[i])
        j = _smoothstep01((rep[i] - JITTER_REP_LO) / (JITTER_REP_HI - JITTER_REP_LO))
        share = (
            math.pow(gap / JITTER_ONSET_MS, JITTER_POW)
            if 0.0 < gap < JITTER_ONSET_MS
            else 1.0
        )
        _add_span(
            jitter_weight,
            grid,
            strokes["t"][i],
            strokes["t"][i + 1],
            j * min(1.0, (1.0 - share) / 0.1),
        )
        load = 1.0 + WRIST_CHORD_W * (strokes["size"][i + 1] - 1.0)
        off = (
            strokes["width"][i + 1] / MANIP_TOL_MS if strokes["size"][i + 1] == 2 else 0.0
        )
        c = (
            load
            * _gap_rate(gap, 0.0)
            * (
                math.pow(WRIST_GAP_PIVOT_MS / gap, WRIST_GAP_POW - 2.0)
                if gap > 0.0
                else 1.0
            )
            * (1.0 - j * (1.0 - share))
        )
        _add_span(rate, grid, strokes["t"][i], strokes["t"][i + 1], c)
        _add_span(
            rate_manip,
            grid,
            strokes["t"][i],
            strokes["t"][i + 1],
            c * (1.0 + math.pow(off, MANIP_TOL_POW)),
        )

    cost = [value * WRIST_W for value in _tech_sum(grid, rate)]
    cost_manip = [value * WRIST_W for value in _tech_sum(grid, rate_manip)]
    return {
        "cost": cost,
        "costManip": cost_manip,
        "able": _window_avg(grid, able, WRIST_BLEND_MS),
        "manip": _window_avg(grid, manip_curve, WRIST_BLEND_MS),
        "jitw": _window_avg(grid, jitter_weight, WRIST_BLEND_MS),
    }


def _hand_cost(finger: float, wrist: dict[str, list[float]], index: int) -> float:
    w = _clamp(wrist["able"][index], 0.0, 1.0)
    m = _clamp(wrist["manip"][index], 0.0, 1.0)
    h = (1.0 - w) * (
        (1.0 - m) * finger + m * min(finger, wrist["costManip"][index])
    ) + w * wrist["cost"][index]
    j = _clamp(wrist["jitw"][index], 0.0, 1.0)
    return (1.0 - j) * h + j * min(h, wrist["costManip"][index])


def _technique_strain(
    x: float, by_column: list[list[dict[str, Any]]], grid: list[float]
) -> tuple[list[list[float]], list[list[float]]]:
    """列 0-1 为左手，2-3 为右手。返回每只手的 strain 与 wristability。"""
    hand_notes: list[list[dict[str, Any]]] = [[], []]
    strokes: list[dict[str, list[Any]]] = [{}, {}]
    for h in range(2):
        notes = hand_notes[h]
        for c in range(2 * h, 2 * h + 2):
            for note in by_column[c]:
                notes.append({"t": note["h"], "f": c - 2 * h, "tail": note["t"]})
        notes.sort(key=lambda note: (note["t"], note["f"]))
        strokes[h] = _group_strokes(notes)
    consistency = _stroke_consistency(hand_notes, strokes)

    out: list[list[float]] = [[], []]
    able: list[list[float]] = [[], []]
    for h in range(2):
        notes = hand_notes[h]
        jack = _repeat_cost(notes, grid)
        motion = _motion_cost(x, notes, grid)
        other = [note["t"] for note in hand_notes[1 - h]]
        wrist = _wrist_cost(notes, strokes[h], consistency[h], other, grid)
        out[h] = _zeros(len(grid))
        able[h] = _zeros(len(grid))
        for i in range(len(grid)):
            out[h][i] = _hand_cost(_finger_mix(jack[i], motion[i]), wrist, i)
            w = _clamp(wrist["able"][i], 0.0, 1.0)
            m = _clamp(wrist["manip"][i], 0.0, 1.0)
            able[h][i] = w + (1.0 - w) * m
    return out, able


# ── 体力：每只手一个能量槽，高于地图自身等级时消耗、低于时回复，另有缓慢耐久损失 ──
STAMINA_GAIN = 2.2908
STAMINA_PROP = 0.90996
STAMINA_CAP = 1.6526
STAMINA_TANK = 50.918
STAMINA_REFILL_REST_MS = 5000.0
STAMINA_REFILL_LEVEL_MS = 15000.0
STAM_INTERVAL_MS = 500.0
STAMINA_DURABILITY = 0.029925
STAMINA_LEVEL_POW = 5.0
STAMINA_EASY = 0.17545
STAMINA_EASY_WINDOW_MS = 4000


def _map_level(
    grid: list[float], strain: list[list[float]], weight: list[list[float]]
) -> float:
    n = len(strain[0])
    both = _zeros(n)
    for i in range(n):
        both[i] = 0.5 * (strain[0][i] + strain[1][i])
    g = _window_avg(grid, both, STAMINA_EASY_WINDOW_MS)
    acc = 0.0
    total_weight = 0.0
    for h in range(2):
        for i in range(n):
            if not (g[i] > 0.0):
                continue
            wd = math.pow(g[i], STAMINA_LEVEL_POW) * weight[h][i]
            acc += wd * g[i]
            total_weight += wd
    if total_weight <= 0.0 or acc <= 0.0:
        return 0.0
    easy = STAMINA_EASY * acc / total_weight
    acc5 = 0.0
    weight5 = 0.0
    for h in range(2):
        for i in range(n):
            if g[i] < easy:
                continue
            d = strain[h][i]
            d2 = d * d
            acc5 += d2 * d2 * d * weight[h][i]
            weight5 += weight[h][i]
    if weight5 <= 0.0 or acc5 <= 0.0:
        return 0.0
    return math.pow(acc5 / weight5, 0.2)


def _run_tank(grid: list[float], strain: list[float], level: float) -> list[float]:
    mod_curve = [1.0] * len(strain)
    tank = 1.0
    prev = 0.0
    work = 0.0
    for i in range(len(strain)):
        step = 0.0 if i == 0 else (grid[i] - grid[i - 1]) / STAM_INTERVAL_MS
        average = 0.5 * (prev + strain[i])
        prev = strain[i]
        rel = average / level
        if rel > 1.0:
            tank -= (rel - 1.0) * step / STAMINA_TANK
        else:
            tau = STAMINA_REFILL_REST_MS + STAMINA_REFILL_LEVEL_MS * rel * rel
            tank += (1.0 - tank) * (1.0 - math.exp(-step * STAM_INTERVAL_MS / tau))
        tank = max(tank, 0.0)
        work += rel * step * STAM_INTERVAL_MS / 60000.0
        mod_curve[i] = (1.0 + (STAMINA_CAP - 1.0) * (1.0 - tank)) * (
            1.0 + STAMINA_DURABILITY * math.sqrt(work)
        )
    return mod_curve


def _apply_stamina(
    grid: list[float], strain: list[list[float]], weight: list[list[float]]
) -> None:
    level = STAMINA_PROP * _map_level(grid, strain, weight)
    if not (level > 0.0):
        return
    for h in range(2):
        mod = _run_tank(grid, strain[h], level)
        for i in range(len(mod)):
            strain[h][i] *= max(0.0, 1.0 + STAMINA_GAIN * (mod[i] - 1.0))


# ── 双手合并 ────────────────────────────────────────────────────────────────
HAND_P_SYNC = 6.1324
HAND_P_ALT = 2.526
SWITCH_MIX = 0.16864
SWITCH_WINDOW_MS = 500.0


def _hand_sync(
    able: list[list[float]], rows: list[dict[str, Any]], grid: list[float]
) -> list[float]:
    sync = _zeros(len(able[0]))
    switch_curve = _zeros(len(grid))
    points: list[float] = []
    changes: list[float] = []
    for r in range(1, len(rows)):
        a = rows[r - 1]["mask"]
        b = rows[r]["mask"]
        if rows[r - 1]["size"] != 1 or rows[r]["size"] != 1:
            continue
        points.append(rows[r]["t"])
        changes.append(1.0 if ((a & 3) != 0) != ((b & 3) != 0) else 0.0)
    cumulative = _zeros(len(changes) + 1)
    for k in range(len(changes)):
        cumulative[k + 1] = cumulative[k] + changes[k]
    lo = 0
    hi = 0
    for i in range(len(grid)):
        while lo < len(points) and points[lo] < grid[i] - SWITCH_WINDOW_MS:
            lo += 1
        while hi < len(points) and points[hi] <= grid[i] + SWITCH_WINDOW_MS:
            hi += 1
        switch_curve[i] = (
            (cumulative[hi] - cumulative[lo]) / (hi - lo) if hi > lo else 0.0
        )
    for i in range(len(sync)):
        a = _clamp(0.5 * (able[0][i] + able[1][i]), 0.0, 1.0)
        sync[i] = _clamp(
            (1.0 - SWITCH_MIX) * a + SWITCH_MIX * (1.0 - switch_curve[i]), 0.0, 1.0
        )
    return sync


def _combine_hands(strain: list[list[float]], sync: list[float]) -> list[float]:
    out = _zeros(len(strain[0]))
    for i in range(len(out)):
        a = max(strain[0][i], 0.0)
        b = max(strain[1][i], 0.0)
        hi = max(a, b)
        if hi <= 0.0:
            continue
        if min(a, b) <= 0.0:
            out[i] = hi
            continue
        s = _clamp(sync[i], 0.0, 1.0)
        p = HAND_P_ALT + (HAND_P_SYNC - HAND_P_ALT) * s
        lo = min(a, b) / hi
        out[i] = hi * math.pow(1.0 + math.pow(lo, p), 1.0 / p)
    return out


# ── 长条代价：释放时机、每个 hold 的固定权重、按住时另一列被按下 ──────────────
HOLD_PRESS_W = [
    [0.00, 1.00, 0.20, 0.15],
    [1.00, 0.00, 0.20, 0.20],
    [0.20, 0.20, 0.00, 1.00],
    [0.15, 0.20, 1.00, 0.00],
]
LN_WEIGHT = 0.05
REL_GAIN = 0.75
REL_MID = 0.75
REL_GAP_WEIGHT = 0.5
LX_GAIN = 0.8
LX_RAMP_MS = 150.0
LX_STACK = 1.0


def _hold_costs(
    x: float,
    by_column: list[list[dict[str, Any]]],
    note_sequence: list[dict[str, Any]],
    grid: list[float],
) -> dict[str, list[float]]:
    tail_sequence = [note for note in note_sequence if note["t"] >= 0]
    tail_sequence.sort(key=lambda note: note["t"])
    release_step = _zeros(len(grid))
    weight_step = _zeros(len(grid))
    cross_step = _zeros(len(grid))
    inv_x = 1.0 / x

    def sigmoid(value: float) -> float:
        return 1.0 / (1.0 + math.exp(-5.0 * (value - REL_MID)))

    column_times = [_head_times(notes) for notes in by_column]

    # release：按超过 LN_TAP_MS 的 hold 长度与列内下一个头的间隔计分。
    releases: list[dict[str, Any]] = []
    intensities: list[float] = []
    for note in tail_sequence:
        length = note["t"] - note["h"]
        if length <= LN_TAP_MS:
            continue
        next_head = 1e9
        times = column_times[note["k"]]
        index = _lower_bound(times, note["h"])
        if index + 1 < len(times):
            next_head = times[index + 1]
        s_head = sigmoid(0.001 * (length - LN_TAP_MS) * inv_x)
        s_tail = sigmoid(0.001 * max(next_head - note["t"], 0.0) * inv_x)
        releases.append(note)
        intensities.append((s_head + REL_GAP_WEIGHT * s_tail) / (1.0 + REL_GAP_WEIGHT))
    for i in range(len(releases) - 1):
        t_start = releases[i]["t"]
        t_end = releases[i + 1]["t"]
        if t_end <= t_start:
            continue
        delta = 0.001 * (t_end - t_start)
        value = (
            REL_GAIN
            * 0.08
            / math.sqrt(delta)
            * inv_x
            * (1.0 + 0.8 * (intensities[i] + intensities[i + 1]))
        )
        _add_span(release_step, grid, t_start, t_end, value)

    # weight：每个 hold 在头上给一个固定权重。
    for note in note_sequence:
        if note["t"] < 0:
            continue
        _add_span(weight_step, grid, note["h"], note["h"] + 1.0, 1000.0 * LN_WEIGHT)

    # cross：每次按下与另一列仍存活的 hold 计代价，LX_RAMP_MS 内渐入。
    holds: list[list[dict[str, Any]]] = [[], [], [], []]
    for k in range(4):
        for note in by_column[k]:
            if note["t"] >= 0:
                holds[k].append(note)
    cursor = [0, 0, 0, 0]
    for press in note_sequence:
        t = press["h"]
        total = 0.0
        worst = 0.0
        for k in range(4):
            if k == press["k"]:
                continue
            column_holds = holds[k]
            while cursor[k] < len(column_holds) and column_holds[cursor[k]]["t"] < t:
                cursor[k] += 1
            if cursor[k] >= len(column_holds):
                continue
            hold = column_holds[cursor[k]]
            d = min(t - hold["h"], hold["t"] - t)
            if d <= 0.0:
                continue
            pair = HOLD_PRESS_W[k][press["k"]] * min(1.0, d / LX_RAMP_MS)
            total += pair
            worst = max(worst, pair)
        if total <= 0.0:
            continue
        accumulated = worst + LX_STACK * (total - worst)
        _add_span(cross_step, grid, t, t + 1.0, 1000.0 * LX_GAIN * accumulated)

    return {
        "rel": _window_sum(grid, release_step, WINDOW_MS, 0.001),
        "weight": _window_sum(grid, weight_step, WINDOW_MS, 0.001),
        "cross": _window_sum(grid, cross_step, WINDOW_MS, 0.001),
    }


# ── 期望准确率聚合 ──────────────────────────────────────────────────────────
RATING_SCALE = 7.528655953984781
AGG_POWER = 3.8724
AGG_TARGET_LOSS = 0.02
SOLVE_STEPS = 40
NOTE_DAMP_N = 60.0
SCALE_A = 30.0
SCALE_C = 290.0


def _bin_strain(strain: list[float]) -> tuple[list[int], list[float]]:
    bins = [-1] * len(strain)
    lo = math.log(1e-4)
    step = math.log(1.01)
    groups: dict[int, list[int]] = {}
    for i, value in enumerate(strain):
        if not (value > 1e-4):
            continue
        key = int((math.log(value) - lo) / step)
        groups.setdefault(key, []).append(i)
    keys = sorted(groups)
    dp: list[float] = []
    for key in keys:
        indexes = groups[key]
        total = 0.0
        for index in indexes:
            total += strain[index]
        for index in indexes:
            bins[index] = len(dp)
        dp.append(math.pow(total / len(indexes), AGG_POWER))
    return bins, dp


def _solve_skill(bin_weights: list[float], dp: list[float], mean_weight: float) -> float:
    target = AGG_TARGET_LOSS * mean_weight
    capacity = 0.0
    max_dp = 0.0
    for b in range(len(bin_weights)):
        if bin_weights[b] > 0.0:
            capacity += bin_weights[b]
            max_dp = max(max_dp, dp[b])
    if capacity <= target or max_dp <= 0.0:
        return 0.0
    lo = math.log(max_dp) - 200.0
    hi = math.log(max_dp) + 60.0
    for _ in range(SOLVE_STEPS):
        mid = 0.5 * (lo + hi)
        inv = math.exp(-mid)
        loss = 0.0
        for b in range(len(bin_weights)):
            if bin_weights[b] > 0.0:
                loss += bin_weights[b] * (1.0 - math.exp(-0.05 * dp[b] * inv))
        if loss > target:
            lo = mid
        else:
            hi = mid
    return math.exp(0.5 * (lo + hi) / AGG_POWER)


def _rating_from_bins(
    binned: tuple[list[int], list[float]], weights: list[float], total_notes: int
) -> float:
    bins, dp = binned
    total_weight = 0.0
    for weight in weights:
        total_weight += weight
    if total_weight <= 0.0:
        return 0.0
    bin_weights = _zeros(len(dp))
    for i, weight in enumerate(weights):
        if bins[i] >= 0:
            bin_weights[bins[i]] += weight
    raw = _solve_skill(bin_weights, dp, total_weight)
    raw *= total_notes / (total_notes + NOTE_DAMP_N)
    return raw * 0.975 * RATING_SCALE


def _note_weights(grid: list[float], notes: list[dict[str, Any]]) -> list[float]:
    times = _head_times(notes)
    n = len(grid)
    weights = _zeros(n)
    lo = 0
    hi = 0
    for i in range(n):
        while lo < len(times) and times[lo] < grid[i] - WINDOW_MS:
            lo += 1
        while hi < len(times) and times[hi] < grid[i] + WINDOW_MS:
            hi += 1
        if i == 0:
            gap = (grid[1] - grid[0]) / 2.0
        elif i == n - 1:
            gap = (grid[n - 1] - grid[n - 2]) / 2.0
        else:
            gap = (grid[i + 1] - grid[i - 1]) / 2.0
        weights[i] = (hi - lo) * gap
    return weights


def _rating_points(raw: float) -> float:
    return SCALE_A * math.log1p(raw / SCALE_C) if raw > 0.0 else 0.0


def _strain_points(strain: float) -> float:
    return _rating_points(strain * 0.975 * RATING_SCALE)


GRID_MS = 25.0
DUP_MS = 10
LN_W = 3.997
LN_X = 1.3275


def _analyse(notes: list[dict[str, Any]]) -> dict[str, Any]:
    sequence: list[dict[str, Any]] = []
    last = [-1, -1, -1, -1]
    for note in notes:
        j = last[note["k"]]
        if j >= 0 and note["h"] - sequence[j]["h"] <= DUP_MS:
            sequence[j]["t"] = max(sequence[j]["t"], note["t"])
            continue
        last[note["k"]] = len(sequence)
        sequence.append(dict(note))
    if len(sequence) < 2:
        return {"rating": 0.0, "grid": [], "graph": []}

    by_column: list[list[dict[str, Any]]] = [[], [], [], []]
    by_hand: list[list[dict[str, Any]]] = [[], []]
    end = 0
    for note in sequence:
        by_column[note["k"]].append(note)
        by_hand[note["k"] // 2].append(note)
        end = max(end, note["h"], note["t"])
    grid: list[float] = []
    t = 0.0
    while t <= end + 1000.0:
        grid.append(t)
        t += GRID_MS
    x = _hit_window_unit()

    strain, able = _technique_strain(x, by_column, grid)

    # 每只手的 hold 代价加到按压 strain 上。
    for h in range(2):
        columns: list[list[dict[str, Any]]] = [[], [], [], []]
        for c in range(2 * h, 2 * h + 2):
            columns[c] = by_column[c]
        holds = _hold_costs(x, columns, by_hand[h], grid)
        for i in range(len(grid)):
            ln_cost = holds["rel"][i] + holds["weight"][i] + holds["cross"][i]
            if ln_cost > 0.0:
                strain[h][i] += LN_W * math.pow(ln_cost, LN_X)
    rested = [list(values) for values in strain]

    # 体力（每只手）。
    weights = [_note_weights(grid, by_hand[0]), _note_weights(grid, by_hand[1])]
    _apply_stamina(grid, strain, weights)

    # 合并双手并聚合。
    rows = _build_rows(sequence)
    sync = _hand_sync(able, rows, grid)
    combined = _combine_hands(strain, sync)
    graph = [_strain_points(value) for value in _combine_hands(rested, sync)]

    overall_weights = _note_weights(grid, sequence)
    total_notes = len(sequence)
    binned = _bin_strain(combined)
    raw = _rating_from_bins(binned, overall_weights, total_notes)

    return {"rating": _rating_points(raw), "grid": grid, "graph": graph}


# ── rating → dan 标定（节点间线性插值）───────────────────────────────────────
# C++ 的 rating 是 0–100 显示值；上游的 rating→dan 标定未随公开源码发布，
# 这里用作者发布的参考输出重建一条只依赖 rating 的单调折线。
XDC1_SCOPE_MIN_RATING = 56.2281

XDC1_RATING_DAN_KNOTS: list[tuple[float, float]] = [
    (56.2457, 10.5),
    (56.2855, 10.52),
    (56.4662, 10.58),
    (56.6748, 10.66),
    (56.6979, 10.66),
    (56.8091, 10.7),
    (56.9228, 10.75),
    (56.9387, 10.75),
    (56.9793, 10.77),
    (56.9979, 10.77),
    (57.0081, 10.78),
    (57.2723, 10.88),
    (57.7027, 11.03),
    (57.7613, 11.06),
    (57.8102, 11.07),
    (57.8729, 11.1),
    (58.0741, 11.17),
    (58.0859, 11.18),
    (58.8904, 11.47),
    (59.0046, 11.52),
    (59.1394, 11.56),
    (59.2864, 11.62),
    (59.3629, 11.64),
    (59.5332, 11.71),
    (59.7566, 11.78),
    (59.9043, 11.84),
    (59.9836, 11.86),
    (60.4924, 12.04),
    (60.8486, 12.15),
    (61.1076, 12.24),
    (61.225, 12.27),
    (61.3015, 12.3),
    (61.3909, 12.32),
    (61.8702, 12.47),
    (62.0354, 12.51),
    (62.1477, 12.55),
    (62.2152, 12.56),
    (62.2251, 12.57),
    (62.4736, 12.64),
    (62.5819, 12.66),
    (62.7811, 12.72),
    (62.9239, 12.75),
    (63.1747, 12.82),
    (63.2892, 12.84),
    (63.6497, 12.93),
    (64.0341, 13.01),
    (64.0417, 13.02),
    (64.1167, 13.03),
    (64.2274, 13.06),
    (64.6646, 13.14),
    (64.6774, 13.15),
    (64.776, 13.17),
    (64.9719, 13.2),
    (65.1055, 13.23),
    (65.1436, 13.23),
    (65.1539, 13.24),
    (65.2878, 13.26),
    (65.3145, 13.27),
    (65.4167, 13.28),
    (65.7317, 13.34),
    (65.7761, 13.34),
    (65.7848, 13.35),
    (65.8349, 13.35),
    (66.0271, 13.39),
    (66.147, 13.4),
    (66.3024, 13.43),
    (66.3418, 13.43),
    (66.3663, 13.44),
    (66.5209, 13.46),
    (66.5409, 13.47),
    (66.6634, 13.48),
    (66.7362, 13.5),
    (66.7933, 13.5),
    (66.8095, 13.51),
    (66.8476, 13.51),
    (66.8772, 13.52),
    (67.2771, 13.57),
    (67.5118, 13.61),
    (67.5686, 13.61),
    (67.7197, 13.64),
    (67.7625, 13.64),
    (67.7925, 13.65),
    (67.9381, 13.67),
    (67.9881, 13.67),
    (68.0871, 13.69),
    (68.1492, 13.69),
    (68.1598, 13.7),
    (68.2924, 13.71),
    (68.3093, 13.72),
    (68.38, 13.72),
    (68.4731, 13.74),
    (68.615, 13.75),
    (68.6215, 13.76),
    (68.7583, 13.77),
    (68.7744, 13.78),
    (68.8377, 13.78),
    (68.8557, 13.79),
    (68.9151, 13.79),
    (68.9306, 13.8),
    (69.0069, 13.8),
    (69.017, 13.81),
    (69.0842, 13.81),
    (69.1041, 13.82),
    (69.1629, 13.82),
    (69.175, 13.83),
    (69.2287, 13.83),
    (69.248, 13.84),
    (69.3271, 13.84),
    (69.3657, 13.85),
    (69.4067, 13.85),
    (69.4107, 13.86),
    (69.4818, 13.86),
    (69.5068, 13.87),
    (69.5477, 13.87),
    (69.5719, 13.88),
    (69.6477, 13.88),
    (69.6548, 13.89),
    (69.7284, 13.89),
    (69.7482, 13.9),
    (69.8116, 13.9),
    (69.8224, 13.91),
    (69.8932, 13.91),
    (69.92, 13.92),
    (69.9782, 13.92),
    (69.9869, 13.93),
    (70.0357, 13.93),
    (70.0666, 13.94),
    (70.1457, 13.94),
    (70.1506, 13.95),
    (70.2254, 13.95),
    (70.244, 13.96),
    (70.3066, 13.96),
    (70.3194, 13.97),
    (70.3934, 13.97),
    (70.402, 13.98),
    (70.4753, 13.98),
    (70.4834, 13.99),
    (70.5603, 13.99),
    (70.5692, 14),
    (70.647, 14),
    (70.65, 14.01),
    (70.7332, 14.01),
    (70.7368, 14.02),
    (70.8105, 14.02),
    (70.8187, 14.03),
    (70.8975, 14.03),
    (70.9041, 14.04),
    (70.9857, 14.04),
    (70.9969, 14.05),
    (71.053, 14.05),
    (71.0759, 14.06),
    (71.1564, 14.06),
    (71.1613, 14.07),
    (71.2388, 14.07),
    (71.2423, 14.08),
    (71.3266, 14.08),
    (71.3522, 14.09),
    (71.4048, 14.09),
    (71.4122, 14.1),
    (71.5797, 14.11),
    (71.6064, 14.12),
    (71.6637, 14.12),
    (71.6789, 14.13),
    (71.751, 14.13),
    (71.7559, 14.14),
    (71.8359, 14.14),
    (71.8491, 14.15),
    (71.922, 14.15),
    (71.9238, 14.16),
    (72.0061, 14.16),
    (72.0124, 14.17),
    (72.0811, 14.17),
    (72.0966, 14.18),
    (72.1747, 14.18),
    (72.1799, 14.19),
    (72.257, 14.19),
    (72.2684, 14.2),
    (72.3338, 14.2),
    (72.35, 14.21),
    (72.4286, 14.21),
    (72.4397, 14.22),
    (72.5129, 14.22),
    (72.5221, 14.23),
    (72.5981, 14.23),
    (72.6134, 14.24),
    (72.6868, 14.24),
    (72.6932, 14.25),
    (72.7629, 14.25),
    (72.7733, 14.26),
    (72.8507, 14.26),
    (72.8653, 14.27),
    (72.9365, 14.27),
    (72.9603, 14.28),
    (73.0111, 14.28),
    (73.0397, 14.29),
    (73.0927, 14.29),
    (73.3052, 14.32),
    (73.3518, 14.32),
    (73.3702, 14.33),
    (73.4169, 14.33),
    (73.5323, 14.35),
    (73.5941, 14.35),
    (73.6983, 14.37),
    (73.7752, 14.37),
    (73.8081, 14.38),
    (73.8526, 14.38),
    (73.8734, 14.39),
    (74.1039, 14.41),
    (74.1103, 14.42),
    (74.1779, 14.42),
    (74.1987, 14.43),
    (74.3418, 14.44),
    (74.3572, 14.45),
    (74.5098, 14.46),
    (74.5352, 14.47),
    (74.9719, 14.52),
    (75.0777, 14.54),
    (75.3078, 14.56),
    (75.3196, 14.57),
    (75.3833, 14.57),
    (75.4193, 14.58),
    (75.7882, 14.63),
    (75.906, 14.64),
    (75.9489, 14.65),
    (76.001, 14.65),
    (76.0137, 14.66),
    (76.2776, 14.69),
    (76.3135, 14.7),
    (76.3765, 14.7),
    (76.4059, 14.71),
    (76.6656, 14.74),
    (76.688, 14.75),
    (76.7485, 14.75),
    (76.7591, 14.76),
    (77.0198, 14.79),
    (77.1932, 14.82),
    (77.2617, 14.82),
    (77.2816, 14.83),
    (77.746, 14.89),
    (77.9723, 14.93),
    (78.1229, 14.95),
    (78.1682, 14.95),
    (78.1856, 14.96),
    (78.4403, 14.99),
    (78.4634, 15),
    (78.7372, 15.04),
    (78.7869, 15.04),
    (78.7955, 15.05),
    (78.9889, 15.07),
    (79.3872, 15.14),
    (79.4355, 15.14),
    (79.5183, 15.16),
    (79.6351, 15.17),
    (79.8522, 15.21),
    (79.896, 15.21),
    (79.9137, 15.22),
    (80.0735, 15.24),
    (80.0883, 15.25),
    (80.1513, 15.26),
    (80.2043, 15.26),
    (80.2763, 15.28),
    (80.4111, 15.3),
    (80.4514, 15.3),
    (80.4731, 15.31),
    (80.7166, 15.35),
    (80.7612, 15.35),
    (80.7761, 15.36),
    (81.1938, 15.42),
    (81.3234, 15.45),
    (81.484, 15.47),
    (81.5002, 15.48),
    (81.7908, 15.53),
    (81.8287, 15.53),
    (81.9506, 15.55),
    (82.4888, 15.65),
    (82.7535, 15.69),
    (82.7743, 15.7),
    (82.8119, 15.7),
    (83.1718, 15.77),
    (83.3822, 15.8),
    (83.6818, 15.86),
    (83.9397, 15.9),
    (83.9539, 15.91),
    (84.23, 15.96),
    (84.2587, 15.96),
    (84.2792, 15.97),
    (84.3806, 15.98),
    (85.0276, 16.1),
    (85.2025, 16.14),
    (85.6174, 16.21),
    (86.5663, 16.39),
    (86.838, 16.45),
    (86.8875, 16.45),
    (89.0059, 16.86),
    (91.2128, 17.26),
    (91.3217, 17.27),
    (92.4651, 17.46),
    (94.525, 17.77),
    (97.0001, 18.11),
    (97.8078, 18.23),
    (98.3042, 18.29),
    (100.2364, 18.56),
]


def xdc1_rating_to_dan(rating: float) -> float:
    try:
        value = float(rating)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(value) or value <= 0:
        return 0.0
    if value < XDC1_SCOPE_MIN_RATING:
        # 图曲线专用：Alpha Low 以下按 (0,0)→(56.2281,10.5) 线性延伸，保持形状。
        return value * (10.5 / XDC1_SCOPE_MIN_RATING)
    knots = XDC1_RATING_DAN_KNOTS
    if value <= knots[0][0]:
        return knots[0][1]
    last = len(knots) - 1
    if value >= knots[last][0]:
        return knots[last][1]
    lo = 0
    hi = last
    while hi - lo > 1:
        mid = (lo + hi) >> 1
        if knots[mid][0] <= value:
            lo = mid
        else:
            hi = mid
    x0, y0 = knots[lo]
    x1, y1 = knots[hi]
    return y0 + ((value - x0) / (x1 - x0)) * (y1 - y0)


def _star_from_dan(dan: float) -> float:
    return 3.4 + 0.38 * dan


def _build_notes(parsed: list[Any], speed_rate: float) -> list[dict[str, Any]]:
    rate = speed_rate if float(speed_rate or 0) > 0 else 1.0
    columns = parsed[1]
    starts = parsed[2]
    ends = parsed[3]
    types = parsed[4]
    notes: list[dict[str, Any]] = []
    for i in range(len(starts)):
        column = int(columns[i])
        head = float(starts[i])
        tail = float(ends[i]) if (int(types[i]) & 128) != 0 else -1.0
        if rate != 1.0:
            head = math.floor(head / rate)
            if tail >= 0:
                tail = math.floor(tail / rate)
        if head < 0:
            continue
        if tail >= 0 and tail < head:
            tail = -1.0
        notes.append({"k": column, "h": head, "t": tail})
    notes.sort(key=lambda note: (note["h"], note["k"]))
    return notes


def _unsupported_result(
    column_count: int, ln_ratio: float, reason: str
) -> dict[str, Any]:
    return {
        "star": math.nan,
        "lnRatio": ln_ratio,
        "columnCount": column_count,
        "graph": None,
        "estDiff": f"Unsupported: {reason}",
        "numericDifficulty": None,
        "numericDifficultyHint": None,
        "rawNumericDifficulty": None,
        "actualEstimatorAlgorithm": "XDC1",
        "unsupported": True,
    }


def estimate_xdc1_result(
    source: Any,
    speed_rate: float = 1.0,
    od_flag: Any = None,
    cvt_flag: Any = None,
    *,
    chart: Any = None,
    with_graph: bool = False,
) -> dict[str, Any]:
    """JS ``runXdc1EstimatorFromText`` 直译（路径式入口）。

    ``chart`` 可传入已解析谱面以复用解析结果；IN/HO 会先 clone 再转换，
    保证共享谱面不被改写（与 JS ``cloneOsuParser`` 同语义）。
    固定 OD9 判定窗，``od_flag`` 仅保留签名兼容。
    """
    del od_flag  # XDC1 固定 OD9，不读显式 OD

    if chart is not None:
        parser_obj = chart.clone()
    else:
        from .shared import load_osu_chart

        parser_obj = load_osu_chart(resolve_chart_path(source))

    normalized = str(cvt_flag or "").strip().upper()
    if "IN" in normalized or "HO" in normalized:
        try:
            if "IN" in normalized:
                parser_obj.mod_IN()
            if "HO" in normalized:
                parser_obj.mod_HO()
        except Exception:  # noqa: BLE001 - 与 JS 转换失败保留未转换 clone 同语义
            pass

    parsed = parser_obj.get_parsed_data()
    column_count = int(float(parsed[0] or 0))
    ln_ratio = float(parsed[8] or 0.0)
    status = str(parsed[7] or "")

    if column_count != 4:
        return _unsupported_result(column_count, ln_ratio, "4K only")
    if status in ("Fail", "NotMania"):
        return _unsupported_result(column_count, ln_ratio, "parse failed")

    notes = _build_notes(parsed, speed_rate)
    if len(notes) < 2:
        return _unsupported_result(column_count, ln_ratio, "too few notes")

    analysis = _analyse(notes)
    rating = float(analysis["rating"])
    if not math.isfinite(rating):
        return _unsupported_result(column_count, ln_ratio, "calculation failed")
    if rating < XDC1_SCOPE_MIN_RATING:
        return _unsupported_result(column_count, ln_ratio, "below Alpha Low")

    calibrated_dan = xdc1_rating_to_dan(rating)
    numeric_difficulty = js_fixed(calibrated_dan, 2)
    # XDC1 只负责 RC 半段；LN 半段由 Mixed 拼接 Sunny 的 LN 区间表结果。
    rc_label = (
        "Alpha low" if calibrated_dan < 10.52 else numeric_to_rc_label(calibrated_dan)
    )

    graph = None
    if with_graph and analysis["grid"]:
        graph = {
            "times": analysis["grid"],
            "values": [
                _star_from_dan(xdc1_rating_to_dan(value)) for value in analysis["graph"]
            ],
        }

    return {
        "star": js_fixed(_star_from_dan(calibrated_dan), 4),
        "lnRatio": ln_ratio,
        "columnCount": column_count,
        "graph": graph,
        "estDiff": rc_label,
        "numericDifficulty": numeric_difficulty,
        "numericDifficultyHint": "xdc1-v1",
        "rawNumericDifficulty": js_fixed(rating, 4),
        "actualEstimatorAlgorithm": "XDC1",
    }
