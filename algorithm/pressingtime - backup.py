# -*- coding: utf-8 -*-
"""
Created on Wed Jun 23 00:32:44 2021

@author: Transcendence
"""

import osrparse
import numpy as np
import re
import os
from matplotlib import pyplot as plt
from matplotlib import colors
from osrparse import GameMode
from scipy.signal import find_peaks
from collections import Counter

def findkey(x = 0):
    keyset = [0 for i in range(18)]
    (a, keyset[0]) = (x//2, x%2)
    j = 1
    while a != 0:
        (a, keyset[j]) = (a//2, a%2)
        j += 1
    return np.array(keyset)

def analyze_cheating(pressset, sample_rate=None, max_time=500, bin_width=1):
    """
    分析作弊特征
    参数:
        pressset: list of lists，每个子列表为一个按键的所有按压时间(ms)
        sample_rate: 采样率 (Hz)，如果为 None，则根据数据估计
        max_time: 直方图最大时间(ms)
        bins: 直方图bin数
        sim_threshold: 相似度阈值
    返回:
        similarity_percent: 平均相似度百分比
        suspicious: 是否可疑
        reason: 原因描述
    """
    sim_RthresholdC=0.99 # 轨道相似度上作弊阈值
    sim_RthresholdS=0.96 # 轨道相似度上可疑阈值
    sim_LthresholdC=0.4 # 轨道相似度下作弊阈值
    sim_LthresholdS=0.55 # 轨道相似度下可疑阈值
    abnormal_peak_threshold = 0.25 # 异常高峰占比阈值
    SHORT_BAND = (0, 25) # 短按区间 [0,25) ms
    LONG_BAND = (100, max_time) # 长按区间 [100,500) ms
    abnormal_peak = False
    reasons = []
    
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
        reason = "正常"
    else:
        reason = "; ".join(reasons)
    return {"percent": similarity_percent, "cheat": cheat, "sus": suspicious, "reason": reason}
    

def presssaver(file_path_without_ext: str, output_dir: str = None) -> str:
    # --- Start to parse file ---
    if output_dir is None:
        output_dir = "graph_results"
    os.makedirs(output_dir, exist_ok=True)
    info = osrparse.parse_replay_file(file_path_without_ext+'.osr') #read replay file
    
    if info.game_mode != GameMode.MANIA:
        return {"status": "NotMania", "img": None}
    
    onset = np.zeros(18) #infornation about previous key pressing
    r_onset = np.zeros(18) #initialize r_onset to avoid UnboundLocalError
    timeset = np.zeros(18) #milisecond time that keyboard pressed
    pressset = [[] for i in range(18)] # save all data of timeset
    intervals = [] # save all data of time delta between frames
    current_time = 0  # 当前累计时间
    press_times = []  # 记录所有按键按下时刻（绝对值，ms）
    
    for i, j in enumerate(info.play_data): # get infornation about key pressing time
        if (j.time_delta == 0 and j.keys == 0) or i < 3 : #there are dummy replay whose timing is zero. We should remove this. and, I deleted first three data because thet data does not indicate real press time.
            continue
        
        intervals.append(j.time_delta)
        
        current_time += j.time_delta
        # 检测新按下的键
        for k, l in enumerate(r_onset):
            if onset[k] == 0 and l == 1:   # 之前未按，现在按下
                press_times.append(current_time)
                
        r_onset=findkey(j.keys) #infornation about "Present" key pressing
        timeset += onset*j.time_delta
        for k,l in enumerate(r_onset):
            if onset[k] != 0 and l == 0:
                pressset[k].append(int(timeset[k]))
                timeset[k] = 0
        onset = r_onset
    
    if intervals:
    # 估计采样率（ms级别）以调整异常峰检测参数
        interval_counts = Counter(intervals)
        most_common_interval, count = interval_counts.most_common(1)[0]
        sample_rate = 1000 / most_common_interval
    else:
        sample_rate = float('inf')
        
    # --- End to parse file ---

    #making plot
    basetime = [] #press time
    presstime = [] #press count
    bin(info.mod_combination)

    corrector = 1
    if info.mod_combination == 0:
        pass
    elif (bin(info.mod_combination)[2:].zfill(32))[-7] =='1':
        corrector = 2/3
    elif (bin(info.mod_combination)[2:].zfill(32))[-9] =='1':
        corrector = 4/3    
    
    for i in pressset: # press count vs press time
        if i != []:
            presstime.append([])
            basetime.append([])
            maxpress = max(i)
            basetime[-1] = np.linspace(0, maxpress, maxpress+1)
            presstime[-1] = np.zeros(maxpress+1)
            for j in i:
                if j >=0:
                    presstime[-1][j] += 1
    for i in basetime:
        i *=corrector
    keyc = len(basetime)
    
    if keyc < 2:
        return {"status": "tooFewKeys", "img": None, "cheat_analysis": {"percent": 0.0, "cheat": False, "sus": False, "reason": "有效轨道少于2个，无法分析"}}
    
    for i in range(len(basetime)):
        rgbcolor = colors.hsv_to_rgb((i/keyc,1,1))*255
        colorst = "#"+hex(int(rgbcolor[0]))[2:].zfill(2)+hex(int(rgbcolor[1]))[2:].zfill(2)+hex(int(rgbcolor[2]))[2:].zfill(2)
        plt.plot(basetime[i], presstime[i], label= 'key '+str(i+1), color = colorst)
    presscount = '320='+str(info.gekis)+', 300='+str(info.number_300s)+'\n200='+str(info.katus)+', 100='+str(info.number_100s)+'\n50='+str(info.number_50s)+', 0='+str(info.misses)
    totObj = info.gekis + info.number_300s + info.number_100s + info.number_50s + info.misses + info.katus
    acc = ((info.gekis + info.number_300s) * 300 + info.katus * 200 + info.number_100s * 100 + info.number_50s * 50) / (totObj * 300) * 100
    ratio = info.gekis / info.number_300s if info.number_300s > 0 else 0
    plt.grid()
    plt.xticks(fontsize=15)
    plt.yticks(fontsize=15)
    plt.xlim(0,160)
    plt.xlabel('pressing time(ms)',fontsize=15)
    plt.ylabel(r'count',fontsize=15)
    plt.legend(shadow=True, fontsize=10, ncol=2)
    plt.text(0.5, 0.5, str(osrparse.Mod(info.mod_combination))[4:].replace("|","\n")+"\nscores="+str(info.score)+"\naccuracy="+str(round(acc,2))+"%\nRatio="+str(round(ratio,2)) if ratio != 0 else "Inf", va='bottom', ha='left')
    plt.text(159.5, 0.5, presscount+"\nRI="+format(corrector,"0.2f"), ha='right', va='bottom')
    plt.title(file_path_without_ext[10:]+"\n,"+info.player_name+","+str(info.timestamp))
    plt.tight_layout()
    base_name = os.path.basename(file_path_without_ext)
    safe_base = re.sub(r'[\\/*?:"<>|]', '_', base_name)
    output_path = os.path.join(output_dir, safe_base + ".png")
    plt.savefig(output_path)
    plt.clf()
    
    status = "OK" if os.path.exists(output_path) else "failure"
    cheat_analysis = analyze_cheating(pressset, sample_rate=sample_rate)
    return {"status": status, "img": output_path, "cheat_analysis": cheat_analysis, "sample_rate": sample_rate}
