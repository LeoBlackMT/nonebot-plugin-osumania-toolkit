import re
import os
import matplotlib
matplotlib.use('Agg')

from matplotlib import pyplot as plt

plt.rcParams['axes.unicode_minus'] = False

from ..parser.osr_file_parser import osr_file

from .utils import safe_plot

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