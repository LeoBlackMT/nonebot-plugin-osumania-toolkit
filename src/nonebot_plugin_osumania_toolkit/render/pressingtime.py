import re
import os
import numpy as np
import matplotlib
matplotlib.use('Agg')

from matplotlib import pyplot as plt
from matplotlib import colors

plt.rcParams['axes.unicode_minus'] = False

from ..parser.osr_file_parser import osr_file

from .utils import safe_plot

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