import json
import os
import datetime

from collections import Counter
from typing import Optional
from nonebot.log import logger
from nonebot import get_plugin_config

from ..algorithm.utils import malody_mods_to_osu_mods

from ..file.osr_file_parser import osr_file, ReplayEvent
from ..file.mr_file_parser import mr_file
from ..config import Config

config = get_plugin_config(Config)

# 辅助函数
def ms(beats, bpm, offset):
    return 1000 * (60 / bpm) * beats + offset

def beat(beat_arr):
    return beat_arr[0] + beat_arr[1] / beat_arr[2]

def col(column, keys):
    return int(512 * (2 * column + 1) / (2 * keys))

def convert_mc_to_osu(mc_file_path: str, output_dir: Optional[str] = None) -> str:
    """
    将 .mc 文件转换为 .osu 文件
    本函数修改自 https://github.com/Jakads/malody2osu/blob/master/convert.py
    
    Args:
        mc_file_path: .mc 文件路径
        output_dir: 输出目录，如果为 None 则输出到原文件所在目录
        
    Returns:
        转换后的 .osu 文件路径
        
    Raises:
        ValueError: 如果文件不是有效的 .mc 文件
        Exception: 转换过程中的其他错误
    """
    # 检查文件
    if not os.path.exists(mc_file_path):
        raise FileNotFoundError(f"文件不存在: {mc_file_path}")
    if not mc_file_path.lower().endswith('.mc'):
        raise ValueError(f"文件不是 .mc 格式: {mc_file_path}")

    # 读取 JSON
    try:
        with open(mc_file_path, 'r', encoding='utf-8') as f:
            mc_data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"无效的 JSON 格式: {e}")

    # 验证基础字段
    if 'meta' not in mc_data:
        raise ValueError("无效的 .mc 文件: 缺少 'meta' 字段")
    meta = mc_data['meta']
    if meta.get('mode') != 0:
        raise ValueError("只支持 Key 模式 (mode 0) 的 .mc 文件")

    if 'mode_ext' not in meta or 'column' not in meta['mode_ext']:
        raise ValueError("无效的 .mc 文件: 缺少 'mode_ext.column' 字段")
    keys = meta['mode_ext']['column']

    if 'time' not in mc_data or not mc_data['time']:
        raise ValueError("无效的 .mc 文件: 缺少 'time' 字段或为空")
    line = mc_data['time']

    if 'note' not in mc_data:
        raise ValueError("无效的 .mc 文件: 缺少 'note' 字段")
    note = mc_data['note']

    effect = mc_data.get('effect', [])

    # 提取音效 note（type != 0 的第一个）
    soundnote = {}
    for n in note:
        if n.get('type', 0) != 0:
            soundnote = n
            break

    # 计算 BPM 和偏移（完全照搬 ref.py 的累积算法）
    bpm = [line[0]['bpm']]
    bpmoffset = [-soundnote.get('offset', 0)]  # 初始偏移

    if len(line) > 1:
        j = 0
        lastbeat = line[0]['beat']
        for x in line[1:]:
            bpm.append(x['bpm'])
            # 计算绝对时间偏移
            offset = ms(beat(x['beat']) - beat(lastbeat), line[j]['bpm'], bpmoffset[j])
            bpmoffset.append(offset)
            j += 1
            lastbeat = x['beat']

    bpmcount = len(bpm)

    # 元数据
    title = meta["song"]["title"]
    artist = meta["song"]["artist"]
    creator = meta["creator"]
    version = meta["version"]
    background = meta.get("background", "")
    preview = meta.get("preview", -1)
    title_org = meta['song'].get('titleorg', title)
    artist_org = meta['song'].get('artistorg', artist)
    sound_file = soundnote.get('sound', '') if soundnote else ''

    # 输出路径
    if output_dir is None:
        output_dir = os.path.dirname(mc_file_path)
    base_name = os.path.splitext(os.path.basename(mc_file_path))[0]
    output_path = os.path.join(output_dir, f"{base_name}.osu")

    # 构建 .osu 内容
    lines = [
        'osu file format v14',
        '',
        '[General]',
        f'AudioFilename: {sound_file}',
        'AudioLeadIn: 0',
        f'PreviewTime: {preview}',
        'Countdown: 0',
        'SampleSet: Soft',
        'StackLeniency: 0.7',
        'Mode: 3',
        'LetterboxInBreaks: 0',
        'SpecialStyle: 0',
        'WidescreenStoryboard: 0',
        '',
        '[Editor]',
        'DistanceSpacing: 1.2',
        'BeatDivisor: 4',
        'GridSize: 8',
        'TimelineZoom: 2.4',
        '',
        '[Metadata]',
        f'Title:{title}',
        f'TitleUnicode:{title_org}',
        f'Artist:{artist}',
        f'ArtistUnicode:{artist_org}',
        f'Creator:{creator}',
        f'Version:{version}',
        'Source:Malody',
        'Tags:Malody Convert by Jakads',
        'BeatmapID:0',
        'BeatmapSetID:-1',
        '',
        '[Difficulty]',
        f'HPDrainRate:{config.default_convert_hp}',
        f'CircleSize:{keys}',
        f'OverallDifficulty:{config.default_convert_od}',
        'ApproachRate:5',
        'SliderMultiplier:1.4',
        'SliderTickRate:1',
        '',
        '[Events]',
        '//Background and Video events',
        f'0,0,"{background}",0,0',
        '',
        '[TimingPoints]'
    ]

    # 红色 Timing Points（BPM 点）
    for i in range(bpmcount):
        meter = line[i].get('sign', 4)
        lines.append(f'{int(bpmoffset[i])},{60000 / bpm[i]},{meter},1,0,0,1,0')

    # 绿色 Timing Points（SV 点）
    for sv in effect:
        sv_beat = beat(sv['beat'])
        # 找到所属 BPM 段（最后一个节拍 ≤ sv_beat 的段）
        idx = 0
        for i, b in enumerate(line):
            if beat(b['beat']) > sv_beat:
                break
            idx = i
        delta_beat = sv_beat - beat(line[idx]['beat'])
        sv_time = ms(delta_beat, bpm[idx], bpmoffset[idx])
        scroll = sv.get('scroll', 1.0)
        sv_value = "1E+308" if scroll == 0 else 100 / abs(scroll)
        meter = line[idx].get('sign', 4)
        lines.append(f'{int(sv_time)},-{sv_value},{meter},1,0,0,0,0')

    lines.append('')
    lines.append('[HitObjects]')

    # 音符
    for n in note:
        if n.get('type', 0) != 0:
            continue  # 跳过音效

        n_beat = beat(n['beat'])
        # 找到所属 BPM 段
        idx = 0
        for i, b in enumerate(line):
            if beat(b['beat']) > n_beat:
                break
            idx = i
        delta_beat = n_beat - beat(line[idx]['beat'])
        n_time = ms(delta_beat, bpm[idx], bpmoffset[idx])
        x = col(n['column'], keys)

        # 长按或普通
        if 'endbeat' in n:
            end_beat = beat(n['endbeat'])
            idx_end = 0
            for i, b in enumerate(line):
                if beat(b['beat']) > end_beat:
                    break
                idx_end = i
            delta_end = end_beat - beat(line[idx_end]['beat'])
            end_time = ms(delta_end, bpm[idx_end], bpmoffset[idx_end])
            type_str = '128'
            extra = f',0,{int(end_time)}:0:0:0:'
        else:
            type_str = '1'
            extra = ',0,0:0:0:'

        vol = n.get('vol', 100)
        sound = n.get('sound', 0)
        extra += f'{vol}:{sound}'

        line_str = f'{x},192,{int(n_time)},{type_str},0,0,{extra}'
        lines.append(line_str)

    # 写入文件
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
    except Exception as e:
        raise Exception(f"写入 .osu 文件失败: {e}")

    return output_path

def convert_mr_to_osr(mr_obj: mr_file) -> osr_file:
    """
    将 mr_file 对象转换为 osr_file 实例，使其兼容现有绘图和分析代码。
    返回的 osr_file 实例已经设置好所有属性，可直接用于后续流程。
    """

    # 创建一个 osr_file 实例，跳过实际文件解析
    osr = osr_file.__new__(osr_file)
    osr._init_derived_attrs()
    # 设置基本属性
    osr.file_path = mr_obj.file_path
    osr.status = mr_obj.status  # 可能为 "OK" 或 "ParseError"
    osr.player_name = "ConvertedFromMalody"
    osr.mod, osr.mods = malody_mods_to_osu_mods(mr_obj.mods_flags)
    
    # 计算速度因子（用于时间缩放）
    # Malody 速度模组：Dash=1.2x, Slow=0.8x, Rush=1.5x
    # 注意：时间戳已经应用了速度模组，所以我们需要逆缩放
    speed_factor = 1.0
    if mr_obj.mods_flags & (1 << 4):   # Dash (bit 5)
        speed_factor *= 1.2
    if mr_obj.mods_flags & (1 << 8):   # Slow (bit 9)
        speed_factor *= 0.8
    if mr_obj.mods_flags & (1 << 5):   # Rush (bit 6) - 对应 DoubleTime
        speed_factor *= 1.5
    osr.speed_factor = speed_factor
    osr.corrector = 1.0 / speed_factor if speed_factor != 0 else 1.0

    # 判定映射：best->320, cool->200, good->100, miss->0
    osr.judge = {
        "320": mr_obj.best_count,
        "300": 0,
        "200": mr_obj.cool_count,
        "100": mr_obj.good_count,
        "50": 0,
        "0": mr_obj.miss_count,
    }
    # 设为 0 兼容性优先
    osr.score = 0  
    osr.ratio = 0
    # 以malody计分方式计算 acc 
    tot_obj = mr_obj.best_count + mr_obj.cool_count + mr_obj.good_count + mr_obj.miss_count
    if tot_obj > 0:
        osr.acc = (mr_obj.best_count * 100 + mr_obj.cool_count * 75 + mr_obj.good_count * 40) / (tot_obj * 100) * 100
    else:
        osr.acc = 0.0
    # 时间戳转换：Unix 秒 -> datetime
    osr.timestamp = datetime.datetime.fromtimestamp(mr_obj.timestamp) if mr_obj.timestamp else datetime.datetime.min

    # HP数据不存在
    osr.life_bar_graph = ""

    # 以下属性从动作序列生成
    osr.pressset = [[] for _ in range(18)]
    osr.intervals = []
    osr.intervals_raw = []
    osr.press_times = []
    osr.press_times_raw = []
    osr.press_events = []
    osr.press_events_raw = []
    osr.play_data = []

    # 按时间排序动作
    actions = sorted(mr_obj.actions, key=lambda x: x[0])
    if not actions:
        osr.status = "tooFewKeys"
        return osr

    # 记录当前每列的按键状态 (True/False)
    current_state = [False] * 18
    # 记录每列按下开始时间（原始时间）
    pressed_start_raw = [None] * 18
    # 记录每列按下开始时间（逆缩放时间）
    pressed_start_scaled = [None] * 18
    # 上一个事件的时间（用于计算 time_delta）
    prev_time_raw = None
    prev_time_scaled = None
    # 当前累积时间（用于绝对时间）
    for time_raw, action, col in actions:
        if col >= 18:
            continue  # 忽略超出轨道
        
        # 计算逆缩放时间（用于与谱面匹配）
        time_scaled = int(time_raw / speed_factor) if speed_factor != 0 else time_raw
        
        # 根据 action 更新状态
        if action == 1:  # 按下
            if not current_state[col]:
                current_state[col] = True
                pressed_start_raw[col] = time_raw
                pressed_start_scaled[col] = time_scaled
                # 记录按下事件（使用逆缩放时间，用于与谱面匹配）
                osr.press_times.append(time_scaled)
                osr.press_events.append((col, time_scaled))
                # 同时保存原始时间
                osr.press_times_raw.append(time_raw)
                osr.press_events_raw.append((col, time_raw))
        elif action == 2:  # 释放
            if current_state[col]:
                current_state[col] = False
                if pressed_start_raw[col] is not None:
                    duration_raw = time_raw - pressed_start_raw[col]
                    duration_scaled = time_scaled - pressed_start_scaled[col]
                    if duration_raw >= 0:
                        osr.pressset[col].append(int(duration_raw))
                    pressed_start_raw[col] = None
                    pressed_start_scaled[col] = None
        # 构建当前时刻的按键掩码
        keys_mask = 0
        for c in range(18):
            if current_state[c]:
                keys_mask |= (1 << c)

        # 生成 play_data 事件：需要相对时间差（使用原始时间）
        if prev_time_raw is None:
            delta_raw = time_raw
            delta_scaled = time_scaled
        else:
            delta_raw = time_raw - prev_time_raw
            delta_scaled = time_scaled - prev_time_scaled
        if delta_raw < 0:
            delta_raw = 0
        if delta_scaled < 0:
            delta_scaled = 0
        # 创建事件对象（使用原始时间差，保持内部一致性）
        event = ReplayEvent(delta_raw, keys_mask)
        osr.play_data.append(event)
        osr.intervals.append(delta_raw)
        osr.intervals_raw.append(delta_raw)
        prev_time_raw = time_raw
        prev_time_scaled = time_scaled

    # 计算采样率
    if osr.intervals:
        interval_counts = Counter(osr.intervals)
        most_common_interval, _ = interval_counts.most_common(1)[0]
        osr.sample_rate = 1000 / most_common_interval if most_common_interval > 0 else float('inf')
    else:
        osr.sample_rate = float('inf')

    # 过滤无效轨道（少于5次按压的轨道视为无效，但保留原样，仅用于状态）
    valid_pressset = [p for p in osr.pressset if len(p) > 5]
    if len(valid_pressset) < 2:
        osr.status = "tooFewKeys"
    else:
        osr.status = "OK"

    # 时间戳已包含速度模组，无需再缩放
    osr.corrector = 1.0

    logger.debug(f"按下事件总数(len(press_events)): {len(osr.press_events)}")
    logger.debug(f"按下事件总数(len(press_times))：{len(osr.press_times)}")
    logger.debug(f"按下事件时间样本（前10个）：{str(osr.press_times[:10])}")
    logger.debug(f"按下事件时间样本（后10个）：{str(osr.press_times[-10:])}")
    return osr