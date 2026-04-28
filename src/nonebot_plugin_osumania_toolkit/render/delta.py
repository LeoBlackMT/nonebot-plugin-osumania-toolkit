import re
import os
import numpy as np
import matplotlib
matplotlib.use('Agg')

from matplotlib import pyplot as plt

plt.rcParams['axes.unicode_minus'] = False

from ..parser.osr_file_parser import osr_file
from ..parser.osu_file_parser import osu_file

from .utils import safe_plot, match_for_visualization

@safe_plot
def plot_delta(osr_obj: osr_file, osu_obj: osu_file, output_dir: str):
    """
    绘制 delta_t 分布直方图（按列着色）
    osr_obj: osr_file 实例（已 process）
    osu_obj: osu_file 实例（已 process）
    output_dir: 输出目录
    """
    delta_list, _matched_pairs = match_for_visualization(osu_obj, osr_obj)

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