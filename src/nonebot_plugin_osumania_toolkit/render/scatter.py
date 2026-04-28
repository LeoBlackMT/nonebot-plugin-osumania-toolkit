import re
import os
import matplotlib
matplotlib.use('Agg')

from matplotlib import pyplot as plt

plt.rcParams['axes.unicode_minus'] = False

from ..parser.osr_file_parser import osr_file
from ..parser.osu_file_parser import osu_file

from .utils import safe_plot, match_for_visualization

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

    _delta_list, matched_pairs = match_for_visualization(osu_obj, osr_obj)

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