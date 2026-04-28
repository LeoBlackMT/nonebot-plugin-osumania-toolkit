import numpy as np
from nonebot import get_plugin_config

from ..matching.matching import match_notes_and_presses
from ...config import Config
from ...parser.osr_file_parser import osr_file
from ...parser.osu_file_parser import osu_file
from ...parser.ruleset_file_parser import ruleset_file
from .delta_chord import detect_chord_near_zero_cluster, detect_chord_sync_template
from .delta_context import detect_gap_ghost_context_v2
from .delta_correlation import detect_column_autocorr_and_drift, detect_cross_correlation
from .delta_memory import detect_ar1_memory_pattern, detect_fatigue_trend, detect_nonlinear_memory
from .helpers import build_chord_groups
from .types import AnalysisResult, Signal

config = get_plugin_config(Config)

_SCOREV2_MOD_BIT = 536870912


def _has_scorev2_mod(osr_obj: osr_file) -> bool:
    mod_value = int(getattr(osr_obj, "mod", 0) or 0)
    if mod_value & _SCOREV2_MOD_BIT:
        return True

    mods = getattr(osr_obj, "mods", [])
    if isinstance(mods, list):
        return any(str(m).lower() == "scorev2" for m in mods)
    return False


def _build_default_rulesets(osu_obj: osu_file, osr_obj: osr_file) -> list[ruleset_file]:
    od_value = float(getattr(osu_obj, "od", 8.0) or 8.0)
    prefer_sv2 = _has_scorev2_mod(osr_obj)
    order = ["osu-sv2", "osu"] if prefer_sv2 else ["osu", "osu-sv2"]

    built: list[ruleset_file] = []
    for name in order:
        rs = ruleset_file(("template", name, od_value))
        if rs.status == "OK":
            built.append(rs)
    return built


def _match_for_delta(osr_obj: osr_file, osu_obj: osu_file) -> dict:
    fallback_result: dict | None = None
    first_error: str | None = None

    for rs in _build_default_rulesets(osu_obj, osr_obj):
        for use_chart_time in (True, False):
            match_result = match_notes_and_presses(
                osu_obj,
                osr_obj,
                rs,
                use_chart_time=use_chart_time,
            )
            if match_result.get("status") != "OK":
                if first_error is None:
                    first_error = str(match_result.get("error") or "未知错误")
                continue

            if match_result.get("delta_list"):
                return match_result

            if fallback_result is None:
                fallback_result = match_result

    if fallback_result is not None:
        return fallback_result

    return {
        "status": "Error",
        "error": first_error or "默认匹配规则构建失败",
        "delta_list": [],
        "matched_pairs": [],
    }


def _compute_local_density(sorted_notes: list[float], radius_ms: int) -> np.ndarray:
    """计算局部密度（双指针线性实现）。"""

    n = len(sorted_notes)
    if n == 0:
        return np.array([], dtype=float)

    arr = np.asarray(sorted_notes, dtype=float)
    density = np.zeros(n, dtype=float)
    left = 0
    right = 0
    for i in range(n):
        t = arr[i]
        while left < n and arr[left] < t - radius_ms:
            left += 1
        while right < n and arr[right] <= t + radius_ms:
            right += 1
        density[i] = float(right - left - 1)
    return density


def analyze_delta_t(osr_obj: osr_file, osu_obj: osu_file) -> dict:
    """执行基于 delta_t 的复合检测。

    Args:
        osr_obj: 回放对象。
        osu_obj: 谱面对象。

    Returns:
        兼容旧接口的字典结果，包含 cheat/sus/reason/signals。

    Raises:
        依赖函数异常会向上传递。
    """

    match_result = _match_for_delta(osr_obj, osu_obj)
    if match_result.get("status") != "OK":
        msg = match_result.get("error") or "未知错误"
        return {
            "cheat": False,
            "sus": False,
            "reason": f"匹配失败: {msg}",
            "stats": {},
            "signals": [],
        }

    delta_list = list(match_result.get("delta_list", []))
    matched_pairs = list(match_result.get("matched_pairs", []))
    if not delta_list:
        return {"cheat": False, "sus": False, "reason": "无匹配数据", "stats": {}, "signals": []}

    deltas = np.array([d for _, d in delta_list])
    std = np.std(deltas)
    unique_count = len(np.unique(deltas))

    cheat = False
    sus = False
    reasons: list[str] = []
    signals: list[Signal] = []
    risk_score = 0

    if std < 2.0 and unique_count < 10:
        sig = Signal("delta_low_std_unique_cheat", True, True, 3, f"delta_t 标准差极小 ({std:.2f}ms) 且独特值少 ({unique_count})")
        cheat = True
        sus = True
        risk_score += sig.risk
        signals.append(sig)
        reasons.append(sig.reason)
    elif std < 2.0:
        sig = Signal("delta_low_std_sus", False, True, 2, f"delta_t 标准差极小 ({std:.2f}ms)")
        sus = True
        risk_score += sig.risk
        signals.append(sig)
        reasons.append(sig.reason)
    elif unique_count < 10:
        sig = Signal("delta_low_unique_sus", False, True, 1, f"delta_t 独特值少 ({unique_count})")
        sus = True
        risk_score += sig.risk
        signals.append(sig)
        reasons.append(sig.reason)

    sorted_pairs = sorted(matched_pairs, key=lambda x: x[1])
    sorted_notes = [n for _, n, _ in sorted_pairs]
    sorted_deltas = np.array([p - n for _, n, p in sorted_pairs], dtype=float)

    density_arr = np.array([], dtype=float)
    if len(sorted_notes) >= 300:
        radius_ms = config.delta_dense_radius_ms
        density_arr = _compute_local_density(sorted_notes, radius_ms)

        high_th = np.percentile(density_arr, 85)
        low_th = np.percentile(density_arr, 30)
        high_idx = density_arr >= high_th
        low_idx = density_arr <= low_th

        if np.sum(high_idx) >= 60 and np.sum(low_idx) >= 60:
            high_mad = float(np.median(np.abs(sorted_deltas[high_idx] - np.median(sorted_deltas[high_idx]))))
            low_mad = float(np.median(np.abs(sorted_deltas[low_idx] - np.median(sorted_deltas[low_idx]))))
            ratio = high_mad / low_mad if low_mad > 1e-6 else 1.0

            if high_mad < config.delta_dense_hard_mad and ratio < config.delta_dense_hard_ratio:
                sig = Signal("delta_dense_hard", False, True, 2, f"高密度区波动异常稳定(MAD高密={high_mad:.2f}ms, 比值={ratio:.2f})")
                sus = True
                risk_score += sig.risk
                signals.append(sig)
                reasons.append(sig.reason)
            elif high_mad < config.delta_dense_soft_mad and ratio < config.delta_dense_soft_ratio:
                sig = Signal("delta_dense_soft", False, True, 1, f"高密度区稳定性偏高(MAD高密={high_mad:.2f}ms, 比值={ratio:.2f})")
                sus = True
                risk_score += sig.risk
                signals.append(sig)
                reasons.append(sig.reason)

            fatigue_sig = detect_fatigue_trend(sorted_notes, sorted_deltas, density_arr)
            if fatigue_sig is not None:
                sus = True
                risk_score += fatigue_sig.risk
                signals.append(fatigue_sig)
                reasons.append(fatigue_sig.reason)

    ar1_sig = detect_ar1_memory_pattern(sorted_deltas)
    if ar1_sig is not None:
        sus = True
        risk_score += ar1_sig.risk
        signals.append(ar1_sig)
        reasons.append(ar1_sig.reason)

    nonlinear_sig = detect_nonlinear_memory(sorted_deltas)
    if nonlinear_sig is not None:
        sus = True
        risk_score += nonlinear_sig.risk
        signals.append(nonlinear_sig)
        reasons.append(nonlinear_sig.reason)

    col_delta: dict[int, list[float]] = {}
    for col, d in delta_list:
        col_delta.setdefault(col, []).append(float(d))

    valid_col = {c: np.array(v, dtype=float) for c, v in col_delta.items() if len(v) >= 80}
    if len(valid_col) >= 4:
        col_std = np.array([np.std(v) for v in valid_col.values()], dtype=float)
        col_median = np.array([np.median(v) for v in valid_col.values()], dtype=float)
        std_cv = float(np.std(col_std) / np.mean(col_std)) if np.mean(col_std) > 1e-6 else 0.0
        med_span = float(np.max(col_median) - np.min(col_median)) if len(col_median) > 1 else 0.0
        if std_cv < 0.015 and med_span < 0.9 and std < 6.0:
            sig = Signal("delta_col_consistency", False, True, 1, f"列间统计过于一致(Std-CV={std_cv:.3f}, 中位差={med_span:.2f}ms)")
            sus = True
            risk_score += sig.risk
            signals.append(sig)
            reasons.append(sig.reason)

    chord_groups = build_chord_groups(osu_obj.note_times)
    note_to_press = {(col, note): press for col, note, press in matched_pairs}
    chord_spans: list[float] = []
    for group in chord_groups:
        press_times = [note_to_press[(col, note)] for col, note in group if (col, note) in note_to_press]
        if len(press_times) > 1:
            chord_spans.append(float(max(press_times) - min(press_times)))

    if chord_spans:
        chord_spans_arr = np.array(chord_spans)
        near_sync_ratio = float(np.mean(chord_spans_arr <= 1.2))
        p90_span = float(np.percentile(chord_spans_arr, 90))
        p95_span = float(np.percentile(chord_spans_arr, 95))

        if (
            len(chord_spans) >= config.delta_chord_hard_min_count
            and near_sync_ratio >= config.delta_chord_hard_ratio
            and p95_span <= config.delta_chord_hard_p95
        ):
            sig = Signal("delta_chord_sync_hard", True, True, 3, f"多押同步性异常高({near_sync_ratio*100:.1f}%, P95跨度={p95_span:.2f}ms)")
            cheat = True
            sus = True
            risk_score += sig.risk
            signals.append(sig)
            reasons.append(sig.reason)
        elif (
            len(chord_spans) >= config.delta_chord_soft_min_count
            and near_sync_ratio >= config.delta_chord_soft_ratio
            and p90_span <= config.delta_chord_soft_p90
        ):
            sig = Signal("delta_chord_sync_soft", False, True, 2, f"多押近同步比例偏高({near_sync_ratio*100:.1f}%, P90跨度={p90_span:.2f}ms)")
            sus = True
            risk_score += sig.risk
            signals.append(sig)
            reasons.append(sig.reason)

        near_zero_sig = detect_chord_near_zero_cluster(chord_spans_arr)
        if near_zero_sig is not None:
            cheat = cheat or near_zero_sig.cheat
            sus = sus or near_zero_sig.sus
            risk_score += near_zero_sig.risk
            signals.append(near_zero_sig)
            reasons.append(near_zero_sig.reason)

    autocorr_sig = detect_column_autocorr_and_drift(delta_list)
    if autocorr_sig is not None:
        sus = True
        risk_score += autocorr_sig.risk
        signals.append(autocorr_sig)
        reasons.append(autocorr_sig.reason)

    cross_corr_sig = detect_cross_correlation(delta_list, osu_obj.note_times)
    if cross_corr_sig is not None:
        sus = True
        risk_score += cross_corr_sig.risk
        signals.append(cross_corr_sig)
        reasons.append(cross_corr_sig.reason)

    chord_template_sig = detect_chord_sync_template(chord_groups, note_to_press)
    if chord_template_sig is not None:
        cheat = cheat or chord_template_sig.cheat
        sus = sus or chord_template_sig.sus
        risk_score += chord_template_sig.risk
        signals.append(chord_template_sig)
        reasons.append(chord_template_sig.reason)

    if not cheat and risk_score >= config.delta_risk_cheat_score:
        cheat = True
        sus = True
        sig = Signal("delta_risk_fusion_cheat", True, True, 0, f"多项特征叠加异常(风险分={risk_score})")
        signals.append(sig)
        reasons.append(sig.reason)
    elif not cheat and risk_score >= config.delta_risk_sus_score:
        sus = True

    result = AnalysisResult(
        cheat=cheat,
        sus=sus,
        reason=("偏移分析：正常" if not reasons else "偏移分析：" + "; ".join(reasons)),
        signals=signals,
    )
    return {
        "cheat": result.cheat,
        "sus": result.sus,
        "reason": result.reason,
        "signals": [s.__dict__ for s in result.signals],
    }
