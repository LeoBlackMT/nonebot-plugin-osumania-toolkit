import numpy as np
import asyncio
import traceback

from scipy.fft import fft, fftfreq
from collections import Counter
from scipy.signal import find_peaks

from ..algorithm.utils import match_notes_and_presses
from ..file.osr_file_parser import osr_file
from ..file.osu_file_parser import osu_file

async def run_analyze_cheating(osr_obj: osr_file, osu_obj: osu_file=None):
    loop = asyncio.get_running_loop()
    def wrapped():
        try:
            return analyze_cheating(osr_obj, osu_obj)
        except Exception as e:
            traceback.print_exc()
            raise
    result = await loop.run_in_executor(None, wrapped)
    return result

def analyze_time_domain(data: dict) -> dict:
    '''
    时域分析作弊特征
    参数:
        data: osr_file.get_data 返回的字典
    返回字典:
        cheat: 是否作弊
        suspicious: 是否可疑
        reason: 原因描述
    '''
    pressset = data["pressset"]
    sample_rate = data["fft_analysis"]["peak_frequency"] if (data["fft_analysis"] != None and data["fft_analysis"]["peak_frequency"] != 0) else data["sample_rate"]
    mr_flag = True if data["player_name"] == "ConvertedFromMalody" else False
    
    # 可变内置参数
    max_time=500 # 直方图最大时间(ms)
    bin_width=1 # 直方图bin数
    sim_RthresholdC=0.99 # 轨道相似度上作弊阈值
    sim_RthresholdS=0.98 # 轨道相似度上可疑阈值
    sim_LthresholdC=0.4 # 轨道相似度下作弊阈值
    sim_LthresholdS=0.55 # 轨道相似度下可疑阈值
    abnormal_peak_threshold = 0.33 # 异常高峰占比阈值
    LOW_SR = 165 # 低采样率阈值
    SHORT_BAND = (0, 25) # 短按区间 [0,25) ms
    LONG_BAND = (100, max_time) # 长按区间 [100,500) ms
    
    abnormal_peak = False # 异常尖峰标记
    reasons = [] #原因列表

    # 过滤样本数过少的轨道
    non_empty = [p for p in pressset if len(p) > 5]
    if len(non_empty) < 2:
        return {"percent": 0.0, "SR": 0, "cheat": False, "sus": False, "reason": "有效轨道少于2个，无法分析"}
    
    # 合并所有按压时间
    all_data = np.concatenate(non_empty)

    # 1. 计算轨道间相似度（使用10ms bin）
    coarse_bins = int(max_time / 10)
    hist_list = []
    for data in non_empty:
        hist, _ = np.histogram(data, bins=coarse_bins, range=(0, max_time))
        hist = hist.astype(float)
        if hist.sum() > 0:
            hist /= hist.sum()
        hist_list.append(hist)

    n = len(hist_list)
    sim_matrix = np.zeros((n, n))
    for i in range(n):
        for j in range(i+1, n):
            a = hist_list[i]
            b = hist_list[j]
            norm_a = np.linalg.norm(a)
            norm_b = np.linalg.norm(b)
            if norm_a > 0 and norm_b > 0:
                cos_sim = np.dot(a, b) / (norm_a * norm_b)
            else:
                cos_sim = 0
            sim_matrix[i, j] = cos_sim
            sim_matrix[j, i] = cos_sim

    avg_sim = np.mean(sim_matrix[np.triu_indices(n, k=1)]) if n > 1 else 0
    similarity_percent = avg_sim * 100
    
    if sample_rate > LOW_SR and not mr_flag:
        # 2. 构建1ms精度直方图（用于异常高峰检测）
        bins = int(max_time / bin_width)
        hist_all, bin_edges = np.histogram(all_data, bins=bins, range=(0, max_time))
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

        # 3. 异常高峰检测

        # 辅助函数：检测区间内是否有异常峰
        def check_band(band_start, band_end, threshold_ratio, min_count=10):
            band_mask = (bin_centers >= band_start) & (bin_centers < band_end)
            band_counts = hist_all[band_mask]
            if band_counts.sum() == 0:
                return False, None, None
            max_count = band_counts.max()
            max_idx = np.argmax(band_counts) + np.where(band_mask)[0][0]
            if max_count > threshold_ratio * band_counts.sum() and max_count > min_count:
                return True, max_count, bin_centers[max_idx]
            return False, None, None

        # 短按区间：
        short_abnormal, short_count, short_time = check_band(SHORT_BAND[0], SHORT_BAND[1], abnormal_peak_threshold)
        if short_abnormal:
            abnormal_peak = True
            reasons.append(f"{short_time:.0f}ms出现异常高峰({short_count}次)")

        # 长按区间：
        long_abnormal, long_count, long_time = check_band(LONG_BAND[0], LONG_BAND[1], abnormal_peak_threshold)
        if long_abnormal:
            abnormal_peak = True
            reasons.append(f"{long_time:.0f}ms出现异常高峰({long_count}次)")

        # 全局多峰检测（仅当未触发区间异常时，避免重复）
        if not abnormal_peak:
                peaks, properties = find_peaks(hist_all, height=0.1 * np.max(hist_all), distance=5)
                peak_heights = properties['peak_heights']
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

    # 5. 综合判定
    cheat = False
    suspicious = False
    if avg_sim > sim_RthresholdC:
        cheat = True
        suspicious = True
        reasons.append(f"轨道相似度极高({similarity_percent:.1f}%)")
    if avg_sim < sim_LthresholdC:
        cheat = True
        suspicious = True
        reasons.append(f"轨道相似度极低({similarity_percent:.1f}%)")
    if avg_sim > sim_RthresholdS and not cheat:
        suspicious = True
        reasons.append(f"轨道相似度过高({similarity_percent:.1f}%)")
    if avg_sim < sim_LthresholdS and not cheat:
        suspicious = True
        reasons.append(f"轨道相似度过低({similarity_percent:.1f}%)")
    if abnormal_peak:
        suspicious = True

    if not suspicious and not cheat:
        reason = "时域与按压时长分析：正常"
    else:
        reason = "时域与按压时长分析： " + "; ".join(reasons)
    return {"cheat": cheat, "sus": suspicious, "reason": reason} 

def analyze_delta_t(osr_obj: osr_file, osu_obj: osu_file):
    """
    基于 delta_t 分析作弊嫌疑
    返回字典:
        - cheat: bool
        - sus: bool
        - reason: str
    """
    delta_list, matched_pairs = match_notes_and_presses(osu_obj, osr_obj)

    if not delta_list:
        return {"cheat": False, "sus": False, "reason": "无匹配数据", "stats": {}}

    deltas = np.array([d for _, d in delta_list])

    # 基本统计
    # mean = np.mean(deltas)
    std = np.std(deltas)
    unique_count = len(np.unique(deltas))
    # 峰度
    # kurt = np.mean((deltas - mean)**4) / (std**4) if std > 0 else 0

    cheat = False
    sus = False
    reasons = []

    # 极低标准差且独特值少 → 作弊
    if std < 2.0 and unique_count < 10:
        cheat = True
        reasons.append(f"delta_t 标准差极小 ({std:.2f}ms) 且独特值少 ({unique_count})")
    elif std < 2.0:
        sus = True
        reasons.append(f"delta_t 标准差极小 ({std:.2f}ms)")
    elif unique_count < 10:
        sus = True
        reasons.append(f"delta_t 独特值少 ({unique_count})")

    # 多押同时性检测
    # 按物件时间分组（时间差 < 1ms）
    note_times_flat = []
    for col, times in osu_obj.note_times.items():
        for t in times:
            note_times_flat.append((col, t))
    note_times_flat.sort(key=lambda x: x[1])
    chord_groups = []
    i = 0
    while i < len(note_times_flat):
        group = [note_times_flat[i]]
        j = i + 1
        while j < len(note_times_flat) and abs(note_times_flat[j][1] - note_times_flat[i][1]) < 1:
            group.append(note_times_flat[j])
            j += 1
        if len(group) > 1:
            chord_groups.append(group)
        i = j

    # 对于每个多押组，找出对应的按下时间
    # 先建立物件时间到按下时间的映射（从 matched_pairs）
    note_to_press = {(col, note): press for col, note, press in matched_pairs}
    all_chord_sync = True
    for group in chord_groups:
        press_times = []
        for col, note in group:
            if (col, note) in note_to_press:
                press_times.append(note_to_press[(col, note)])
        if len(press_times) > 1:
            max_diff = max(press_times) - min(press_times)
            if max_diff > 0.05:  # 允许 0.05ms 误差（采样率导致）
                all_chord_sync = False
                break

    if all_chord_sync and chord_groups:
        # 所有多押组中按键时间差极小
        sus = True
        reasons.append("多押按键时间几乎同步")

    if not reasons:
        reason = "偏移分析：正常"
    else:
        reason = "偏移分析：" + "; ".join(reasons)

    return {
        "cheat": cheat,
        "sus": sus,
        "reason": reason,
    }

def analyze_pulse_spectrum(data: dict) -> dict:
    """
    对脉冲序列进行频谱分析，返回分析结果。
    参数:
        data: osr_file.get_data 返回的字典
    返回字典:
        cheat: 是否作弊
        suspicious: 是否可疑
        reason: 原因描述
    """
    press_times = data["press_times"]
    intervals = data["intervals"]
    sample_rate = data["fft_analysis"]["peak_frequency"] if (data["fft_analysis"] != None and data["fft_analysis"]["peak_frequency"] != 0) else data["sample_rate"]

    if not press_times or not intervals:
        return {
            "cheat": False,
            "sus": False,
            "reason": "频谱分析失败，无有效按键事件"
        }

    if data["player_name"] == "ConvertedFromMalody":
        return {
            "cheat": False,
            "sus": False,
            "reason": "频谱分析: 无法对mr分析。"
        }
    # 如果采样率未估算，重新计算
    if sample_rate is None or sample_rate == float('inf'):
        if intervals:
            interval_counts = Counter(intervals)
            most_common_interval, _ = interval_counts.most_common(1)[0]
            sample_rate = 1000 / most_common_interval
        else:
            sample_rate = 0

    total_duration = max(press_times)
    if total_duration <= 0:
        return {
            "cheat": False,
            "sus": False,
            "reason": "频谱分析失败，无效时长"
        }

    # 构建脉冲信号
    pulse_signal = np.zeros(total_duration + 1, dtype=int)
    for t in press_times:
        if 0 <= t <= total_duration:
            pulse_signal[t] += 1

    # FFT
    fs = 1000
    n = len(pulse_signal)
    yf = fft(pulse_signal)
    xf = fftfreq(n, 1/fs)[:n//2]
    amplitude = 2.0/n * np.abs(yf[0:n//2])

    mask = (xf >= 1) & (xf <= 500)
    search_xf = xf[mask]
    search_amp = amplitude[mask]

    if len(search_amp) == 0:
        return {
            "cheat": False,
            "sus": False,
            "reason": "频谱分析失败，无有效频率"
        }

    peak_idx = np.argmax(search_amp)
    peak_hz = search_xf[peak_idx]
    peak_amp = search_amp[peak_idx]

    # 局部信噪比
    local_range = 10
    local_mask = (xf >= peak_hz - local_range) & (xf <= peak_hz + local_range)
    local_avg = np.mean(amplitude[local_mask]) if np.any(local_mask) else 0
    snr = peak_amp / local_avg if local_avg > 0 else 0

    global_avg = np.mean(search_amp)
    significant = (snr > 50.0 and peak_amp > 10 * global_avg)

    device_peak = False
    if sample_rate > 0 and (abs(peak_hz - sample_rate) < 2 or
                            (sample_rate % peak_hz < 1e-6 and peak_hz < sample_rate)):
        device_peak = True


    # 生成简短描述
    if significant:
        if device_peak:
            reason = f"脉冲序列分析：主峰频率 {peak_hz:.0f} Hz 与设备采样率相关。"
            sus = False
            cheat = False
        else:
            if peak_hz < 30:
                reason = f"脉冲序列分析：主峰 {peak_hz:.1f} Hz (信噪比={snr:.1f})，低频峰，正常。"
                sus = False
                cheat = False
            elif peak_hz >= 30 and peak_hz < 50:
                reason = f"脉冲序列分析：主峰 {peak_hz:.1f} Hz (信噪比={snr:.1f})，标记为可疑。"
                sus = True
                cheat = False
            else:
                reason = f"脉冲序列分析：主峰 {peak_hz:.1f} Hz (信噪比={snr:.1f})，标记为作弊。"
                sus = True
                cheat = True                
            
    else:
        reason = "脉冲序列分析：正常"
        cheat = False
        sus = False

    return {
        "cheat": cheat,
        "sus": sus,
        "reason": reason
    }
    
def analyze_cheating(osr: osr_file, osu: osu_file=None) -> dict:
    """
    综合分析作弊嫌疑
    参数:
        data: osr_file.get_data 返回的字典
    返回:
        字典，包含:
        - cheat: 是否确定作弊 (bool)
        - sus: 是否可疑 (bool)
        - reason: 原因描述 (str)
    """
    data = osr.get_data()
    # 时域分析
    time_result = analyze_time_domain(data)
    spectrum_result = analyze_pulse_spectrum(data)
    if osu:
        delta_result = analyze_delta_t(osr, osu)
    else:
        delta_result = {"cheat": False, "sus": False, "reason": "未分析delta_t。"}

    cheat = time_result["cheat"] or spectrum_result["cheat"] or delta_result["cheat"]
    sus = time_result["sus"] or spectrum_result["sus"] or delta_result["sus"]

    # 合并原因
    reasons = []
    reasons.append(time_result["reason"])
    reasons.append(spectrum_result["reason"])
    reasons.append(delta_result["reason"])

    return {
        "cheat": cheat,
        "sus": sus,
        "reasons": reasons,
    }