import asyncio

from typing import Tuple, List
from pathlib import Path

from ..file.osu_file_parser import osu_file

# ==================== 内置单曲数据 ====================

def acc_data():
    """
    段位物量数据
    数据来源：https://github.com/Ohdmire/nonebot-plugin-acc-calculate/blob/main/nonebot_plugin_acc_calculate/database.py
    返回: dict, 键为段位名，值为[sv2_flag, note1, note2, ...]
    """
    return {
        "regular0": [False, 492, 529, 595, 681],
        "regular1": [False, 695, 621, 718, 1279],
        "regular2": [False, 1397, 1090, 805, 1212],
        "regular3": [False, 1055, 1489, 1288, 1788],
        "regular4": [False, 1865, 1434, 1284, 1839],
        "regular5": [False, 1282, 1706, 1473, 1939],
        "regular6": [False, 1694, 1636, 1803, 2115],
        "regular7": [False, 1701, 1799, 2132, 1899],
        "regular8": [False, 2237, 2081, 2280, 2000],
        "regular9": [False, 2374, 1889, 2142, 1814],
        "regular10": [False, 2034, 1740, 2270, 2166],
        "ex1": [False, 1952, 2013, 1953, 2111],
        "ex2": [False, 2107, 1953, 2386, 2674],
        "ex3": [False, 2518, 2636, 2326, 2511],
        "ex4": [False, 2634, 2212, 2336, 2602],
        "ex5": [False, 2734, 2417, 3089, 2974],
        "ex6": [False, 2483, 2276, 2921, 3194],
        "ex7": [False, 2846, 2260, 2333, 3347],
        "ex8": [False, 3789, 3663, 2424, 3255],
        "ex9": [False, 3888, 3030, 3581, 3700],
        "exfinal": [False, 2828, 3362, 3393, 5100],
        "regular1v2": [False, 813, 955, 907, 654],
        "regular2v2": [False, 1152, 850, 950, 969],
        "regular3v2": [False, 1169, 1143, 974, 1347],
        "regular4v2": [False, 1400, 1402, 1685, 1599],
        "regular5v2": [False, 1953, 2250, 2166, 1667],
        "regular6v2": [False, 1487, 1424, 1381, 1587],
        "regular7v2": [False, 1909, 1814, 1777, 2681],
        "regular8v2": [False, 1962, 1067, 2388, 1772],
        "regular9v2": [False, 1799, 2023, 2283, 1787],
        "regular10v2": [False, 2606, 2188, 2194, 2187],
        "ex1v2": [False, 2160, 1952, 1821, 3249],
        "ex2v2": [False, 2871, 2024, 1871, 2452],
        "ex3v2": [False, 2327, 1593, 2166, 2200],
        "ex4v2": [False, 2731, 2653, 2033, 2761],
        "ex5v2": [False, 3229, 2731, 2561, 2109],
        "ex6v2": [False, 1766, 1861, 3171, 1680],
        "ex7v2": [False, 2339, 2461, 2511, 2177],
        "ex8v2": [False, 1929, 2380, 2710, 4675],
        "exfinalv2": [False, 3468, 3335, 3698, 5061],
        "reform1": [False, 878, 696, 954, 1167],
        "reform2": [False, 1107, 905, 955, 1487],
        "reform3": [False, 905, 797, 1047, 1560],
        "reform4": [False, 980, 1499, 1283, 2071],
        "reform5": [False, 1293, 1494, 1126, 1903],
        "reform6": [False, 1487, 1266, 1749, 2186],
        "reform7": [False, 2114, 1777, 1081, 2734],
        "reform8": [False, 2177, 1309, 1608, 1589],
        "reform9": [False, 2144, 2070, 1674, 2272],
        "reform10": [False, 1906, 1460, 1723, 2392],
        "reforma": [False, 2265, 1528, 2300, 3334],
        "reformb": [False, 2274, 2308, 1740, 2301],
        "reformg": [False, 1973, 1980, 1429, 3976],
        "reformd": [False, 2018, 2711, 3140, 2629],
        "reforme": [False, 2128, 2552, 2194, 2829]
    }

# ==================== 计算函数 ====================

def calculate_acc(note_counts: List, acc_str: str) -> Tuple:
    """
    使用自定义物量计算单曲ACC
    
    参数:
        note_counts: 物量列表
        acc_str: ACC字符串 (格式: acc1-acc2-acc3-acc4)
    
    返回:
        tuple: (单曲ACC列表, 错误信息)
    """
    try:
        # 解析ACC字符串
        acc_parts = acc_str.split('-')
        if len(acc_parts) != len(note_counts):
            return None, f"ACC变化需要{len(note_counts)}个值，但提供了{len(acc_parts)}个"
        
        acc_change = [float(acc) for acc in acc_parts]
        
        # 计算单曲ACC
        single_accs = []
        for i in range(len(acc_change)):
            if i == 0:
                # 第一首: acc1 = i1
                acc = acc_change[0]
            else:
                total_notes_prev = sum(note_counts[:i])
                total_notes_curr = sum(note_counts[:i+1])
                
                # 计算单曲ACC: acc_i = (i_i * T_i - i_{i-1} * T_{i-1}) / n_i
                prev_product = acc_change[i-1] * total_notes_prev
                curr_product = acc_change[i] * total_notes_curr
                
                if note_counts[i] == 0:
                    acc = 0.0
                else:
                    acc = (curr_product - prev_product) / note_counts[i]
            
            single_accs.append(round(acc, 2))
        
        return single_accs, None
        
    except ValueError as e:
        return None, f"格式错误: {str(e)}"
    except ZeroDivisionError:
        return None, "物量不能为0"
    except Exception as e:
        return None, f"计算错误: {str(e)}"
    
def calculate_acc_from_dan(dan_name, acc_str) -> Tuple:
    """
    根据段位名和ACC变化字符串计算单曲ACC
    
    参数:
        dan_name: str, 段位名
        cumulative_acc_str: str, ACC变化字符串，用"-"分隔
    
    返回:
        tuple: (单曲ACC列表, 错误信息)
    """
    data = acc_data()
    if dan_name not in data:
        return None, f"段位 '{dan_name}' 不存在。"

    entry = data[dan_name]
    # en结构: [sv2_flag, note1, note2, ...]
    if isinstance(entry, (list, tuple)) and len(entry) >= 1:
        note_counts = list(entry[1:])
    else:
        note_counts = list(entry)

    try:
        single_acc, err_msg = calculate_acc(note_counts, acc_str)
        if err_msg:
            return None, err_msg
        return single_acc, None

    except ValueError as e:
        return None, f"格式错误: {str(e)}"
    except Exception as e:
        return None, f"计算错误: {str(e)}"

# ==================== 辅助函数 ====================

def parse_acc_cmd(cmd_text: str) -> Tuple:
    """
    解析acc命令参数
    
    参数:
        cmd_text: str, 命令文本
    
    返回:
        tuple: (段位名, ACC字符串, bid, num_songs, sv2_flag, 错误信息)
    """
    # 移除命令前缀
    cmd_text = cmd_text.strip()
    prefixes = ["/acc ", "acc ", "/单曲 ", "单曲 "]
    for prefix in prefixes:
        if cmd_text.startswith(prefix):
            cmd_text = cmd_text[len(prefix):].strip()
            break
    
    if not cmd_text:
        return None, None, None, 4, False, None  # 进入交互模式 默认4段
    
    cmd_parts = cmd_text.split()
    err_msg = []
    
    bid = None
    num_songs = 4
    acc_str = None
    dan_name = None
    sv2_flag = False
    
    # 解析命令
    i = 0
    while i < len(cmd_parts):
        part = cmd_parts[i]

        # sv2加权模式
        if part.lower() == "-sv2":
            sv2_flag = True
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

    return dan_name, acc_str, bid, num_songs, sv2_flag, err_msg

def get_available_dans():
    """
    获取所有可用的段位名
    
    返回:
        list, 按字典序升序排列的段位名列表
    """
    data = list(acc_data().keys())
    data.sort()
    return data

def validate_dan_name(dan_name: str, sv2_flag: bool = None):
    """
    验证段位名是否有效，并可选择性匹配 sv2_flag

    参数:
        dan_name: str, 段位名
        sv2_flag: bool|None: 如果为 True/False，则要求段位数据的首位 sv2_flag 与之匹配；
                             如果为 None，则只检查段位名是否存在。

    返回:
        bool: 是否有效
    """
    data = acc_data()
    if dan_name not in data:
        return False

    if sv2_flag is None:
        return True

    entry = data[dan_name]
    if isinstance(entry, (list, tuple)) and len(entry) >= 1:
        return bool(entry[0]) == bool(sv2_flag)

    return False

def get_acc_result_text(
    mode: str,
    display_name: str = "",
    note_counts: List = None,
    acc_str: str = "",
    single_accs: List = None,
    sv2_flag: bool = False
) -> str:
    """
    构建ACC计算结果消息
    
    参数:
        mode: 模式 "predefined", "bid", "file", "custom"
        display_name: 显示名称
        note_counts: 物量列表
        acc_str: ACC字符串
        single_accs: 单曲ACC列表
    
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
        result_msg += f"ACC变化: {acc_str}\n\n"
    
    if single_accs:
        result_msg += "单曲ACC计算结果:\n"
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
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, calculate_note_counts, parse_osu_file(file_path), num_songs, sv2_flag)

def parse_osu_file(file_path: Path) -> List:
    """
    解析.osu文件，提取物件信息
    调用统一的 osu_file 解析器，与项目内其他功能一致
    
    参数:
        file_path: .osu文件路径
        
    返回:
        list of (time, type, end_time)
        type: 1=RC, 128=LN
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

    return objects

def _get_note_weight(note_type: int, sv2_flag: bool) -> int:
    """
    计算单个物件权重
    sv2_flag=False: RC/LN均计1
    sv2_flag=True:  RC计1，LN计2
    """
    if sv2_flag and (note_type & 128):
        return 2
    return 1


def calculate_note_counts(objects: List, num_songs: int = 4, sv2_flag: bool = False) -> List:
    """
    计算分段物量
    修改自： https://github.com/uzxn/osu-split/blob/main/osu-split.c
    
    参数:
        objects: 物件列表
        num_songs: 分段数量
        sv2_flag: 是否使用sv2加权（LN按2计）
        
    返回:
        各段物量列表
    """
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
    
    # 计算分段点（按时间均匀分段）
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
