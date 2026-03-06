import re
import os
import numpy as np

from matplotlib import pyplot as plt
from matplotlib import colors
from scipy.fft import fft, fftfreq

from ..file.osr_file_parser import osr_file
from ..file.osu_file_parser import osu_file

from ..algorithm.utils import match_notes_and_presses


def plot_pressingtime(data: dict, output_dir: str) -> str:
    """
    绘制按压时长分布图（各轨道颜色区分）
    参数:
        data: osr_file.get_data 返回的字典
        output_dir: 输出目录
    返回:
        生成的图片路径
    """
    pressset = data["pressset"]
    mod = data["mod"]
    player_name = data["player_name"]
    timestamp = data["timestamp"]
    file_basename = data["file_path"].with_suffix("")
    acc = data["accuracy"]
    ratio = data["ratio"]
    score = data["score"]
    gekis = data["judge"]["320"]
    n300 = data["judge"]["300"]
    katus = data["judge"]["200"]
    n100 = data["judge"]["100"]
    n50 = data["judge"]["50"]
    misses = data["judge"]["0"]

    # 计算速度修正系数
    corrector = 1
    if mod != 0:
        mod_bin = bin(mod)[2:].zfill(32)
        if mod_bin[-7] == '1':
            corrector = 2/3
        elif mod_bin[-9] == '1':
            corrector = 4/3

    # 构建绘图数据
    basetime = []
    presstime = []
    for key_presses in pressset:
        if key_presses:
            maxpress = max(key_presses)
            t = np.linspace(0, maxpress, maxpress + 1) * corrector
            count = np.zeros(maxpress + 1)
            for d in key_presses:
                if d >= 0:
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

    plt.grid()
    plt.xticks(fontsize=15)
    plt.yticks(fontsize=15)
    plt.xlim(0, 160)
    plt.xlabel('pressing time (ms)', fontsize=15)
    plt.ylabel('count', fontsize=15)
    plt.legend(shadow=True, fontsize=10, ncol=2)
    plt.text(0.5, 0.5,
             mod[4:].replace("|", "\n") +
             f"\nscores={score}\naccuracy={acc:.2f}%\nRatio={ratio:.2f}" if ratio != 0 else "Inf",
             va='bottom', ha='left')
    plt.text(159.5, 0.5, presscount + f"\nRI={corrector:.2f}", ha='right', va='bottom')
    plt.title(f"{file_basename}\n,{player_name},{timestamp}")

    safe_base = re.sub(r'[\\/*?:"<>|]', '_', file_basename)
    output_path = os.path.join(output_dir, safe_base + "_duration.png")
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
    return output_path

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

    plt.figure(figsize=(12, 6))
    bins = np.linspace(-200, 200, 100)
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

def plot_spectrum(data: dict, output_dir: str) -> str:
    """
    生成脉冲序列频谱图
    参数:
        data: presssaver 返回的字典
        output_dir: 输出目录
    返回:
        生成的图片路径
    """
    press_times = data["press_times"]
    sample_rate = data["sample_rate"]
    player_name = data["player_name"]
    file_basename = data["file_basename"]

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
    plt.title(f"脉冲序列频谱\n玩家: {player_name} | 文件: {file_basename} | 采样率: {sample_rate:.0f} Hz",
              fontweight='bold', fontsize=12)
    plt.xlabel("频率 (Hz)")
    plt.ylabel("幅度")
    plt.xlim(0, 500)
    plt.grid(True, alpha=0.3)

    safe_base = re.sub(r'[\\/*?:"<>|]', '_', file_basename)
    output_path = os.path.join(output_dir, safe_base + "_spectrum.png")
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
    return output_path

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
    plt.xlabel('物件时间 (ms)')
    plt.ylabel('Delta t (玩家 - 物件) ms')
    plt.title(f'Delta t 散点图 - {osr_obj.player_name}')
    plt.grid(alpha=0.3)

    safe_base = os.path.basename(osr_obj.file_path).replace('.osr', '')
    safe_base = re.sub(r'[\\/*?:"<>|]', '_', safe_base)
    output_path = os.path.join(output_dir, safe_base + "_delta_scatter.png")
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
    return output_path

def plot_life(osr_obj: osr_file, output_dir: str) -> str:
    """
    绘制玩家血量随时间变化图
    osr_obj: osr_file 实例（已 process）
    output_dir: 输出目录
    返回:
        生成的图片路径
    """
    life_str = osr_obj.get_data()["life_bar_graph"]
    if not life_str:
        raise ValueError("无生命条数据")

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
            life = float(parts[1])
            points.append((t, life))
        except ValueError:
            continue

    if not points:
        raise ValueError("生命条数据解析失败")

    times, lives = zip(*points)

    plt.figure(figsize=(12, 4))
    plt.plot(times, lives, color='green', linewidth=1.5)
    plt.fill_between(times, 0, lives, alpha=0.2, color='green')
    plt.xlabel('时间 (ms)')
    plt.ylabel('血量')
    plt.title(f'血量变化 - {osr_obj.player_name}')
    plt.grid(alpha=0.3)
    plt.ylim(0, 100)

    safe_base = os.path.basename(osr_obj.file_path).replace('.osr', '')
    safe_base = re.sub(r'[\\/*?:"<>|]', '_', safe_base)
    output_path = os.path.join(output_dir, safe_base + "_life.png")
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
    return output_path

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
    mod = data["mod"]
    player_name = data["player_name"]
    # timestamp = data["timestamp"]
    file_basename = os.path.basename(osr_obj.file_path).replace('.osr', '')
    # acc = data["accuracy"]
    # ratio = data["ratio"]
    # score = data["score"]
    # judge = data["judge"]
    press_times = data["press_times"]
    sample_rate = data["sample_rate"]

    # 计算速度修正系数（用于按压分布图）
    corrector = 1
    if mod != 0:
        mod_bin = bin(mod)[2:].zfill(32) if isinstance(mod, int) else ''
        if len(mod_bin) >= 7 and mod_bin[-7] == '1':
            corrector = 2/3
        elif len(mod_bin) >= 9 and mod_bin[-9] == '1':
            corrector = 4/3

    # 构建按压分布图数据（复用 plot_pressingtime 的逻辑）
    basetime = []
    presstime_count = []
    for key_presses in pressset:
        if key_presses:
            maxpress = max(key_presses)
            t = np.linspace(0, maxpress, maxpress + 1) * corrector
            count = np.zeros(maxpress + 1)
            for d in key_presses:
                if d >= 0:
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
        ax1.set_title('按压时长分布')
        ax1.legend(fontsize='x-small', ncol=2)
        ax1.grid(alpha=0.3)

        # 右上：频谱图
        ax2.plot(xf, amp, color='darkgreen', linewidth=1)
        ax2.fill_between(xf, amp, alpha=0.15, color='green')
        ax2.set_xlim(0, 500)
        ax2.set_xlabel('频率 (Hz)')
        ax2.set_ylabel('幅度')
        ax2.set_title(f'脉冲序列频谱 (采样率 {sample_rate:.0f} Hz)')
        ax2.grid(alpha=0.3)

        # 左下：delta_t 直方图
        from ..algorithm.utils import match_notes_and_presses
        delta_list, _ = match_notes_and_presses(osu_obj, osr_obj)
        if delta_list:
            deltas = [d for _, d in delta_list]
            ax3.hist(deltas, bins=50, alpha=0.7, color='steelblue', edgecolor='black')
            ax3.set_xlabel('Delta t (ms)')
            ax3.set_ylabel('频次')
            ax3.set_title('Delta t 分布')
            ax3.grid(alpha=0.3)
        else:
            ax3.text(0.5, 0.5, '无匹配数据', ha='center', va='center')
            ax3.set_title('Delta t 分布')

        # 右下：delta_t 散点图
        _, matched_pairs = match_notes_and_presses(osu_obj, osr_obj)
        if matched_pairs:
            note_times = [p[1] for p in matched_pairs]
            deltas_scatter = [p[2] - p[1] for p in matched_pairs]
            ax4.scatter(note_times, deltas_scatter, s=1, alpha=0.5, c='blue')
            ax4.axhline(y=0, color='red', linestyle='--', linewidth=0.5)
            ax4.set_xlabel('物件时间 (ms)')
            ax4.set_ylabel('Delta t (ms)')
            ax4.set_title('Delta t 散点图')
            ax4.grid(alpha=0.3)
        else:
            ax4.text(0.5, 0.5, '无匹配数据', ha='center', va='center')
            ax4.set_title('Delta t 散点图')

        fig.suptitle(f'综合回放分析 - {player_name} | {file_basename}', fontsize=14, fontweight='bold')
        plt.tight_layout()
        output_path = os.path.join(output_dir, re.sub(r'[\\/*?:"<>|]', '_', file_basename) + "_comprehensive.png")
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
        ax1.set_title('按压时长分布')
        ax1.legend(fontsize='x-small', ncol=2)
        ax1.grid(alpha=0.3)

        # 右：频谱
        ax2.plot(xf, amp, color='darkgreen', linewidth=1)
        ax2.fill_between(xf, amp, alpha=0.15, color='green')
        ax2.set_xlim(0, 500)
        ax2.set_xlabel('频率 (Hz)')
        ax2.set_ylabel('幅度')
        ax2.set_title(f'脉冲序列频谱 (采样率 {sample_rate:.0f} Hz)')
        ax2.grid(alpha=0.3)

        fig.suptitle(f'回放分析 - {player_name} | {file_basename}', fontsize=14, fontweight='bold')
        plt.tight_layout()
        output_path = os.path.join(output_dir, re.sub(r'[\\/*?:"<>|]', '_', file_basename) + "_dual.png")

    plt.savefig(output_path)
    plt.close()
    return output_path