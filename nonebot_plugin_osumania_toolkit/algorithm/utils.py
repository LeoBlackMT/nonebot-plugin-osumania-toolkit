import bisect
import json
import os

from nonebot.log import logger
from pathlib import Path

from ..file.osr_file_parser import osr_file
from ..file.osu_file_parser import osu_file

from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
    PrivateMessageEvent,
)

async def send_forward_text_messages(bot: Bot, event: MessageEvent, texts: list[str], nickname: str = "Bot"):
    """发送合并转发消息，适用于文本较多的情况"""
    nodes = [
        MessageSegment.node_custom(
            user_id=int(bot.self_id),
            nickname=nickname,
            content=Message(text),
        )
        for text in texts
    ]

    if isinstance(event, GroupMessageEvent):
        await bot.call_api("send_group_forward_msg", group_id=event.group_id, messages=nodes)
    elif isinstance(event, PrivateMessageEvent):
        await bot.call_api("send_private_forward_msg", user_id=event.user_id, messages=nodes)
    else:
        for text in texts:
            await bot.send(text)

def match_notes_and_presses(osu: osu_file, osr: osr_file):
    """
    匹配物件和按下事件，返回匹配的列表。
    参数:
        osu: osu文件实例
        osr: osr文件实例
    返回:
        list of (col, delta_t) 差值列表
        list of (col, note_time, press_time) 详细匹配对
    """
    note_times_by_col = osu.note_times

    # 对同一 (osu, osr) 对象复用匹配结果，减少分析与绘图重复计算。
    cache = getattr(osr, "_match_notes_cache", None)
    if cache is None:
        cache = {}
        setattr(osr, "_match_notes_cache", cache)

    press_events_ref = getattr(osr, "press_events_float", None) or osr.press_events

    # 通过采样签名避免仅按长度命中缓存，导致复用过期匹配结果。
    def _events_signature(events: list[tuple[int, float]]) -> tuple:
        n = len(events)
        if n == 0:
            return (0,)
        pick_idx = sorted({0, n // 2, n - 1})
        sample = tuple((int(events[i][0]), round(float(events[i][1]), 3)) for i in pick_idx)
        return (n, sample)

    events_sig = _events_signature(press_events_ref)
    cache_key = (
        id(osu),
        id(note_times_by_col),
        events_sig,
        int(getattr(osr, "mod", 0) or 0),
        float(getattr(osu, "od", 0.0) or 0.0),
    )
    cached = cache.get(cache_key)
    if cached is not None:
        cached_delta = cached[0]
        cached_frac_count = sum(1 for _, d in cached_delta if abs(float(d) - round(float(d))) > 1e-6)
        logger.debug(
            f"match_notes_and_presses 命中缓存: events_sig={events_sig}, "
            f"delta_count={len(cached_delta)}, frac_count={cached_frac_count}"
        )
        return cached

    all_notes = [t for times in note_times_by_col.values() for t in times]
    if not all_notes:
        cache[cache_key] = ([], [])
        return cache[cache_key]
    min_note = min(all_notes)
    max_note = max(all_notes)
    buffer = 5000

    # 获取按下事件（使用已缩放的时间，用于匹配谱面）
    # 对于普通.osr文件：press_events是实时时间（已应用速度模组）
    # 对于.mr转换的osr文件：press_events是逆缩放时间（用于匹配原始谱面时间）
    press_events = press_events_ref

    # 检查是否启用 Mirror 模组 (MR)
    mod_value = getattr(osr, 'mod', 0)
    mirror = (mod_value & 1073741824) != 0
    if mirror:
        total_cols = osu.column_count
        # 将物理列映射到谱面列
        press_events = [(total_cols - 1 - col, t) for col, t in press_events]

    # 按列整理按下事件，并过滤超出时间范围的事件
    press_by_col = {}
    for col, t in press_events:
        if min_note - buffer <= t <= max_note + buffer:
            press_by_col.setdefault(col, []).append(t)

    for col in press_by_col:
        press_by_col[col].sort()

    delta_list = []
    matched_pairs = []
    max_diff = 188 - 3 * osu.od  # 判定窗口，单位 ms

    for col in note_times_by_col:
        notes = note_times_by_col[col]
        presses = press_by_col.get(col, [])
        if not presses:
            continue
        used = [False] * len(presses)
        for note in notes:
            idx = bisect.bisect_left(presses, note)
            best = None
            best_dist = None
            # 向左搜索
            i = idx - 1
            while i >= 0:
                if not used[i]:
                    dist = abs(presses[i] - note)
                    if dist <= max_diff:
                        best = i
                        best_dist = dist
                    break
                i -= 1
            # 向右搜索
            i = idx
            while i < len(presses):
                if not used[i]:
                    dist = abs(presses[i] - note)
                    if dist <= max_diff:
                        if best is None or dist < best_dist:
                            best = i
                            best_dist = dist
                    break
                i += 1
            if best is not None:
                used[best] = True
                delta_list.append((col, presses[best] - note))
                matched_pairs.append((col, note, presses[best]))
    logger.debug(f"匹配到的点数量: {len(delta_list)}")
    frac_count = sum(1 for _, d in delta_list if abs(float(d) - round(float(d))) > 1e-6)
    delta_preview = [round(float(d), 3) for _, d in delta_list[:8]]
    logger.debug(
        f"match_notes_and_presses 计算完成: events_sig={events_sig}, "
        f"frac_count={frac_count}, preview={delta_preview}"
    )
    logger.debug(f"匹配到的最后物件时间: {max(note for _, note, _ in matched_pairs) if matched_pairs else 0} ms")
    cache[cache_key] = (delta_list, matched_pairs)
    return cache[cache_key]

def parse_cmd(cmd_text: str):
    # 辅助变量
    cmd_parts = cmd_text.split()
    parsed_mods = []
    err_msg = []
    mod_display = "NM"  # 用于显示模组的字符串

    # 命令参数
    speed_rate = 1.0
    od_flag = None
    bid = None
    cvt_flag = []

    i = 0
    while i < len(cmd_parts):
        part = cmd_parts[i]

        # 特殊处理：当部分以 "b" 开头且包含 "+" 但无法解析为整数时，尝试拆分
        if part.lower().startswith("b") and "+" in part:
            try:
                # 如果后面没有 + 的情况
                int(part[1:])
                bid = int(part[1:])
                i += 1
                continue
            except ValueError:
                # 进行拆分
                plus_index = part.find('+')
                bid_part = part[:plus_index]
                mod_part = part[plus_index:] 
                cmd_parts[i] = bid_part
                cmd_parts.insert(i + 1, mod_part)
                continue

        # 模组处理
        if part.startswith("+"):
            s = part[1:].upper().replace('+', '')
            known_mods = ["NC", "DT", "HT", "HR", "EZ", "DC", "IN", "HO"]
            known_mods.sort(key=lambda x: -len(x))
            j = 0
            unknown_parts = []
            while j < len(s):
                matched = False
                for code in known_mods:
                    if s.upper().startswith(code, j):
                        parsed_mods.append(code)
                        j += len(code)
                        matched = True
                        break
                if not matched:
                    unknown_parts.append(s[j:])
                    break
            if unknown_parts:
                err_msg.append(f"不支持的 mods: {unknown_parts}; ")
            # 将解析到的模组映射到行为
            for code in parsed_mods:
                match code:
                    case "HR" | "EZ":
                        match od_flag:
                            case None:
                                od_flag = code
                            case "HR" | "EZ":
                                err_msg.append(f"EZ/HR 模组冲突: 已设置 {od_flag}, 当前 {code}; ")
                            case _:
                                err_msg.append(f"OD覆写与 EZ/HR 模组冲突: 已设置 OD{od_flag}, 当前 {code}; ")
                    case "DT" | "NC":
                        speed_rate *= 1.5
                    case "HT" | "DC":
                        speed_rate *= 0.75
                    case "IN":
                        if not cvt_flag:
                            cvt_flag = ["IN"]
                        else:
                            err_msg.append(f"模组冲突: 已设置 {cvt_flag[0]}, 当前 {code}; ")
                    case "HO":
                        if not cvt_flag:
                            cvt_flag = ["HO"]
                        else:
                            err_msg.append(f"模组冲突: 已设置 {cvt_flag[0]}, 当前 {code}; ")
            mod_display = ('+' + '+'.join(parsed_mods)) if parsed_mods else "NM"
            i += 1
            continue

        # 倍速处理
        if part.lower().startswith("x") or part.startswith("*"):
            try:
                value = float(part[1:])
                if 0.25 <= round(value, 3) <= 3.0:
                    speed_rate = round(value, 3)
                else:
                    err_msg.append(f"倍速必须在0.25到3.0之间: {part[1:]}x; ")
            except ValueError:
                err_msg.append(f"无效的倍速: {part[1:]}; ")
            i += 1
            continue

        # OD覆写
        if part.lower().startswith("od"):
            try:
                od_value = float(part[2:])
                if -15 <= od_value <= 15:
                    od_flag = od_value
                else:
                    err_msg.append(f"OD值必须在-15到15之间: OD{od_value}; ")
            except ValueError:
                err_msg.append(f"无效的OD: {part[2:]}; ")
            i += 1
            continue

        # 获取bid
        if part.lower().startswith("b"):
            try:
                bid = int(part[1:])
            except ValueError:
                err_msg.append(f"无效的谱面ID: {part[1:]}; ")
            i += 1
            continue

        i += 1

    return speed_rate, od_flag, cvt_flag, bid, mod_display, err_msg

def is_mc_file(file_path: str) -> bool:
    """
    检查文件是否为有效的 .mc 文件
    
    Args:
        file_path: 文件路径
        
    Returns:
        是否为有效的 .mc 文件
    """
    if not os.path.exists(file_path):
        return False
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 基本验证
        if 'meta' not in data:
            return False
        
        meta = data['meta']
        if 'mode' not in meta or meta['mode'] != 0:
            return False
        
        if 'mode_ext' not in meta or 'column' not in meta['mode_ext']:
            return False
        
        if 'time' not in data or not data['time']:
            return False
        
        if 'note' not in data:
            return False
        
        return True
    except:
        return False
    
def malody_mods_to_osu_mods(malody_flags: int) -> tuple:
    """
    将 Malody 的 mods_flags 转换为 osu! 的 mod 整数值和mod列表。
    
    映射规则：
    - bit 1: Fair -> 忽略
    - bit 2: Luck -> Random (2097152)
    - bit 3: Flip -> Mirror (1073741824)
    - bit 4: Const -> 忽略
    - bit 5: Dash -> 忽略
    - bit 6: Rush -> DoubleTime (64)
    - bit 7: Hide -> Hidden (8)
    - bit 9: Slow -> 忽略
    - bit 10: Death -> 忽略
    """
    osu_mod = 0
    osu_mods = []
    
    if malody_flags & (1 << 1):   # Luck (bit 2)
        osu_mod |= 2097152
        osu_mods.append("Random")
    
    if malody_flags & (1 << 2):   # Flip (bit 3)
        osu_mod |= 1073741824
        osu_mods.append("Mirror")
    
    if malody_flags & (1 << 5):   # Rush (bit 6)
        osu_mod |= 64
        osu_mods.append("DoubleTime")
    
    if malody_flags & (1 << 6):   # Hide (bit 7)
        osu_mod |= 8
        osu_mods.append("Hidden")

    
    # 忽略的mods
    ignored_mods = []
    if malody_flags & (1 << 0):   # Fair (bit 1)
        ignored_mods.append("Fair")
    if malody_flags & (1 << 3):   # Const (bit 4)
        ignored_mods.append("Const")
    if malody_flags & (1 << 4):   # Dash (bit 5)
        ignored_mods.append("Dash")
    if malody_flags & (1 << 8):   # Slow (bit 9)
        ignored_mods.append("Slow")
    if malody_flags & (1 << 9):   # Death (bit 10)
        ignored_mods.append("Death")
    
    if ignored_mods:
        logger.debug(f"忽略的Malody mods: {', '.join(ignored_mods)}")
    
    if not osu_mods:
        osu_mods.append("NoMod")
        
    return osu_mod, osu_mods

def parse_osu_filename(file_path: str) -> dict | None:
    """
    <artist> - <title> (<mapper>) [<difficulty>].osu
    """
    import os
    
    # 提取文件名（去除路径）
    filename = os.path.basename(file_path)

    # 检查扩展名并去除
    if not filename.lower().endswith('.osu'):
        return None
    name_without_ext = filename[:-4]  # 去掉最后的 .osu

    # 提取难度名：位于最后一个 [ ... ] 中
    last_left_bracket = name_without_ext.rfind('[')
    last_right_bracket = name_without_ext.rfind(']')
    if last_left_bracket == -1 or last_right_bracket == -1 or last_left_bracket > last_right_bracket:
        return None  # 缺少有效的难度名括号
    difficulty = name_without_ext[last_left_bracket + 1:last_right_bracket]
    # 剩余部分（去掉难度名及其方括号，并去除可能多余的空格）
    remaining_after_diff = name_without_ext[:last_left_bracket].rstrip()

    # 提取谱师：位于最后一个 ( ... ) 中
    last_left_paren = remaining_after_diff.rfind('(')
    last_right_paren = remaining_after_diff.rfind(')')
    if last_left_paren == -1 or last_right_paren == -1 or last_left_paren > last_right_paren:
        return None  # 缺少有效的谱师括号
    mapper = remaining_after_diff[last_left_paren + 1:last_right_paren]
    # 剩余部分（去掉谱师及其括号）
    remaining_after_mapper = remaining_after_diff[:last_left_paren].rstrip()

    # 提取曲师和曲名：以 " - " 分隔，只分割一次
    if ' - ' not in remaining_after_mapper:
        return None
    artist, title = remaining_after_mapper.split(' - ', 1)
    artist = artist.strip()
    title = title.strip()
    
    return {
        'Artist': artist,
        'Title': title,
        'Creator': mapper,
        'Version': difficulty
    }
    
def resolve_meta_data(chart_file: Path, file_name: str):
    required_keys = {"Creator", "Artist", "Title", "Version"}

    # 优先从 osu 文件内部元信息读取，失败或字段不完整时回退到文件名解析。
    try:
        osu_obj = osu_file(chart_file)
        osu_obj.process()
        if isinstance(osu_obj.meta_data, dict) and required_keys.issubset(osu_obj.meta_data.keys()):
            return osu_obj.meta_data
    except Exception:
        pass

    return parse_osu_filename(file_name)