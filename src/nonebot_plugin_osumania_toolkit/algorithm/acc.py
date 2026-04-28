import asyncio

from typing import Tuple, List
from pathlib import Path

from ..parser.osu_file_parser import osu_file
from ..data import dan_data
from .utils import parse_bid_or_url

# ==================== 计算函数 ====================

def calculate_acc(note_counts: List, acc_str: str, sv2_flag: bool = False) -> Tuple:
    """
    使用自定义物量计算单曲ACC
    
    参数:
        note_counts: 物量列表
        acc_str: ACC字符串 (格式: acc1-acc2-acc3-acc4)
        sv2_flag: 兼容参数，物量已在外部按模式准备，此处不参与计算
    
    返回:
        tuple: (单曲ACC列表, 错误信息)
    """
    try:
        # 解析ACC字符串
        acc_parts = acc_str.split('-')
        if len(acc_parts) != len(note_counts):
            return None, f"ACC变化需要{len(note_counts)}个值，但提供了{len(acc_parts)}个"
        
        acc_change = [float(acc) for acc in acc_parts]
        if any(notes <= 0 for notes in note_counts):
            return None, "物量必须为正整数"

        # 使用前缀和
        prefix_notes = [0]
        for notes in note_counts:
            prefix_notes.append(prefix_notes[-1] + notes)
        
        # 计算单曲ACC
        single_accs = []
        for i in range(len(acc_change)):
            if i == 0:
                # 第一首: acc1 = i1
                acc = acc_change[0]
            else:
                total_notes_prev = prefix_notes[i]
                total_notes_curr = prefix_notes[i + 1]
                
                # 计算单曲ACC: acc_i = (i_i * T_i - i_{i-1} * T_{i-1}) / n_i
                prev_product = acc_change[i-1] * total_notes_prev
                curr_product = acc_change[i] * total_notes_curr
                
                acc = (curr_product - prev_product) / note_counts[i]
            
            single_accs.append(round(acc, 2))
        
        return single_accs, None
        
    except ValueError as e:
        return None, f"格式错误: {str(e)}"
    except ZeroDivisionError:
        return None, "物量不能为0"
    except Exception as e:
        return None, f"计算错误: {str(e)}"


def calculate_acc_change(note_counts: List, single_acc_str: str) -> Tuple:
    """
    由单曲ACC推算段位ACC变化。

    参数:
        note_counts: 物量列表
        single_acc_str: 单曲ACC字符串 (格式: acc1-acc2-acc3-acc4)

    返回:
        tuple: (段位ACC变化列表, 错误信息)
    """
    try:
        single_parts = single_acc_str.split('-')
        if len(single_parts) != len(note_counts):
            return None, f"单曲ACC需要{len(note_counts)}个值，但提供了{len(single_parts)}个"

        single_accs = [float(acc) for acc in single_parts]
        if any(notes <= 0 for notes in note_counts):
            return None, "物量必须为正整数"

        prefix_notes = [0]
        for notes in note_counts:
            prefix_notes.append(prefix_notes[-1] + notes)

        cumulative_changes = []
        weighted_sum = 0.0
        for i, single_acc in enumerate(single_accs, start=1):
            weighted_sum += single_acc * note_counts[i - 1]
            cumulative_changes.append(round(weighted_sum / prefix_notes[i], 2))

        return cumulative_changes, None

    except ValueError as e:
        return None, f"格式错误: {str(e)}"
    except ZeroDivisionError:
        return None, "物量不能为0"
    except Exception as e:
        return None, f"计算错误: {str(e)}"
    
def calculate_acc_from_dan(dan_name, acc_str, sv2_flag: bool = False) -> Tuple:
    """
    根据段位名和ACC变化字符串计算单曲ACC
    
    参数:
        dan_name: str, 段位名
        cumulative_acc_str: str, ACC变化字符串，用"-"分隔
    
    返回:
        tuple: (单曲ACC列表, 错误信息)
    """
    data = dan_data.dan_notes
    if dan_name not in data:
        return None, f"段位 '{dan_name}' 不存在。"

    entry = data[dan_name]
    note_counts, data_err = extract_note_counts_from_dan(entry, sv2_flag)
    if data_err:
        return None, data_err

    try:
        single_acc, err_msg = calculate_acc(note_counts, acc_str)
        if err_msg:
            return None, err_msg
        return single_acc, None

    except ValueError as e:
        return None, f"格式错误: {str(e)}"
    except Exception as e:
        return None, f"计算错误: {str(e)}"


def calculate_acc_change_from_dan(dan_name, single_acc_str, sv2_flag: bool = False) -> Tuple:
    """
    根据段位名和单曲ACC字符串推算段位ACC变化。

    参数:
        dan_name: str, 段位名
        single_acc_str: str, 单曲ACC字符串，用"-"分隔

    返回:
        tuple: (段位ACC变化列表, 错误信息)
    """
    data = dan_data.dan_notes
    if dan_name not in data:
        return None, f"段位 '{dan_name}' 不存在。"

    entry = data[dan_name]
    note_counts, data_err = extract_note_counts_from_dan(entry, sv2_flag)
    if data_err:
        return None, data_err

    try:
        dan_acc_changes, err_msg = calculate_acc_change(note_counts, single_acc_str)
        if err_msg:
            return None, err_msg
        return dan_acc_changes, None
    except ValueError as e:
        return None, f"格式错误: {str(e)}"
    except Exception as e:
        return None, f"计算错误: {str(e)}"

# ==================== 辅助函数 ====================

def extract_note_counts_from_dan(entry: List, sv2_flag: bool = False) -> Tuple:
    """
    从段位条目中提取对应模式的物量列表。

    entry 格式:
        [n, note1..noteN] 或 [n, note1..noteN, sv2_note1..sv2_noteN]
    """
    if not isinstance(entry, (list, tuple)) or not entry:
        return None, "段位数据格式错误"

    try:
        num_songs = int(entry[0])
    except (TypeError, ValueError):
        return None, "段位数据格式错误"

    if num_songs <= 0:
        return None, "段位歌曲数量必须大于0"

    if len(entry) < 1 + num_songs:
        return None, "段位物量数据不完整"

    normal_notes = list(entry[1:1 + num_songs])
    if not sv2_flag:
        return normal_notes, None

    if len(entry) >= 1 + 2 * num_songs:
        return list(entry[1 + num_songs:1 + 2 * num_songs]), None

    return None, "该段位不支持 ScoreV2 数据"

def parse_acc_cmd(cmd_text: str) -> Tuple:
    """
    解析acc命令参数
    
    参数:
        cmd_text: str, 命令文本
    
    返回:
        tuple: (段位名, ACC字符串, bid, num_songs, sv2_flag, reverse_flag, 错误信息)
    """
    # 移除命令前缀
    cmd_text = cmd_text.strip()
    prefixes = ["/acc ", "acc ", "/单曲 ", "单曲 "]
    for prefix in prefixes:
        if cmd_text.startswith(prefix):
            cmd_text = cmd_text[len(prefix):].strip()
            break
    
    if not cmd_text:
        return None, None, None, 4, False, False, None  # 进入交互模式 默认4段
    
    cmd_parts = cmd_text.split()
    err_msg = []
    
    bid = None
    num_songs = 4
    acc_str = None
    dan_name = None
    sv2_flag = False
    reverse_flag = False
    
    # 解析命令
    i = 0
    while i < len(cmd_parts):
        part = cmd_parts[i]

        # sv2加权模式
        if part.lower() == "-sv2":
            sv2_flag = True
            i += 1
            continue

        # 反推模式（仅首轮命令支持）
        if part.lower() == "-r":
            reverse_flag = True
            i += 1
            continue
        
        # 获取bid（支持 b<bid> 或 mania 谱面网址）
        parsed_bid, bid_err = parse_bid_or_url(part)
        if bid_err is not None:
            err_msg.append(f"{bid_err}; ")
            i += 1
            continue
        if parsed_bid is not None:
            bid = parsed_bid
            i += 1
            continue
        
        # 获取num_songs
        elif part.isdigit():
            try:
                num_songs = int(part)
                if num_songs <= 0 or num_songs >= 10:
                    err_msg.append("单曲个数必须属于区间(0,10)。")
            except ValueError:
                err_msg.append(f"无效的单曲个数: {part}; ")
            i += 1
            continue
            
        # 获取 acc 变化字符串
        elif '-' in part:
            try:
                acc_str = part
            except ValueError:
                err_msg.append(f"无效的acc变化: {part}; ")
            i += 1
            continue
        
        # 如果都不是上面的情况 则视为段位名
        elif validate_dan_name(part, sv2_flag):
            try:
                dan_name = part
            except ValueError:
                err_msg.append(f"无效的段位名: {part}; ")
            i += 1
            continue
        
        # 未定义的参数
        else:
            i += 1

    return dan_name, acc_str, bid, num_songs, sv2_flag, reverse_flag, err_msg

def validate_dan_name(dan_name: str, sv2_flag: bool = None):
    """
    验证段位名是否有效，并可选择性匹配 sv2_flag

    参数:
        dan_name: str, 段位名
        sv2_flag: bool|None: 如果为 True/False，则校验该模式下是否有可用物量数据；
                             如果为 None，则只检查段位名是否存在。

    返回:
        bool: 是否有效
    """
    data = dan_data.dan_notes
    if dan_name not in data:
        return False

    if sv2_flag is None:
        return True

    entry = data[dan_name]
    _, err_msg = extract_note_counts_from_dan(entry, bool(sv2_flag))
    return err_msg is None

def get_acc_result_text(
    mode: str,
    display_name: str = "",
    note_counts: List = None,
    acc_str: str = "",
    single_accs: List = None,
    sv2_flag: bool = False,
    reverse_flag: bool = False
) -> str:
    """
    构建ACC计算结果消息
    
    参数:
        mode: 模式 "predefined", "bid", "file", "custom"
        display_name: 显示名称
        note_counts: 物量列表
        acc_str: 输入ACC字符串
        single_accs: 计算结果列表
    
    返回:
        格式化结果消息
    """
    result_msg = ""
    
    if mode == "predefined":
        result_msg += f"\n段位: {display_name}\n"
    elif mode in ["bid", "file", "custom"]:
        result_msg += f"\n谱面: {display_name}\n"
        if note_counts:
            result_msg += f"物量分布: {'-'.join(str(n) for n in note_counts)}\n"

    if sv2_flag:
        result_msg += "Mods: ScoreV2\n"
    
    if acc_str:
        input_label = "单曲ACC" if reverse_flag else "ACC变化"
        result_msg += f"{input_label}: {acc_str}\n\n"
    
    if single_accs:
        result_label = "推算段位ACC变化" if reverse_flag else "单曲ACC计算结果"
        result_msg += f"{result_label}:\n"
        i = 1
        for acc_value in single_accs:
            result_msg += f"第{i}首: {acc_value}\n"
            i += 1
    
    return result_msg.strip()

# ==================== 谱面分析函数 ====================

async def calculate_map_notes(file_path: Path, num_songs: int = 4, sv2_flag: bool = False) -> List:
    """
    分析谱面物量分布（异步）
    
    参数:
        file_path: .osu文件路径
        num_songs: 分段数量，默认为4
        
    返回:
        num_songs段物量列表
    """
    parsed = await asyncio.to_thread(parse_osu_file, file_path)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, calculate_note_counts, parsed, num_songs, sv2_flag)

def parse_osu_file(file_path: Path) -> dict:
    """
    解析.osu文件，提取物件、休息段和物件间隔信息
    调用统一的 osu_file 解析器，与项目内其他功能一致
    
    参数:
        file_path: .osu文件路径
        
    返回:
        dict:
            objects: list of (time, type, end_time)
            breaks: list of [break_start, break_end]
            intervals: list of [start_time, interval]，按 interval 降序排序
    """
    osu_obj = osu_file(file_path)
    osu_obj.process()

    if str(osu_obj.GameMode) != '3':
        raise ValueError("该谱面不是 mania 模式")

    objects = []
    for start_time, obj_type, raw_end_time in zip(osu_obj.note_starts, osu_obj.note_types, osu_obj.note_ends):
        start = int(start_time)
        note_type = int(obj_type)

        if note_type & 128:
            end = int(raw_end_time)
            if end < start:
                end = start
        else:
            end = start

        objects.append((start, note_type, end))

    return {
        "objects": objects,
        "breaks": list(osu_obj.breaks),
        "intervals": list(osu_obj.object_intervals),
    }

def _get_note_weight(note_type: int, sv2_flag: bool) -> int:
    """
    计算单个物件权重
    sv2_flag=False: RC/LN均计1
    sv2_flag=True:  RC计1，LN计2
    """
    if sv2_flag and (note_type & 128):
        return 2
    return 1


def select_segment_points(breaks: List, intervals: List, num_songs: int) -> List:
    """
    选择分段点，优先使用休息段，其次使用最长物件间隔。
    """
    if num_songs <= 1:
        return []

    required_points = num_songs - 1
    break_points = []
    if breaks:
        if len(breaks) == required_points:
            break_points = [(break_start + break_end) / 2 for break_start, break_end in breaks]
        elif len(breaks) >= num_songs:
            sorted_breaks = sorted(
                breaks,
                key=lambda item: (item[1] - item[0], item[0]),
                reverse=True,
            )
            selected_breaks = sorted_breaks[:required_points]
            break_points = [(break_start + break_end) / 2 for break_start, break_end in selected_breaks]

    if break_points:
        break_points.sort()
        return break_points

    candidate_intervals = []
    for start_time, interval in intervals:
        if interval > 0:
            candidate_intervals.append((start_time - interval, interval, start_time))

    if not candidate_intervals:
        return []

    candidate_intervals.sort(key=lambda item: (-item[1], item[2]))
    segment_points = [segment_point for segment_point, _, _ in candidate_intervals[:required_points]]
    segment_points.sort()
    return segment_points


def calculate_note_counts(parsed_data, num_songs: int = 4, sv2_flag: bool = False) -> List:
    """
    计算分段物量
    部分内容修改自： https://github.com/uzxn/osu-split/blob/main/osu-split.c
    
    参数:
        parsed_data: 谱面解析结果，包含物件列表、休息段和物件间隔
        num_songs: 分段数量
        sv2_flag: 是否使用sv2加权（LN按2计）
        
    返回:
        各段物量列表
    """
    if isinstance(parsed_data, dict):
        objects = list(parsed_data.get("objects", []))
        breaks = list(parsed_data.get("breaks", []))
        intervals = list(parsed_data.get("intervals", []))
    else:
        objects = list(parsed_data)
        breaks = []
        intervals = []

    if not objects:
        return [0] * num_songs
    
    # 按时间排序
    objects.sort(key=lambda x: x[0])
    
    # 计算总时间范围
    start_time = objects[0][0]
    end_time = max(obj[2] for obj in objects)
    total_duration = end_time - start_time
    
    if total_duration <= 0:
        return [0] * num_songs
    
    # 优先使用休息段中点切分，否则使用最长物件间隔
    segment_points = select_segment_points(breaks, intervals, num_songs)

    if not segment_points:
        segment_duration = total_duration / num_songs
        segment_points = [start_time + i * segment_duration for i in range(1, num_songs)]
    
    # 计算各段物量
    segment_counts = [0] * num_songs
    current_segment = 0
    
    for obj in objects:
        obj_time = obj[0]
        
        # 找到物件所属的段
        while current_segment < len(segment_points) and obj_time > segment_points[current_segment]:
            current_segment += 1
        
        if current_segment < num_songs:
            segment_counts[current_segment] += _get_note_weight(obj[1], sv2_flag)
    
    return segment_counts
