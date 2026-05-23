from __future__ import annotations

import math
from typing import Any

from .shared import load_osu_chart, resolve_chart_path
from ...data.estimator import estimator_data

AZUSA_CONFIG = estimator_data.AZUSA_CONFIG
GREEK_BY_INDEX = estimator_data.GREEK_BY_INDEX
RC_TIER_CANDIDATES = estimator_data.RC_TIER_CANDIDATES
AZUSA_CALIBRATION_LOW_BLOCKS = estimator_data.AZUSA_CALIBRATION_LOW_BLOCKS
AZUSA_CALIBRATION_HIGH_BLOCKS = estimator_data.AZUSA_CALIBRATION_HIGH_BLOCKS
AZUSA_ISOTONIC_POINTS = estimator_data.AZUSA_ISOTONIC_POINTS

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _safe_div(a: float, b: float, fallback: float = 0.0) -> float:
    if not math.isfinite(a) or not math.isfinite(b) or abs(b) < 1e-9:
        return fallback
    return a / b


def _fmt4(v: float | None) -> float | None:
    if v is None or not math.isfinite(v):
        return None
    return round(v, 4)


def _piecewise_linear(x: float, knots: list[list[float]], value_col: int = 1) -> float:
    v = float(x)
    if not math.isfinite(v) or not knots:
        return v
    if v <= knots[0][0]:
        return knots[0][value_col]
    last = len(knots) - 1
    if v >= knots[last][0]:
        return knots[last][value_col]
    for i in range(last):
        x0, y0 = knots[i][0], knots[i][value_col]
        x1, y1 = knots[i + 1][0], knots[i + 1][value_col]
        if x0 <= v <= x1:
            return y0 + _safe_div((v - x0) * (y1 - y0), x1 - x0, 0.0)
    return v


def _piecewise_block(x: float, blocks: list[list[float]]) -> float:
    v = float(x)
    if not math.isfinite(v) or not blocks:
        return v
    if v <= blocks[0][0]:
        return blocks[0][2]
    last = len(blocks) - 1
    for i in range(len(blocks)):
        x0, x1, y = blocks[i]
        if x0 <= v <= x1:
            return y
        if i < last and x1 < v < blocks[i + 1][0]:
            t = _safe_div(v - x1, blocks[i + 1][0] - x1, 0.0)
            return y * (1.0 - t) + blocks[i + 1][2] * t
    return blocks[last][2]


def _format_rc_base_label(base: int) -> str:
    if base <= 0:
        return f"Intro {_clamp(base + 3, 1, 3)}"
    if base <= 10:
        return f"Reform {base}"
    return GREEK_BY_INDEX[_clamp(base - 11, 0, len(GREEK_BY_INDEX) - 1)]


def _numeric_to_rc_label(numeric: float) -> str:
    if not math.isfinite(numeric):
        return "Invalid"
    clamped = _clamp(float(numeric), -2.4, 20.4)
    best = None
    for base in range(-2, 21):
        for tier in RC_TIER_CANDIDATES:
            d = abs(clamped - (base + tier["offset"]))
            if best is None or d < best[0]:
                best = (d, base, tier["suffix"])
    if best is None:
        return "Invalid"
    return f"{_format_rc_base_label(best[1])} {best[2]}"


def _estimate_daniel_numeric(result: dict[str, Any] | None) -> float | None:
    if result is None:
        return None
    nr = result.get("numericDifficulty")
    if isinstance(nr, (int, float)) and math.isfinite(nr):
        return float(nr)
    if isinstance(nr, str) and nr.strip():
        try:
            return float(nr)
        except ValueError:
            pass
    star = float(result.get("star", math.nan))
    if not math.isfinite(star):
        return None
    if star >= 6.56:
        return round(11.0 + _clamp((star - 6.56) / 0.58, 0.0, 9.99), 2)
    return round(-2.0 + 13.0 * math.pow(_clamp(star / 6.56, 0.0, 1.0), 1.72), 2)


def _has_daniel_native_numeric(result: dict[str, Any] | None) -> bool:
    nr = result.get("numericDifficulty") if result else None
    if isinstance(nr, (int, float)):
        return math.isfinite(nr)
    if isinstance(nr, str) and nr.strip():
        try:
            return math.isfinite(float(nr))
        except ValueError:
            return False
    return False


def _estimate_sunny_numeric(result: dict[str, Any] | None) -> float | None:
    if result is None:
        return None
    star = float(result.get("star", math.nan))
    if not math.isfinite(star):
        return None
    return round(_clamp(2.85 + 1.33 * star, -2.0, 20.0), 2)


def _quantile_from_sorted(vals: list[float], q: float) -> float:
    if not vals:
        return 0.0
    t = _clamp(float(q), 0.0, 1.0) * (len(vals) - 1)
    left = int(math.floor(t))
    right = min(len(vals) - 1, left + 1)
    w = t - left
    return vals[left] * (1.0 - w) + vals[right] * w


def _power_mean(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    acc = sum(max(v, 0.0) ** p for v in vals)
    return (acc / len(vals)) ** (1.0 / p)


def _build_tap_notes(parsed: Any) -> list[dict[str, Any]]:
    columns = list(parsed[1]) if len(parsed) > 1 else []
    starts = list(parsed[2]) if len(parsed) > 2 else []
    taps: list[dict[str, Any]] = []
    for i in range(len(columns)):
        col = int(columns[i])
        time = float(starts[i])
        if not (0 <= col < 18 and math.isfinite(time)):
            continue
        taps.append({"t": time, "c": col, "hand": 0 if col < 2 else 1, "rowSize": 1})
    taps.sort(key=lambda n: (n["t"], n["c"]))
    return taps


def _annotate_rows(taps: list[dict[str, Any]], tolerance_ms: float) -> None:
    if not taps:
        return
    rs = 0
    for i in range(1, len(taps) + 1):
        if i < len(taps) and abs(taps[i]["t"] - taps[rs]["t"]) <= tolerance_ms:
            continue
        sz = i - rs
        for j in range(rs, i):
            taps[j]["rowSize"] = sz
        rs = i


def _exp_decay(dt_ms: float, tau_ms: float) -> float:
    if dt_ms <= 0.0:
        return 1.0
    return math.exp(-dt_ms / tau_ms)


def _skill_from_states(states: list[float], weights: list[float]) -> float:
    return sum(states[i] * weights[i] for i in range(len(states)))


def _build_difficulty_curve(taps: list[dict[str, Any]]) -> dict[str, Any]:
    nwin = len(AZUSA_CONFIG["decayWindowsMs"])
    st = {"spd": [0.0] * nwin, "sta": [0.0] * nwin, "chd": [0.0] * nwin,
          "tec": [0.0] * nwin, "jak": [0.0] * nwin}
    lbc, lbh = [-1e9] * 4, [-1e9, -1e9]
    d250, d500, jack_raw = [], [], []
    cc = [0, 0, 0, 0]
    cnc, c250, c500 = 0, 0, 0

    loc, sps, sts, chs, tes, jas, tms = [], [], [], [], [], [], []
    pt = taps[0]["t"] if taps else 0.0
    pa1, pa2, pc = -1e9, -1e9, 0

    for i, n in enumerate(taps):
        t, c = n["t"], n["c"]
        cc[c] += 1
        if n["rowSize"] >= 2:
            cnc += 1

        dg = max(0.0, t - pt) if i > 0 else 0.0
        ds = max(0.0, t - lbc[c])
        dh = max(0.0, t - lbh[n["hand"]])
        da = max(0.0, t - pa1)

        while c250 < i and t - taps[c250]["t"] > 250:
            c250 += 1
        while c500 < i and t - taps[c500]["t"] > 500:
            c500 += 1

        v250, v500 = (i - c250 + 1) / 0.25, (i - c500 + 1) / 0.5
        d250.append(v250); d500.append(v500)
        jv = (190.0 / (ds + 35.0)) ** 1.16
        jack_raw.append(jv)
        stream = (170.0 / (da + 30.0)) ** 1.07
        hstream = (185.0 / (dh + 42.0)) ** 1.08
        mv = abs(c - pc) / 3.0
        rr = _safe_div(max(da, 1.0), max(t - pa2, 1.0), 1.0)
        rc = abs(math.log2(_clamp(rr, 0.2, 5.0)))
        rch = max(0.0, n["rowSize"] - 1.0)
        ch = (rch + 1.0) ** 1.22 - 1.0

        si = 0.60 * stream + 0.30 * hstream + 0.10 * jv
        ji = jv * (1.0 + 0.15 * ch)
        sti = 0.48 * (v500 / 11.0) + 0.27 * (v250 / 15.0) + 0.25 * stream
        chi = ch * (1.0 + 0.10 * min(1.5, stream))
        ti = 0.45 * rc + 0.30 * mv + 0.25 * (1.0 + 0.3 * rch if rch > 0 else 0.0)

        for j in range(nwin):
            tau = AZUSA_CONFIG["decayWindowsMs"][j]
            dcy = _exp_decay(dg, tau)
            st["spd"][j] = st["spd"][j] * dcy + si
            st["sta"][j] = st["sta"][j] * dcy + sti
            st["chd"][j] = st["chd"][j] * dcy + chi
            st["tec"][j] = st["tec"][j] * dcy + ti
            st["jak"][j] = st["jak"][j] * dcy + ji

        dw = AZUSA_CONFIG["decayWeights"]
        ss = _skill_from_states(st["spd"], dw)
        sts_ = _skill_from_states(st["sta"], dw)
        cs_ = _skill_from_states(st["chd"], dw)
        ts_ = _skill_from_states(st["tec"], dw)
        js_ = _skill_from_states(st["jak"], dw)

        p = AZUSA_CONFIG["localPower"]
        sw = AZUSA_CONFIG["skillWeights"]
        sk = [
            sw["speed"] * max(ss, 0.0) ** p, sw["stamina"] * max(sts_, 0.0) ** p,
            sw["chord"] * max(cs_, 0.0) ** p, sw["tech"] * max(ts_, 0.0) ** p,
            sw["jack"] * max(js_, 0.0) ** p,
        ]
        combined = (sum(sk) / (sw["speed"] + sw["stamina"] + sw["chord"] + sw["tech"] + sw["jack"])) ** (1.0 / p)

        loc.append(combined); sps.append(ss); sts.append(sts_)
        chs.append(cs_); tes.append(ts_); jas.append(js_); tms.append(t)
        pa2, pa1, pt, pc = pa1, t, t, c
        lbc[c], lbh[n["hand"]] = t, t

    return {"local": loc, "speedSeries": sps, "staminaSeries": sts, "chordSeries": chs,
            "techSeries": tes, "jackSeries": jas, "times": tms, "density250": d250,
            "density500": d500, "jackRawSeries": jack_raw, "columnCounts": cc, "chordNoteCount": cnc}


def _compute_azusa_numeric_from_curve(curve: dict[str, Any], note_count: int) -> float:
    loc = curve.get("local", [])
    if not loc:
        return 0.0

    def summ(vals):
        sv = sorted(vals)
        q97 = _quantile_from_sorted(sv, 0.97); q94 = _quantile_from_sorted(sv, 0.94)
        q90 = _quantile_from_sorted(sv, 0.90); q75 = _quantile_from_sorted(sv, 0.75)
        q50 = _quantile_from_sorted(sv, 0.50)
        tc = max(8, int(len(sv) * 0.04))
        tl = sv[-tc:] if tc > 0 else sv
        tm = sum(tl) / len(tl) if tl else 0.0
        pm = _power_mean(vals, 2.6)
        return {"q97": q97, "q94": q94, "q90": q90, "q75": q75, "q50": q50, "tailMean": tm, "pm": pm}

    sp = summ(curve.get("speedSeries", [])); sta = summ(curve.get("staminaSeries", []))
    chd = summ(curve.get("chordSeries", [])); tec = summ(curve.get("techSeries", []))
    jak = summ(curve.get("jackSeries", []))

    d250 = _power_mean(curve.get("density250", []), 1.18)
    d500 = _power_mean(curve.get("density500", []), 1.12)
    lb = min(AZUSA_CONFIG["lengthCap"], (max(note_count, 1) / AZUSA_CONFIG["lengthRefNotes"]) ** AZUSA_CONFIG["lengthExponent"])

    peak = (0.26 * sp["q97"] + 0.22 * sta["q97"] + 0.10 * chd["q97"] + 0.10 * tec["q97"]
            + 0.10 * jak["q97"] + 0.06 * sp["q90"] + 0.04 * sta["q90"] + 0.02 * chd["q90"]
            + 0.02 * tec["q90"] + 0.02 * jak["q90"])
    sus = (0.18 * sp["q75"] + 0.16 * sta["q75"] + 0.08 * chd["q75"] + 0.06 * tec["q75"]
           + 0.08 * jak["q75"] + 0.10 * sp["tailMean"] + 0.08 * sta["tailMean"]
           + 0.04 * chd["tailMean"] + 0.04 * tec["tailMean"] + 0.04 * jak["tailMean"])
    den = 0.14 * math.log1p(d250) + 0.22 * math.log1p(d500)
    mid = 0.16 * sp["q50"] + 0.13 * sta["q50"] + 0.06 * chd["q50"] + 0.06 * tec["q50"] + 0.06 * jak["q50"]
    raw = 0.52 * peak + 0.26 * sus + 0.10 * den + 0.08 * mid + 0.04 * lb
    scaled = 0.82 + 0.43 * raw

    cc = curve.get("columnCounts", [0, 0, 0, 0])
    mc = max(cc) if cc else 0
    ai = _safe_div((mc / max(note_count, 1)) - 0.25, 0.75, 0.0)
    cr = _safe_div(curve.get("chordNoteCount", 0), max(note_count, 1), 0.0)
    js = sorted(curve.get("jackRawSeries", []))
    jq = _quantile_from_sorted(js, 0.95)

    cjb = _clamp(2.5 * _clamp((cr - 0.40) * 3.5, 0.0, 1.0) * _clamp((jq - 1.25) * 2.8, 0.0, 1.0)
                 * _clamp(1.0 - (ai * 8.0), 0.0, 1.0), 0.0, 2.2)

    tms = curve.get("times", [0.0, 1.0])
    tts = max(1.0, (tms[-1] - tms[0]) / 1000.0)
    nps = note_count / tts
    msb = _clamp((nps - 9.0) * 0.04, 0.0, 0.35) * _clamp((19.0 - nps) * 0.25, 0.0, 1.0)

    return _clamp(scaled + cjb + msb, -2.0, 20.0)


def _resolve_rc_blend_components(
    pn: float | None, dn: float | None, sn: float | None, hints: dict[str, Any] | None = None
) -> dict[str, Any]:
    p = pn if pn is not None and math.isfinite(pn) else None
    d = dn if dn is not None and math.isfinite(dn) else None
    s = sn if sn is not None and math.isfinite(sn) else None
    if d is None and p is None and s is None:
        return {"value": None, "lowGateSource": None, "lowGate": None, "highGate": None, "lowBase": None, "highBase": None}

    lgs = d if d is not None else (s if s is not None else p if p is not None else 0.0)
    lg = _clamp((9.61 - lgs) / 4.94, 0.0, 1.0)
    hg = 1.0 - lg

    lb_val = None
    if s is not None:
        v = -8.317 + 1.536 * s
        if p is not None: v += 0.011 * p
        if d is not None: v += 0.049 * d
        if lg > 0:
            pp = max(0.0, p - 10.4) if p is not None else 0.0
            sp = max(0.0, s - 9.84)
            lsc = max(0.0, 7.935 - s) ** 2
            v += lg * (0.442 * sp + 0.016 * pp + 0.235 * lsc)
        lb_val = v

    hb_val = None
    du = d if d is not None else (s if s is not None else p)
    if du is not None:
        pu = p if p is not None else du
        su = s if s is not None else du
        v = 0.809 * du + 0.057 * pu + 0.165 * su + 0.183
        hm = _clamp((lgs - 14.83) / 2.667, 0.0, 1.0)
        if hm > 0:
            v += hm * (-0.154 * max(0.0, pu - du) + 0.081 * max(0.0, su - du))
        if hints is not None:
            ai, cr, jq = hints.get("anchorImbalance"), hints.get("chordRate"), hints.get("jackQ95")
            if ai is not None and cr is not None and jq is not None and math.isfinite(ai) and math.isfinite(cr) and math.isfinite(jq):
                v += _clamp(0.20 * max(0.0, jq - 2.08) * max(0.0, 0.24 - cr) * max(0.0, ai - 0.10), 0.0, 0.25)
        hb_val = v

    ll = max(0.0, 9.889 - lgs) * 0.257 if math.isfinite(lgs) else 0.0
    if lb_val is None and hb_val is None:
        return {"value": None, "lowGateSource": lgs, "lowGate": lg, "highGate": hg, "lowBase": lb_val, "highBase": hb_val}
    if lb_val is None:
        return {"value": hb_val, "lowGateSource": lgs, "lowGate": lg, "highGate": hg, "lowBase": lb_val, "highBase": hb_val}
    if hb_val is None:
        return {"value": lb_val + ll, "lowGateSource": lgs, "lowGate": lg, "highGate": hg, "lowBase": lb_val, "highBase": hb_val}
    return {"value": (lb_val * lg) + ((hb_val + ll) * hg), "lowGateSource": lgs, "lowGate": lg, "highGate": hg, "lowBase": lb_val, "highBase": hb_val}


def _calibrate_azusa_numeric(value: float, lo: float | None = None, hi: float | None = None) -> float:
    if not math.isfinite(value):
        return value
    low = _piecewise_block(value, AZUSA_CALIBRATION_LOW_BLOCKS)
    high = _piecewise_block(value, AZUSA_CALIBRATION_HIGH_BLOCKS)
    lg = _clamp(float(lo), 0.0, 1.0) if lo is not None and math.isfinite(lo) else None
    hg_ = _clamp(float(hi), 0.0, 1.0) if hi is not None and math.isfinite(hi) else None
    if lg is None and hg_ is None:
        return low if value < 11 else high
    lw = lg if lg is not None else max(0.0, 1.0 - (hg_ or 0.0))
    hw = hg_ if hg_ is not None else max(0.0, 1.0 - lw)
    ws = lw + hw
    if ws <= 1e-6:
        return low if value < 11 else high
    return (lw * low + hw * high) / ws


def _calibrate_azusa_output_numeric(value: float) -> float:
    return _piecewise_linear(float(value), AZUSA_ISOTONIC_POINTS, 1)


def _compute_curve_gap_residual_correction(
    bn: float, bd: dict[str, Any] | None, cs: dict[str, Any] | None,
    pn: float | None, sn: float | None, dn: float | None,
) -> float:
    x = float(bn)
    if not math.isfinite(x):
        return 0.0
    hg = _clamp(float(bd.get("highGate", 0.0) if bd else 0.0), 0.0, 1.0)
    p = pn if (pn is not None and math.isfinite(pn)) else x
    s = sn if (sn is not None and math.isfinite(sn)) else x
    d = dn if (dn is not None and math.isfinite(dn)) else x
    ds, sp_ = d - s, s - p
    ai = cs.get("anchorImbalance", 0.0) if cs else 0.0
    cr = cs.get("chordRate", 0.0) if cs else 0.0
    jq = cs.get("jackQ95", 0.0) if cs else 0.0
    res = (4.335282 + (-0.170459 * x) + (-1.622303 * max(0.0, 11.0 - x))
           + (1.328125 * max(0.0, 12.5 - x)) + (-0.042829 * max(0.0, 14.0 - x))
           + (-0.834997 * hg) + (3.060352 * hg * max(0.0, 11.0 - x))
           + (-1.744638 * hg * max(0.0, 12.5 - x)) + (0.409922 * ds)
           + (0.041072 * sp_) + (-0.388231 * hg * ds) + (-0.170185 * hg * sp_)
           + (3.466868 * ai) + (-1.743778 * cr) + (-0.094758 * jq)
           + (2.626366 * ai * jq) + (1.836357 * cr * jq)
           + (-2.612648 * hg * ai) + (-2.493596 * hg * cr))
    return _clamp(res, -1.2, 1.2)


def _compute_reference_correction(ae: float, dn: float | None, sn: float | None) -> float:
    x = float(ae)
    if not math.isfinite(x) or x < 10.0 or x > 17.5:
        return 0.0
    if x < 11.5:
        gt, cd, cs_ = _clamp((x - 10.0) / 1.5, 0.0, 1.0), 0.10, 0.06
    elif x < 12.5:
        gt, cd, cs_ = 1.0, 0.20, 0.13
    elif x < 16.0:
        gt, cd, cs_ = 1.0, 0.40, 0.25
    else:
        gt, cd, cs_ = _clamp((17.5 - x) / 1.5, 0.0, 1.0), 0.28, 0.17
    corr = 0.0
    if dn is not None and math.isfinite(dn):
        corr += cd * (dn - x)
    if sn is not None and math.isfinite(sn):
        corr += cs_ * (sn - x)
    return _clamp(corr * gt, -1.2, 1.2)


def _build_error_result(code: str, msg: str, ln: float = 0.0, cc: int = 0) -> dict[str, Any]:
    return {"star": math.nan, "lnRatio": ln, "columnCount": cc,
            "estDiff": f"Invalid: {msg}", "numericDifficulty": None,
            "numericDifficultyHint": code, "graph": None, "rawNumericDifficulty": None,
            "debug": {"code": code, "message": msg}}


def estimate_azusa_result(
    source: Any, speed_rate: float = 1.0, od_flag: Any = None, cvt_flag: Any = None,
    *, sunny_result: dict[str, Any] | None = None, daniel_result: dict[str, Any] | None = None,
    with_graph: bool = False, force_sunny_reference_ho: bool = True,
) -> dict[str, Any]:
    chart = load_osu_chart(resolve_chart_path(source))
    parsed = chart.get_parsed_data()
    ln_ratio = float(parsed[8] or 0) if len(parsed) > 8 else 0.0
    column_count = int(parsed[0] or 0) if len(parsed) > 0 else 0
    status = str(parsed[7] or "") if len(parsed) > 7 else ""

    if status == "Fail":
        return _build_error_result("ParseFailed", "Beatmap parse failed", ln_ratio, column_count)
    if status == "NotMania":
        return _build_error_result("NotMania", "Beatmap mode is not mania", ln_ratio, column_count)
    if column_count != 4:
        return _build_error_result("UnsupportedKeys", "Azusa only supports 4K", ln_ratio, column_count)

    taps = _build_tap_notes(parsed)
    if len(taps) < AZUSA_CONFIG["minNotes"]:
        return _build_error_result("TooShort", f"Insufficient notes for stable estimate ({len(taps)})", ln_ratio, column_count)

    ts = 1.0 / speed_rate if speed_rate != 0 else 1.0
    _annotate_rows(taps, AZUSA_CONFIG["rowToleranceMs"] * ts)
    if ts != 1.0:
        taps = [{"t": n["t"] * ts, "c": n["c"], "hand": n["hand"], "rowSize": n["rowSize"]} for n in taps]
        _annotate_rows(taps, AZUSA_CONFIG["rowToleranceMs"])

    curve = _build_difficulty_curve(taps)
    primary_numeric = _compute_azusa_numeric_from_curve(curve, len(taps))
    note_count = len(taps)

    cc = curve.get("columnCounts", [0, 0, 0, 0])
    mc = max(cc) if cc else 0
    ai = _safe_div((mc / max(note_count, 1)) - 0.25, 0.75, 0.0)
    cr = _safe_div(curve.get("chordNoteCount", 0), max(note_count, 1), 0.0)
    js = sorted(curve.get("jackRawSeries", []))
    jq = _quantile_from_sorted(js, 0.95)

    daniel_numeric = None; daniel_result_val = daniel_result; daniel_has_native = False
    sunny_numeric = None; sunny_result_val = sunny_result

    if daniel_result is not None:
        daniel_numeric = _estimate_daniel_numeric(daniel_result)
        daniel_has_native = _has_daniel_native_numeric(daniel_result)
    else:
        try:
            from .daniel import estimate_daniel_result as _dr
            daniel_result_val = _dr(source, speed_rate, od_flag, cvt_flag)
            daniel_numeric = _estimate_daniel_numeric(daniel_result_val)
            daniel_has_native = _has_daniel_native_numeric(daniel_result_val)
        except Exception:
            pass

    if sunny_result_val is not None:
        sunny_numeric = _estimate_sunny_numeric(sunny_result_val)
    else:
        try:
            from .sunny import estimate_sunny_result as _sr
            sunny_result_val = _sr(source, speed_rate, od_flag, "HO" if force_sunny_reference_ho else cvt_flag)
            sunny_numeric = _estimate_sunny_numeric(sunny_result_val)
        except Exception:
            pass

    dnfb = daniel_numeric
    if not daniel_has_native and daniel_numeric is not None and math.isfinite(daniel_numeric):
        hs = max(
            primary_numeric if math.isfinite(primary_numeric) else float("-inf"),
            sunny_numeric if sunny_numeric is not None and math.isfinite(sunny_numeric) else float("-inf"),
            daniel_numeric,
        )
        if hs < 14.0:
            sd = speed_rate - 1.0
            fs = _clamp(-sd * 0.43, 0.0, 1.0) if sd < 0 else _clamp(sd * 0.35, 0.0, 1.0)
            dnfb = daniel_numeric * fs

    blend = _resolve_rc_blend_components(primary_numeric, dnfb, sunny_numeric, {"anchorImbalance": ai, "chordRate": cr, "jackQ95": jq})
    nd = blend["value"]
    cal = _calibrate_azusa_numeric(nd, blend["lowGate"], blend["highGate"])
    cgr = _compute_curve_gap_residual_correction(cal, blend, {"anchorImbalance": ai, "chordRate": cr, "jackQ95": jq}, primary_numeric, sunny_numeric, dnfb)
    pre = _clamp(float(cal) + cgr, -2.0, 20.0)
    out = _calibrate_azusa_output_numeric(pre)
    ref = _compute_reference_correction(out, dnfb, sunny_numeric)
    final = _clamp(float(out) + ref, -2.0, 20.0)
    est_diff = _numeric_to_rc_label(final)

    return {
        "star": round(3.4 + 0.38 * final, 4), "lnRatio": ln_ratio, "columnCount": column_count,
        "estDiff": est_diff, "numericDifficulty": round(final, 2),
        "numericDifficultyHint": "azusa-rc-v1",
        "graph": sunny_result_val.get("graph") if (with_graph and sunny_result_val) else None,
        "rawNumericDifficulty": round(primary_numeric, 4),
        "debug": {
            "primaryNumeric": _fmt4(primary_numeric), "blendNumeric": _fmt4(nd),
            "danielNumeric": _fmt4(daniel_numeric), "danielNumericForBlend": _fmt4(dnfb),
            "danielHasNativeNumeric": daniel_has_native, "sunnyNumeric": _fmt4(sunny_numeric),
            "notes": note_count, "calibratedNumeric": _fmt4(cal),
            "curveStats": {"anchorImbalance": _fmt4(ai), "chordRate": _fmt4(cr), "jackQ95": _fmt4(jq)},
            "curveGapResidual": _fmt4(cgr), "outputNumeric": _fmt4(out),
            "postCurveGapResidual": _fmt4(ref), "finalNumeric": _fmt4(final),
            "blend": {"lowGateSource": f"{blend.get('lowGateSource', 0):.4f}" if blend.get("lowGateSource") is not None else None,
                      "lowGate": f"{blend.get('lowGate', 0):.4f}" if blend.get("lowGate") is not None else None,
                      "highGate": f"{blend.get('highGate', 0):.4f}" if blend.get("highGate") is not None else None,
                      "lowBase": f"{blend.get('lowBase', 0):.4f}" if blend.get("lowBase") is not None else None,
                      "highBase": f"{blend.get('highBase', 0):.4f}" if blend.get("highBase") is not None else None},
        },
    }
