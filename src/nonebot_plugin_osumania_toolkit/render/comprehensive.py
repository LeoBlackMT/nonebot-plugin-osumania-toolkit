import re
import os
import numpy as np
import asyncio
import traceback
import gc
import matplotlib
matplotlib.use('Agg') 

from matplotlib import pyplot as plt
from matplotlib import colors
from scipy.fft import fft, fftfreq

plt.rcParams['axes.unicode_minus'] = False

from ..parser.osr_file_parser import osr_file
from ..parser.osu_file_parser import osu_file
from .utils import safe_plot, match_for_visualization

async def run_plot_comprehensive(output_dir: str, osr_obj: osr_file, osu_obj: osu_file=None):
    loop = asyncio.get_running_loop()
    def wrapped():
        try:
            return plot_comprehensive(output_dir, osr_obj, osu_obj=osu_obj)
        except Exception as e:
            traceback.print_exc()
            raise
        finally:
            # 确保清理资源
            plt.close('all')
            gc.collect()
    img_path = await loop.run_in_executor(None, wrapped)
    return img_path

@safe_plot
def plot_comprehensive(output_dir: str, osr_obj: osr_file, osu_obj: osu_file = None) -> str:
    """
    综合绘图：
    - 如果有 osu_obj，则绘制 2x2 四格图：
        1. 按压时长分布图（左上）
        2. 脉冲序列频谱图（右上）
        3. delta_t 直方图（左下）
        4. delta_t 散点图（右下）
    - 如果没有 osu_obj，则绘制 1x2 两格图（按压分布 + 频谱）
    参数:
        osr_obj: osr_file 实例
        output_dir: 输出目录
        osu_obj: 可选，osu_file 实例
    返回:
        生成的图片路径
    """
    data = osr_obj.get_data()
    pressset = data["pressset"]
    mod_obj = data["mod"]            # 可能是 Mod 对象或整数
    player_name = data["player_name"]
    file_basename = os.path.basename(osr_obj.file_path).replace('.osr', '')
    press_times = data["press_times"]
    sample_rate = data["sample_rate"]
    mods_list = data.get("mods", [])  # 获取模组列表
    
    # 统计信息：分数、准确率、ratio 以及各判定计数
    score = data.get("score", 0)
    accuracy = data.get("accuracy", 0)
    ratio = data.get("ratio", 0)
    judge = data.get("judge", {})
    gekis = judge.get("320", 0)
    n300 = judge.get("300", 0)
    katus = judge.get("200", 0)
    n100 = judge.get("100", 0)
    n50 = judge.get("50", 0)
    misses = judge.get("0", 0)
    presscount = f'320={gekis}, 300={n300}\n200={katus}, 100={n100}\n50={n50}, 0={misses}'
    
    # 使用 parser 中提供的 corrector（parser 已对时间数据做了统一缩放）
    corrector = data.get("corrector", 1.0)

    # 匹配 (仅在有 osu_obj 时进行)
    if osu_obj is not None:
        delta_list, matched_pairs = match_for_visualization(osu_obj, osr_obj)
    else:
        delta_list, matched_pairs = [], []

    # 构建按压分布图数据
    basetime = []
    presstime_count = []
    for key_presses in pressset:
        if key_presses:
            # 过滤掉负数
            valid_presses = [d for d in key_presses if d >= 0]
            if not valid_presses:
                continue
            maxpress = max(valid_presses)
            t = np.linspace(0, maxpress, maxpress + 1)
            count = np.zeros(maxpress + 1)
            for d in valid_presses:
                count[d] += 1
            basetime.append(t)
            presstime_count.append(count)
    keyc = len(basetime)

    # 构建频谱数据
    if press_times:
        total_duration = max(press_times)
        pulse_signal = np.zeros(total_duration + 1, dtype=int)
        for t in press_times:
            if 0 <= t <= total_duration:
                pulse_signal[t] += 1
        fs = 1000
        n = len(pulse_signal)
        yf = fft(pulse_signal)
        xf = fftfreq(n, 1/fs)[:n//2]
        amp = 2.0/n * np.abs(yf[0:n//2])
    else:
        xf, amp = np.array([]), np.array([])

    # 根据是否有 osu_obj 决定子图布局
    if osu_obj is not None:
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        ax1, ax2, ax3, ax4 = axes.ravel()

        # 左上：按压分布图
        for i in range(keyc):
            rgb = colors.hsv_to_rgb((i / keyc, 1, 1)) * 255
            color = "#{:02x}{:02x}{:02x}".format(int(rgb[0]), int(rgb[1]), int(rgb[2]))
            ax1.plot(basetime[i], presstime_count[i], label=f'key {i+1}', color=color)
        ax1.set_xlim(0, 160)
        ax1.set_xlabel('pressing time (ms)')
        ax1.set_ylabel('count')
        ax1.set_title('Duration Distribution')
        ax1.legend(fontsize='x-small', ncol=2)
        ax1.grid(alpha=0.3)
        
        # 在按压分布图中添加RI信息
        ax1.text(0.02, 0.98, f'RI={corrector:.2f}', transform=ax1.transAxes, 
                fontsize=10, verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
        # 添加分数、准确率、ratio 信息
        stats_text = f"Score={score}\nAcc={accuracy:.2f}%\nRatio={ratio:.2f}"
        ax1.text(0.02, 0.90, stats_text, transform=ax1.transAxes,
                 fontsize=9, verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
        # 添加判定统计在右下
        ax1.text(0.98, 0.02, presscount, transform=ax1.transAxes,
                 fontsize=9, verticalalignment='bottom', horizontalalignment='right',
                 bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

        # 右上：频谱图
        ax2.plot(xf, amp, color='darkgreen', linewidth=1)
        ax2.fill_between(xf, amp, alpha=0.15, color='green')
        ax2.set_xlim(0, 500)
        ax2.set_xlabel('Frequency (Hz)')
        ax2.set_ylabel('Amplitude')
        ax2.set_title(f'Pulse Spectrum (Sample Rate {sample_rate:.0f} Hz)')
        ax2.grid(alpha=0.3)

        # 左下：delta_t 直方图
        if delta_list:
            deltas = [d for _, d in delta_list]
            # 根据数据范围自动调整 bins
            min_delta = min(deltas)
            max_delta = max(deltas)
            margin = (max_delta - min_delta) * 0.05
            bins_range = np.linspace(min_delta - margin, max_delta + margin, 50)
            ax3.hist(deltas, bins=bins_range, alpha=0.7, color='steelblue', edgecolor='black')
            ax3.set_xlabel('Delta t (ms)')
            ax3.set_ylabel('Count')
            ax3.set_title('Delta t Distribution')
            ax3.grid(alpha=0.3)
            
            # 在delta_t直方图中添加统计信息
            if deltas:
                mean_delta = np.mean(deltas)
                std_delta = np.std(deltas)
                unique_count = len(np.unique(deltas))
                stats_text = f'Mean: {mean_delta:.2f}ms\nStd: {std_delta:.2f}ms\nUnique: {unique_count}'
                ax3.text(0.02, 0.98, stats_text, transform=ax3.transAxes,
                        fontsize=9, verticalalignment='top',
                        bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.5))
        else:
            ax3.text(0.5, 0.5, 'No matching data', ha='center', va='center')
            ax3.set_title('Delta t Distribution')

        # 右下：delta_t 散点图
        if matched_pairs:
            note_times = [p[1] for p in matched_pairs]
            deltas_scatter = [p[2] - p[1] for p in matched_pairs]
            ax4.scatter(note_times, deltas_scatter, s=1, alpha=0.5, c='blue')
            ax4.axhline(y=0, color='red', linestyle='--', linewidth=0.5)
            ax4.set_xlabel('Note Time (ms)')
            ax4.set_ylabel('Delta t (ms)')
            ax4.set_title('Delta t Scatter')
            ax4.grid(alpha=0.3)
            
            # 在散点图中添加模组信息
            if mods_list:
                mods_text = "Mods: " + ", ".join(mods_list[:5])  # 只显示前5个模组
                if len(mods_list) > 5:
                    mods_text += "..."
                ax4.text(0.02, 0.98, mods_text, transform=ax4.transAxes,
                        fontsize=9, verticalalignment='top',
                        bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.5))
        else:
            ax4.text(0.5, 0.5, 'No matching data', ha='center', va='center')
            ax4.set_title('Delta t Scatter')

        # 主标题
        fig.suptitle(f'Replay Analysis - {player_name} | {file_basename}', fontsize=14, fontweight='bold')
        plt.tight_layout()
        output_path = os.path.join(output_dir, re.sub(r'[\/*?:"<>|]', '_', file_basename) + "_comprehensive.png")
    else:
        # 无 osu_obj，只绘制两个图：按压分布 + 频谱
        fig, axes = plt.subplots(1, 2, figsize=(16, 6))
        ax1, ax2 = axes

        # 左：按压分布
        for i in range(keyc):
            rgb = colors.hsv_to_rgb((i / keyc, 1, 1)) * 255
            color = "#{:02x}{:02x}{:02x}".format(int(rgb[0]), int(rgb[1]), int(rgb[2]))
            ax1.plot(basetime[i], presstime_count[i], label=f'key {i+1}', color=color)
        ax1.set_xlim(0, 160)
        ax1.set_xlabel('pressing time (ms)')
        ax1.set_ylabel('count')
        ax1.set_title('Duration Distribution')
        ax1.legend(fontsize='x-small', ncol=2)
        ax1.grid(alpha=0.3)
        
        # 在按压分布图中添加RI信息
        ax1.text(0.02, 0.98, f'RI={corrector:.2f}', transform=ax1.transAxes, 
                fontsize=10, verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
        # 添加分数、准确率、ratio 信息
        stats_text = f"Score={score}\nAcc={accuracy:.2f}%\nRatio={ratio:.2f}"
        ax1.text(0.02, 0.90, stats_text, transform=ax1.transAxes,
                 fontsize=9, verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
        # 添加判定统计在右下
        ax1.text(0.98, 0.02, presscount, transform=ax1.transAxes,
                 fontsize=9, verticalalignment='bottom', horizontalalignment='right',
                 bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

        # 右：频谱
        ax2.plot(xf, amp, color='darkgreen', linewidth=1)
        ax2.fill_between(xf, amp, alpha=0.15, color='green')
        ax2.set_xlim(0, 500)
        ax2.set_xlabel('Frequency (Hz)')
        ax2.set_ylabel('Amplitude')
        ax2.set_title(f'Pulse Spectrum (Sample Rate {sample_rate:.0f} Hz)')
        ax2.grid(alpha=0.3)
        
        # 在频谱图中添加模组信息
        if mods_list:
            mods_text = "Mods: " + ", ".join(mods_list[:5])  # 只显示前5个模组
            if len(mods_list) > 5:
                mods_text += "..."
            ax2.text(0.02, 0.98, mods_text, transform=ax2.transAxes,
                    fontsize=9, verticalalignment='top',
                    bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.5))

        fig.suptitle(f'Replay Analysis - {player_name} | {file_basename}', fontsize=14, fontweight='bold')
        plt.tight_layout()
        output_path = os.path.join(output_dir, re.sub(r'[\/*?:"<>|]', '_', file_basename) + "_dual.png")

    plt.savefig(output_path)
    plt.close()
    return output_path