import re
import os
import numpy as np
import asyncio
import traceback
import gc

# 必须在导入 pyplot 之前设置后端，避免 tkinter 线程安全问题
import matplotlib
matplotlib.use('Agg')  # 使用非交互式后端

from matplotlib import pyplot as plt
from matplotlib import colors
from scipy.fft import fft, fftfreq
from functools import partial, wraps

# 中文字体
# plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'WenQuanYi Zen Hei', 'Noto Sans CJK SC']
plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题

from ..file.osr_file_parser import osr_file
from ..file.osu_file_parser import osu_file

from ..algorithm.utils import match_notes_and_presses


def safe_plot(func):
    """
    装饰器：确保绘图函数即使出错也能正确清理资源
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        finally:
            # 关闭所有打开的图形，释放资源
            plt.close('all')
            # 强制垃圾回收，清理 matplotlib 对象
            gc.collect()
    return wrapper


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
def plot_pressingtime(osr_obj: osr_file, output_dir: str) -> str:
    """
    绘制按压时长分布图（各轨道颜色区分）
    本函数修改自 https://github.com/adgjl7777777/VSRG_Total_Analyzer/blob/master/graph.py
    参数:
        osr_obj: osr_file 实例（已 process）
        output_dir: 输出目录
    返回:
        生成的图片路径
    """
    pressset = osr_obj.pressset
    mod_obj = getattr(osr_obj, 'mod', 0)          # 使用getattr避免AttributeError
    player_name = osr_obj.player_name
    timestamp = osr_obj.timestamp
    file_basename = os.path.basename(osr_obj.file_path).replace('.osr', '')
    acc = osr_obj.acc
    ratio = osr_obj.ratio
    score = osr_obj.score
    gekis = osr_obj.judge["320"]
    n300 = osr_obj.judge["300"]
    katus = osr_obj.judge["200"]
    n100 = osr_obj.judge["100"]
    n50 = osr_obj.judge["50"]
    misses = osr_obj.judge["0"]

    # 获取用于显示的 mod 字符串和 corrector（parser 中已统一缩放时间数据）
    mods_list = osr_obj.mods if hasattr(osr_obj, 'mods') else []
    mod_str = str(mod_obj)
    corrector = getattr(osr_obj, 'corrector', 1.0)

    # 构建绘图数据
    basetime = []
    presstime = []
    for key_presses in pressset:
        if key_presses:
            valid_presses = [d for d in key_presses if d >= 0]
            if not valid_presses:
                continue
            maxpress = max(valid_presses)
            t = np.linspace(0, maxpress, maxpress + 1)
            count = np.zeros(maxpress + 1)
            for d in valid_presses:
                count[d] += 1
            basetime.append(t)
            presstime.append(count)

    keyc = len(basetime)
    if keyc == 0:
        raise ValueError("无有效轨道")

    plt.figure()
    for i in range(keyc):
        rgb = colors.hsv_to_rgb((i / keyc, 1, 1)) * 255
        color = "#{:02x}{:02x}{:02x}".format(int(rgb[0]), int(rgb[1]), int(rgb[2]))
        plt.plot(basetime[i], presstime[i], label=f'key {i+1}', color=color)

    presscount = f'320={gekis}, 300={n300}\n200={katus}, 100={n100}\n50={n50}, 0={misses}'

    if mods_list:
        # 将模组列表转换为多行字符串，每行最多3个模组
        mod_lines = []
        for i in range(0, len(mods_list), 3):
            mod_lines.append(", ".join(mods_list[i:i+3]))
        display_mod = "\n".join(mod_lines)
    else:
        # 回退到原来的显示方式
        if mod_str.startswith("Mod."):
            display_mod = mod_str[4:].replace("|", "\n")
        else:
            display_mod = mod_str.replace("|", "\n")

    plt.grid()
    plt.xticks(fontsize=15)
    plt.yticks(fontsize=15)
    plt.xlim(0, 160)
    plt.xlabel('pressing time (ms)', fontsize=15)
    plt.ylabel('count', fontsize=15)
    plt.legend(shadow=True, fontsize=10, ncol=2)
    plt.text(0.5, 0.5,
             display_mod +
             f"\nscores={score}\naccuracy={round(acc,2)}%\nRatio={ratio:.2f}" if ratio != 0 else "Inf",
             va='bottom', ha='left')
    plt.text(159.5, 0.5, presscount + f"\nRI={corrector:.2f}", ha='right', va='bottom')
    plt.title(f"{file_basename}\n,{player_name},{timestamp}")

    safe_base = re.sub(r'[\\/*?:"<>|]', '_', file_basename)
    output_path = os.path.join(output_dir, safe_base + "_duration.png")
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
    return output_path

@safe_plot
def plot_delta(osr_obj: osr_file, osu_obj: osu_file, output_dir: str):
    """
    绘制 delta_t 分布直方图（按列着色）
    osr_obj: osr_file 实例（已 process）
    osu_obj: osu_file 实例（已 process）
    output_dir: 输出目录
    """
    delta_list, _ = match_notes_and_presses(osu_obj, osr_obj)

    if not delta_list:
        raise ValueError("无匹配的 delta_t，无法绘图")

    # 按列分组
    delta_by_col = {}
    for col, d in delta_list:
        delta_by_col.setdefault(col, []).append(d)

    # 获取 delta_list 的范围
    all_deltas = [d for _, d in delta_list]
    min_delta = min(all_deltas)
    max_delta = max(all_deltas)
    # 添加 5% 的边距
    margin = (max_delta - min_delta) * 0.05
    bin_min = min_delta - margin
    bin_max = max_delta + margin

    plt.figure(figsize=(12, 6))
    bins = np.linspace(bin_min, bin_max, 75)
    for col, deltas in delta_by_col.items():
        plt.hist(deltas, bins=bins, alpha=0.5, label=f'Col {col+1}', histtype='stepfilled')
    plt.xlabel('Delta Time (ms)')
    plt.ylabel('Count')
    plt.title(f'Delta Time Distribution - {osr_obj.player_name}')
    plt.legend()
    plt.grid(alpha=0.3)

    safe_base = os.path.basename(osr_obj.file_path).replace('.osr', '')
    safe_base = re.sub(r'[\\/*?:"<>|]', '_', safe_base)
    output_path = os.path.join(output_dir, safe_base + "_delta.png")
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
    return output_path

@safe_plot
def plot_spectrum(osr_obj: osr_file, output_dir: str) -> str:
    """
    生成脉冲序列频谱图
    参数:
        osr_obj: osr_file 实例（已 process）
        output_dir: 输出目录
    返回:
        生成的图片路径
    """
    press_times = osr_obj.press_times
    sample_rate = osr_obj.sample_rate
    player_name = osr_obj.player_name
    file_basename = os.path.basename(osr_obj.file_path).replace('.osr', '')

    if not press_times:
        raise ValueError("无按键事件，无法生成频谱图")

    total_duration = max(press_times) if press_times else 0
    if total_duration <= 0:
        raise ValueError("无效的时长")

    # 构建脉冲信号（每个毫秒的按键次数）
    pulse_signal = np.zeros(total_duration + 1, dtype=int)
    for t in press_times:
        if 0 <= t <= total_duration:
            pulse_signal[t] += 1

    # FFT
    fs = 1000  # 采样率 1000 Hz
    n = len(pulse_signal)
    yf = fft(pulse_signal)
    xf = fftfreq(n, 1/fs)[:n//2]
    amplitude = 2.0/n * np.abs(yf[0:n//2])

    # 绘图
    plt.figure(figsize=(10, 6))
    plt.plot(xf, amplitude, color='darkgreen', linewidth=1)
    plt.fill_between(xf, amplitude, alpha=0.15, color='green')
    plt.title(f"Pulse Spectrum\nPlayer: {player_name} | File: {file_basename} | SampleRate: {sample_rate:.0f} Hz",
              fontweight='bold', fontsize=12)
    plt.xlabel("Frequency (Hz)")
    plt.ylabel("Amplitude")
    plt.xlim(0, 500)
    plt.grid(True, alpha=0.3)

    safe_base = re.sub(r'[\\/*?:"<>|]', '_', file_basename)
    output_path = os.path.join(output_dir, safe_base + "_spectrum.png")
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
    return output_path

@safe_plot
def plot_scatter(osr_obj: osr_file, osu_obj: osu_file, output_dir: str) -> str:
    """
    绘制 delta_t 散点图（横坐标为物件时间，纵坐标为玩家按下时间与物件时间的差值）
    osr_obj: osr_file 实例（已 process）
    osu_obj: osu_file 实例（已 process）
    output_dir: 输出目录
    返回:
        生成的图片路径
    """

    _ , matched_pairs = match_notes_and_presses(osu_obj, osr_obj)

    if not matched_pairs:
        raise ValueError("无匹配的 delta_t 数据，无法绘图")

    # 准备数据
    note_times = [pair[1] for pair in matched_pairs]  # 物件时间
    press_times = [pair[2] for pair in matched_pairs] # 按下时间
    deltas = [press - note for note, press in zip(note_times, press_times)]

    plt.figure(figsize=(12, 6))
    plt.scatter(note_times, deltas, s=1, alpha=0.5, c='blue')
    plt.axhline(y=0, color='red', linestyle='--', linewidth=0.5)
    plt.xlabel('Time (ms)')
    plt.ylabel('Delta_t (ms)')
    plt.title(f'Delta_t scatter - {osr_obj.player_name}')
    plt.grid(alpha=0.3)

    safe_base = os.path.basename(osr_obj.file_path).replace('.osr', '')
    safe_base = re.sub(r'[\\/*?:"<>|]', '_', safe_base)
    output_path = os.path.join(output_dir, safe_base + "_delta_scatter.png")
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
    return output_path

@safe_plot
def plot_life(osr_obj: osr_file, output_dir: str) -> str:
    """
    绘制玩家血量随时间变化图
    osr_obj: osr_file 实例（已 process）
    output_dir: 输出目录
    返回:
        生成的图片路径
    """
    life_str = osr_obj.life_bar_graph
    if not life_str:
        raise ValueError("无血条数据")

    # 解析 "time|life,time|life,..."
    points = []
    for segment in life_str.split(','):
        if not segment:
            continue
        parts = segment.split('|')
        if len(parts) != 2:
            continue
        try:
            t = int(parts[0])
            life = float(parts[1]) * 100
            points.append((t, life))
        except ValueError:
            continue

    if not points:
        raise ValueError("血条数据解析失败")

    times, lives = zip(*points)

    plt.figure(figsize=(12, 4))
    plt.plot(times, lives, color='green', linewidth=1.5)
    plt.fill_between(times, 0, lives, alpha=0.2, color='green')
    plt.xlabel('Time (ms)')
    plt.ylabel('Health (%)')
    plt.title(f'HP Bar - {osr_obj.player_name}')
    plt.grid(alpha=0.3)
    plt.ylim(0, 100)

    safe_base = os.path.basename(osr_obj.file_path).replace('.osr', '')
    safe_base = re.sub(r'[\\/*?:"<>|]', '_', safe_base)
    output_path = os.path.join(output_dir, safe_base + "_life.png")
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
    return output_path

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
        delta_list, matched_pairs = match_notes_and_presses(osu_obj, osr_obj)
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
