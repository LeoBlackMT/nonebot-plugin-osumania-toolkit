"""Convert Malody .mc charts to osu! .osu format."""
from __future__ import annotations

import json
import os
from collections import Counter
from typing import Optional

from nonebot import get_plugin_config
from nonebot.log import logger

from ...config import Config

config = get_plugin_config(Config)


def _ms(beats: float, bpm: float, offset: float) -> float:
    return 1000.0 * (60.0 / bpm) * beats + offset


def _beat(beat_arr: list[int]) -> float:
    return beat_arr[0] + beat_arr[1] / beat_arr[2]


def _col(column: int, keys: int) -> int:
    return int(512.0 * (2.0 * column + 1.0) / (2.0 * keys))


def convert_mc_to_osu(mc_file_path: str, output_dir: Optional[str] = None) -> str:
    """
    Summary:
        将 .mc 文件转换为 .osu 文件。
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
    if not os.path.exists(mc_file_path):
        raise FileNotFoundError(f"文件不存在: {mc_file_path}")
    if not mc_file_path.lower().endswith('.mc'):
        raise ValueError(f"文件不是 .mc 格式: {mc_file_path}")

    try:
        with open(mc_file_path, 'r', encoding='utf-8') as f:
            mc_data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"无效的 JSON 格式: {e}")

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

    soundnote = {}
    for n in note:
        if n.get('type', 0) != 0:
            soundnote = n
            break

    bpm = [line[0]['bpm']]
    bpmoffset = [-soundnote.get('offset', 0)]

    if len(line) > 1:
        j = 0
        lastbeat = line[0]['beat']
        for x in line[1:]:
            bpm.append(x['bpm'])
            offset = _ms(_beat(x['beat']) - _beat(lastbeat), line[j]['bpm'], bpmoffset[j])
            bpmoffset.append(offset)
            j += 1
            lastbeat = x['beat']

    bpmcount = len(bpm)

    title = meta["song"]["title"]
    artist = meta["song"]["artist"]
    creator = meta["creator"]
    version = meta["version"]
    background = meta.get("background", "")
    preview = meta.get("preview", -1)
    title_org = meta['song'].get('titleorg', title)
    artist_org = meta['song'].get('artistorg', artist)
    sound_file = soundnote.get('sound', '') if soundnote else ''

    if output_dir is None:
        output_dir = os.path.dirname(mc_file_path)
    base_name = os.path.splitext(os.path.basename(mc_file_path))[0]
    output_path = os.path.join(output_dir, f"{base_name}.osu")

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

    for i in range(bpmcount):
        meter = line[i].get('sign', 4)
        lines.append(f'{int(bpmoffset[i])},{60000 / bpm[i]},{meter},1,0,0,1,0')

    for sv in effect:
        sv_beat = _beat(sv['beat'])
        idx = 0
        for i, b in enumerate(line):
            if _beat(b['beat']) > sv_beat:
                break
            idx = i
        delta_beat = sv_beat - _beat(line[idx]['beat'])
        sv_time = _ms(delta_beat, bpm[idx], bpmoffset[idx])
        scroll = sv.get('scroll', 1.0)
        sv_value = "1E+308" if scroll == 0 else 100 / abs(scroll)
        meter = line[idx].get('sign', 4)
        lines.append(f'{int(sv_time)},-{sv_value},{meter},1,0,0,0,0')

    lines.append('')
    lines.append('[HitObjects]')

    converted_notes = []
    start_time_counter: Counter[tuple[int, int]] = Counter()

    for n in note:
        if n.get('type', 0) != 0:
            continue

        column_idx = int(n['column'])

        n_beat = _beat(n['beat'])
        idx = 0
        for i, b in enumerate(line):
            if _beat(b['beat']) > n_beat:
                break
            idx = i
        delta_beat = n_beat - _beat(line[idx]['beat'])
        n_time = _ms(delta_beat, bpm[idx], bpmoffset[idx])
        n_time_ms = int(n_time)
        x = _col(column_idx, keys)
        start_time_counter[(column_idx, n_time_ms)] += 1

        end_time_ms = None
        if 'endbeat' in n:
            end_beat = _beat(n['endbeat'])
            idx_end = 0
            for i, b in enumerate(line):
                if _beat(b['beat']) > end_beat:
                    break
                idx_end = i
            delta_end = end_beat - _beat(line[idx_end]['beat'])
            end_time = _ms(delta_end, bpm[idx_end], bpmoffset[idx_end])
            end_time_ms = int(end_time)
            type_str = '128'
        else:
            type_str = '1'

        converted_notes.append({
            'x': x, 'column_idx': column_idx, 'start_time_ms': n_time_ms,
            'end_time_ms': end_time_ms, 'type_str': type_str,
            'vol': n.get('vol', 100), 'sound': n.get('sound', 0),
        })

    adjusted_tail_count = 0
    for item in converted_notes:
        end_time_ms = item['end_time_ms']
        if end_time_ms is None:
            continue
        start_time_ms = item['start_time_ms']
        column_idx = item['column_idx']
        adjusted_end = int(end_time_ms)
        while adjusted_end > start_time_ms and start_time_counter[(column_idx, adjusted_end)] > 0:
            adjusted_end -= 1
        if adjusted_end <= start_time_ms:
            adjusted_end = start_time_ms + 1
        if adjusted_end != end_time_ms:
            item['end_time_ms'] = adjusted_end
            adjusted_tail_count += 1

    if adjusted_tail_count > 0:
        logger.debug(f".mc 转换中检测到 {adjusted_tail_count} 个 LN 尾同毫秒冲突，已自动微调结束时间提升兼容性")

    for item in converted_notes:
        x = item['x']
        n_time_ms = item['start_time_ms']
        end_time_ms = item['end_time_ms']
        type_str = item['type_str']
        vol = item['vol']
        sound = item['sound']

        if end_time_ms is not None:
            line_str = f'{x},192,{n_time_ms},{type_str},{sound},{end_time_ms}:0:0:0:{vol}:'
        else:
            line_str = f'{x},192,{n_time_ms},{type_str},{sound},0:0:0:{vol}:'
        lines.append(line_str)

    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
    except Exception as e:
        raise Exception(f"写入 .osu 文件失败: {e}")

    return output_path
