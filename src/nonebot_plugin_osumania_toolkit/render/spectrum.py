import re
import os
import numpy as np
import matplotlib
matplotlib.use('Agg')

from matplotlib import pyplot as plt
from scipy.fft import fft, fftfreq

plt.rcParams['axes.unicode_minus'] = False

from ..parser.osr_file_parser import osr_file

from .utils import safe_plot

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