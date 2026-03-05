import re
import os
import numpy as np

from matplotlib import pyplot as plt
from matplotlib import colors
from scipy.fft import fft, fftfreq

from nonebot_plugin_osumania_toolkit.file.osr_file_parser import osr_file
from nonebot_plugin_osumania_toolkit.file.osu_file_parser import osu_file

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