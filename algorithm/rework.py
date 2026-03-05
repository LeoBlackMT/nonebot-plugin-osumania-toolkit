import os
import asyncio

from .xxy_algorithm import calculate

def get_result(map, mod_display: str, sr: float, speed_rate: float, od_flag, LN_ratio: float, est_diff: str):
    
    result = []
    extra_parts = []
    
    if speed_rate != 1.0:
        # 格式化倍速，去掉末尾多余的0和小数点
        speed_str = f"{speed_rate:.2f}".rstrip('0').rstrip('.')
        extra_parts.append(f"x{speed_str}")
    if isinstance(od_flag, (int, float)):
        extra_parts.append(f"OD{od_flag}")
        
    if isinstance(map, dict):
        result.append(f"{map['mapper']} // {map['artist']} - {map['title']} [{map['difficulty']}]")
    else:
        result.append(f"{map}")
        
    if extra_parts:
        result.append(f"Mods: {mod_display}, " + ", ".join(extra_parts))
    else:
        result.append(f"Mods: {mod_display}")
        
    if LN_ratio:
        result.append(f"LN占比: {LN_ratio:.2%}")
        
    result.append(f"参考难度 (4K):  {est_diff}") 
    result.append(f"Rework结果 => {sr:.2f}")

    return "谱面信息：\n" + "\n".join(result)


def parse_cmd(cmd_text: str):
    # 辅助变量
    cmd_parts = cmd_text.split()
    parsed_mods = []
    err_msg = []
    mod_display = "NM" # 用于显示模组的字符串
    
    # 命令参数
    speed_rate = 1.0
    od_flag = None
    bid = None
    cvt_flag = []
    
    for i in range(len(cmd_parts)):
        '''
        命令处理
        参数列表：
            - 模组：以 "+" 开头，后跟模组名缩写（如 HR、DT、IN 等）。不区分大小写
            - 倍速：以 "x" 或 "*" 开头，后跟倍速数值（如 "x1.5"）。倍速必须在 0.25 到 3.0 之间。
            - OD覆写: 以 "OD" 开头, OD值必须在 -15 到 15 之间。
            - 谱面ID: 以 "b" 开头，后跟整数
            - 面缝参数: 以 "gap:" 开头，后跟整数，单位ms, 仅在 IN 模组启用时有效
        '''
        if cmd_parts[i].startswith("+"):
            # 模组解析
            s = cmd_parts[i][1:].upper().replace('+', '')
            known_mods = ["NC","DT","HT","HR","EZ","DC","IN","HO"]
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
            
        # 倍速处理
        if cmd_parts[i].lower().startswith("x") or cmd_parts[i].startswith("*"):
            try:
                if 0.25 <= round(float(cmd_parts[i][1:]), 3) <= 3.0:
                    speed_rate = round(float(cmd_parts[i][1:]), 3)
                else:
                    err_msg.append(f"倍速必须在0.25到3.0之间: {cmd_parts[i][1:]}x; ")
            except ValueError:
                speed_rate = 1.0
                err_msg.append(f"无效的倍速: {cmd_parts[i][1:]}x; ")
                
        # OD覆写
        if cmd_parts[i].lower().startswith("od"):
            try:
                od_value = float(cmd_parts[i][2:])
                if -15 <= od_value <= 15:
                    od_flag = od_value
                else:
                    err_msg.append(f"OD值必须在-15到15之间: OD{od_value}; ")
            except ValueError:
                err_msg.append(f"无效的OD: {cmd_parts[i][2:]}; ")
                
        # 获取bid
        if cmd_parts[i].lower().startswith("b"):
            try:
                bid = int(cmd_parts[i][1:])
            except ValueError:
                bid = None
                err_msg.append(f"无效的谱面ID: {cmd_parts[i][1:]}; ")
                
        # 获取反键参数（可选）
        if cmd_parts[i].lower().startswith("gap:"):
            if "HO" in cvt_flag:
                err_msg.append(f"模组冲突: IN/HO; ")
                continue            
            if "IN" not in cvt_flag:
                err_msg.append(f"面缝参数仅在反键模组中有效，请在模组参数之后输入; ")
                continue
            try:
                if 10 <= int(cmd_parts[i][4:]) <= 1000:
                    cvt_flag.append(int(cmd_parts[i][4:]))
                else:
                    err_msg.append(f"面缝参数必须在10到1000之间: gap:{cmd_parts[i][4:]}; ")
            except ValueError:
                err_msg.append(f"无效的面缝参数: {cmd_parts[i][4:]}; ")
                
    return speed_rate, od_flag, cvt_flag, bid, mod_display, err_msg


def parse_osu_filename(file_path: str) -> dict | None:
    """
    <artist> - <title> (<mapper>) [<difficulty>].osu
    """
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
        'artist': artist,
        'title': title,
        'mapper': mapper,
        'difficulty': difficulty
    }


async def get_rework_sr(file_path: str, speed_rate: float, od_flag, cvt_flag):
    try:
        loop = asyncio.get_running_loop()
        # 将转换标记传入算法
        result = await loop.run_in_executor(
            None,
            calculate,
            str(file_path),
            speed_rate,
            od_flag,
            cvt_flag
        )
        sr = result[0]
        LN_ratio = result[1]
        if sr == -1:
            raise Exception("ParseError")
        elif sr == -2:
            raise Exception("NotMania")
        return sr, LN_ratio
    except Exception as e:
        raise Exception(f"{e}")
    
    
def est_diff(sr: float, LN_ratio: float) -> str:
    LN_intervals = [
        (4.832, 4.898, "LN 5 mid"),
        (4.898, 4.963, "LN 5 mid/high"),
        (4.963, 5.095, "LN 5 high"),
        (5.095, 5.160, "LN 6 low"),
        (5.160, 5.143, "LN 6 mid/low"),
        (5.143, 5.213, "LN 6 mid"),
        (5.213, 5.264, "LN 6 mid/high"),
        (5.264, 5.314, "LN 6 high"),
        (5.314, 5.446, "LN 7 low"),
        (5.446, 5.521, "LN 7 mid/low"),
        (5.521, 5.577, "LN 7 mid"),
        (5.577, 5.631, "LN 7 mid/high"),
        (5.631, 5.686, "LN 7 high"),
        (5.686, 5.740, "LN 8 low"),
        (5.740, 5.794, "LN 8 mid/low"),
        (5.794, 5.853, "LN 8 mid"),
        (5.853, 5.917, "LN 8 mid/high"),
        (5.917, 5.981, "LN 8 high"),
        (5.981, 6.044, "LN 9 low"),
        (6.044, 6.108, "LN 9 mid/low"),
        (6.108, 6.175, "LN 9 mid"),
        (6.175, 6.246, "LN 9 mid/high"),
        (6.246, 6.318, "LN 9 high"),
        (6.318, 6.389, "LN 10 low"),
        (6.389, 6.461, "LN 10 mid/low"),
        (6.461, 6.534, "LN 10 mid"),
        (6.534, 6.611, "LN 10 mid/high"),
        (6.611, 6.687, "LN 10 high"),
        (6.687, 6.763, "LN 11 low"),
        (6.763, 6.839, "LN 11 mid/low"),
        (6.839, 6.898, "LN 11 mid"),
        (6.898, 6.920, "LN 11 mid/high"),
        (6.920, 6.941, "LN 11 high"),
        (6.941, 7.023, "LN 12 low"),
        (7.023, 7.068, "LN 12 mid/low"),
        (7.068, 7.136, "LN 12 mid"),
        (7.136, 7.225, "LN 12 mid/high"),
        (7.225, 7.313, "LN 12 high"),
        (7.313, 7.401, "LN 13 low"),
        (7.401, 7.490, "LN 13 mid/low"),
        (7.490, 7.578, "LN 13 mid"),
        (7.578, 7.665, "LN 13 mid/high"),
        (7.665, 7.753, "LN 13 high"),
        (7.753, 7.841, "LN 14 low"),
        (7.841, 7.929, "LN 14 mid/low"),
        (7.929, 8.013, "LN 14 mid"),
        (8.013, 8.093, "LN 14 mid/high"),
        (8.093, 8.173, "LN 14 high"),
        (8.173, 8.253, "LN 15 low"),
        (8.253, 8.333, "LN 15 mid/low"),
        (8.333, 8.389, "LN 15 mid"),
        (8.389, 8.428, "LN 15 mid/high"),
        (8.428, 8.470, "LN 15 high"),
        (8.470, 8.509, "hypersovae LN 16 low"),
        (8.509, 8.548, "hypersovae LN 16 mid/low"),
        (8.548, 8.586, "hypersovae LN 16 mid"),
        (8.586, 8.635, "hypersovae LN 16 mid/high"),
        (8.635, 8.908, "hypersovae LN 16 high"),
        (8.908, 9.044, "Lnlism LN 17 low"),
        (9.044, 9.180, "Lnlism LN 17 mid/low"),
        (9.180, 9.316, "Lnlism LN 17 mid"),
        (9.316, 9.452, "Lnlism LN 17 mid/high"),
        (9.452, 9.589, "Lnlism LN 17 high"),
    ]
    RC_intervals = [
        (1.502, 1.631, "intro 1 low"),
        (1.631, 1.760, "intro 1 mid/low"),
        (1.760, 1.890, "intro 1 mid"),
        (1.890, 2.019, "intro 1 mid/high"),
        (2.019, 2.148, "intro 1 high"),
        (2.148, 2.278, "intro 2 low"),
        (2.278, 2.407, "intro 2 mid/low"),
        (2.407, 2.502, "intro 2 mid"),
        (2.502, 2.560, "intro 2 mid/high"),
        (2.560, 2.619, "intro 2 high"),
        (2.619, 2.679, "intro 3 low"),
        (2.679, 2.737, "intro 3 mid/low"),
        (2.737, 2.821, "intro 3 mid"),
        (2.821, 2.929, "intro 3 mid/high"),
        (2.929, 3.037, "intro 3 high"),
        (3.037, 3.145, "reform 1 low"),
        (3.145, 3.253, "reform 1 mid/low"),
        (3.253, 3.346, "reform 1 mid"),
        (3.346, 3.424, "reform 1 mid/high"),
        (3.424, 3.503, "reform 1 high"),
        (3.503, 3.581, "reform 2 low"),
        (3.581, 3.659, "reform 2 mid/low"),
        (3.659, 3.701, "reform 2 mid"),
        (3.701, 3.708, "reform 2 mid/high"),
        (3.708, 3.714, "reform 2 high"),
        (3.714, 3.720, "reform 3 low"),
        (3.720, 3.727, "reform 3 mid/low"),
        (3.727, 3.810, "reform 3 mid"),
        (3.810, 3.970, "reform 3 mid/high"),
        (3.970, 4.130, "reform 3 high"),
        (4.130, 4.290, "reform 4 low"),
        (4.290, 4.450, "reform 4 mid/low"),
        (4.450, 4.569, "reform 4 mid"),
        (4.569, 4.648, "reform 4 mid/high"),
        (4.648, 4.726, "reform 4 high"),
        (4.726, 4.804, "reform 5 low"),
        (4.804, 4.883, "reform 5 mid/low"),
        (4.883, 4.972, "reform 5 mid"),
        (4.972, 5.072, "reform 5 mid/high"),
        (5.072, 5.173, "reform 5 high"),
        (5.173, 5.273, "reform 6 low"),
        (5.273, 5.373, "reform 6 mid/low"),
        (5.373, 5.441, "reform 6 mid"),
        (5.441, 5.476, "reform 6 mid/high"),
        (5.476, 5.511, "reform 6 high"),
        (5.511, 5.547, "reform 7 low"),
        (5.547, 5.582, "reform 7 mid/low"),
        (5.582, 5.646, "reform 7 mid"),
        (5.646, 5.738, "reform 7 mid/high"),
        (5.738, 5.829, "reform 7 high"),
        (5.829, 5.921, "reform 8 low"),
        (5.921, 6.013, "reform 8 mid/low"),
        (6.013, 6.069, "reform 8 mid"),
        (6.069, 6.090, "reform 8 mid/high"),
        (6.090, 6.110, "reform 8 high"),
        (6.110, 6.130, "reform 9 low"),
        (6.130, 6.151, "reform 9 mid/low"),
        (6.151, 6.205, "reform 9 mid"),
        (6.205, 6.294, "reform 9 mid/high"),
        (6.294, 6.382, "reform 9 high"),
        (6.382, 6.471, "reform 10 low"),
        (6.471, 6.560, "reform 10 mid/low"),
        (6.560, 6.616, "reform 10 mid"),
        (6.616, 6.641, "reform 10 mid/high"),
        (6.641, 6.666, "reform 10 high"),
        (6.666, 6.691, "alpha low"),
        (6.691, 6.716, "alpha mid/low"),
        (6.716, 6.773, "alpha mid"),
        (6.773, 6.860, "alpha mid/high"),
        (6.860, 6.947, "alpha high"),
        (6.947, 7.034, "beta low"),
        (7.034, 7.121, "beta mid/low"),
        (7.121, 7.214, "beta mid"),
        (7.214, 7.312, "beta mid/high"),
        (7.312, 7.410, "beta high"),
        (7.410, 7.509, "gamma low"),
        (7.509, 7.607, "gamma mid/low"),
        (7.607, 7.705, "gamma mid"),
        (7.705, 7.803, "gamma mid/high"),
        (7.803, 7.901, "gamma high"),
        (7.901, 8.000, "delta low"),
        (8.000, 8.098, "delta mid/low"),
        (8.098, 8.244, "delta mid"),
        (8.244, 8.438, "delta mid/high"),
        (8.438, 8.631, "delta high"),
        (8.631, 8.825, "epsilon low"),
        (8.825, 9.019, "epsilon mid/low"),
        (9.019, 9.172, "epsilon mid"),
        (9.172, 9.285, "epsilon mid/high"),
        (9.285, 9.398, "epsilon high"),
        (9.398, 9.511, "Emik zeta low"),
        (9.511, 9.624, "Emik zeta mid/low"),
        (9.624, 9.742, "Emik zeta mid"),
        (9.742, 9.867, "Emik zeta mid/high"),
        (9.867, 9.991, "Emik zeta high"),
        (9.991, 10.116, "Thaumiel eta low"),
        (10.116, 10.241, "Thaumiel eta mid/low"),
        (10.241, 10.358, "Thaumiel eta mid"),
        (10.358, 10.468, "Thaumiel eta mid/high"),
        (10.468, 10.578, "Thaumiel eta high"),
        (10.578, 10.689, "CloverWisp theta low"),
        (10.689, 10.799, "CloverWisp theta mid/low"),
        (10.799, 10.909, "CloverWisp theta mid"),
        (10.909, 11.019, "CloverWisp theta mid/high"),
        (11.019, 11.129, "CloverWisp theta high"),
    ]
    # RC难度匹配
    RC_diff = None
    for lower, upper, name in RC_intervals:
        if lower <= sr <= upper:
            RC_diff = name
            break
    if RC_diff is None:
        if sr < 1.502:
            RC_diff = "< intro 1 low"
        elif sr > 11.129:
            RC_diff = "> theta high"
        else:
            RC_diff = "未知RC难度"

    if LN_ratio < 0.1:
        return f"{RC_diff}"
    
    # LN难度匹配
    LN_diff = None
    for lower, upper, name in LN_intervals:
        if lower <= sr <= upper:
            LN_diff = name
            break
    if LN_diff is None:
        if sr < 4.832:
            LN_diff = "< LN 5 mid"
        elif sr > 9.589:
            LN_diff = "> LN 17 high"
        else:
            LN_diff = "未知LN难度"
    return f"{RC_diff} || {LN_diff}"
