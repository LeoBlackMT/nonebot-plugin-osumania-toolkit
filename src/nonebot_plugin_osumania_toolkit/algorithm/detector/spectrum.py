from collections import Counter

import numpy as np
from nonebot import get_plugin_config
from scipy.fft import fft, fftfreq

from ...config import Config
from .helpers import is_mr_replay, safe_sample_rate
from .types import AnalysisResult, Signal

config = get_plugin_config(Config)


def analyze_pulse_spectrum(data: dict) -> dict:
    """执行按键脉冲序列频域分析。

    Args:
        data: osr.get_data() 返回字典。

    Returns:
        兼容旧接口的字典结果，包含 cheat/sus/reason/signals。
    """

    press_times = data["press_times"]
    intervals = data["intervals"]
    sample_rate = safe_sample_rate(data)

    if not press_times or not intervals:
        res = AnalysisResult(False, False, "频谱分析失败，无有效按键事件", [])
        return {"cheat": res.cheat, "sus": res.sus, "reason": res.reason, "signals": []}

    if is_mr_replay(data):
        res = AnalysisResult(False, False, "频谱分析: 无法对mr分析。", [])
        return {"cheat": res.cheat, "sus": res.sus, "reason": res.reason, "signals": []}

    if sample_rate is None or sample_rate == float("inf"):
        if intervals:
            interval_counts = Counter(intervals)
            most_common_interval, _ = interval_counts.most_common(1)[0]
            sample_rate = 1000 / most_common_interval
        else:
            sample_rate = 0

    total_duration = max(press_times)
    if total_duration <= 0:
        res = AnalysisResult(False, False, "频谱分析失败，无效时长", [])
        return {"cheat": res.cheat, "sus": res.sus, "reason": res.reason, "signals": []}

    pulse_signal = np.zeros(total_duration + 1, dtype=int)
    for t in press_times:
        if 0 <= t <= total_duration:
            pulse_signal[t] += 1

    fs = 1000
    n = len(pulse_signal)
    yf = fft(pulse_signal)
    xf = fftfreq(n, 1 / fs)[: n // 2]
    amplitude = 2.0 / n * np.abs(yf[0 : n // 2])

    mask = (xf >= 1) & (xf <= 500)
    search_xf = xf[mask]
    search_amp = amplitude[mask]

    if len(search_amp) == 0:
        res = AnalysisResult(False, False, "频谱分析失败，无有效频率", [])
        return {"cheat": res.cheat, "sus": res.sus, "reason": res.reason, "signals": []}

    peak_idx = int(np.argmax(search_amp))
    peak_hz = float(search_xf[peak_idx])
    peak_amp = float(search_amp[peak_idx])

    local_range = 10
    local_mask = (xf >= peak_hz - local_range) & (xf <= peak_hz + local_range)
    local_avg = float(np.mean(amplitude[local_mask])) if np.any(local_mask) else 0
    snr = peak_amp / local_avg if local_avg > 0 else 0

    global_avg = float(np.mean(search_amp))
    significant = snr > 50.0 and peak_amp > 10 * global_avg

    device_peak = False
    if sample_rate > 0 and (
        abs(peak_hz - sample_rate) < 2
        or (sample_rate % peak_hz < 1e-6 and peak_hz < sample_rate)
    ):
        device_peak = True

    signals: list[Signal] = []
    if significant:
        if device_peak:
            reason = f"脉冲序列分析：主峰频率 {peak_hz:.0f} Hz 与设备采样率相关。"
            res = AnalysisResult(False, False, reason, signals)
        elif peak_hz < 30:
            reason = f"脉冲序列分析：主峰 {peak_hz:.1f} Hz (信噪比={snr:.1f})，低频峰，正常。"
            res = AnalysisResult(False, False, reason, signals)
        elif peak_hz < 50:
            reason = f"脉冲序列分析：主峰 {peak_hz:.1f} Hz (信噪比={snr:.1f})，标记为可疑。"
            signals.append(Signal("spectrum_peak_sus", False, True, 1, reason))
            res = AnalysisResult(False, True, reason, signals)
        else:
            reason = f"脉冲序列分析：主峰 {peak_hz:.1f} Hz (信噪比={snr:.1f})，标记为作弊。"
            signals.append(Signal("spectrum_peak_cheat", True, True, 3, reason))
            res = AnalysisResult(True, True, reason, signals)
    else:
        res = AnalysisResult(False, False, "脉冲序列分析：正常", signals)

    return {
        "cheat": res.cheat,
        "sus": res.sus,
        "reason": res.reason,
        "signals": [s.__dict__ for s in res.signals],
    }
