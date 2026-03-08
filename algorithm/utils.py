import bisect
from nonebot.log import logger

from ..file.osr_file_parser import osr_file
from ..file.osu_file_parser import osu_file

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
    all_notes = [t for times in note_times_by_col.values() for t in times]
    if not all_notes:
        return [], []
    min_note = min(all_notes)
    max_note = max(all_notes)
    buffer = 5000  # 允许5秒的缓冲

    # 按列整理按下事件，并过滤超出时间范围的事件
    press_events = osr.press_events
    press_by_col = {}
    for col, t in press_events:
        if min_note - buffer <= t <= max_note + buffer:
            press_by_col.setdefault(col, []).append(t)

    for col in press_by_col:
        press_by_col[col].sort()

    delta_list = []
    matched_pairs = []
    max_diff = 188 - 3 * osu.od  # 最大允许偏差

    import bisect

    for col in note_times_by_col:
        notes = note_times_by_col[col]
        presses = press_by_col.get(col, [])
        if not presses:
            continue
        used = [False] * len(presses)
        for note in notes:
            # 二分查找插入点
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
                    break  # 找到第一个可用的即停止，因为更远的距离只会更大
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
                    break  # 同样，找到第一个可用的即停止
                i += 1
            # 如果找到了可用事件
            if best is not None:
                used[best] = True
                delta_list.append((col, presses[best] - note))
                matched_pairs.append((col, note, presses[best]))
    logger.debug(f"匹配到的点数量: {len(delta_list)}")
    logger.debug(f"匹配到的最后物件时间: {max(note for _, note, _ in matched_pairs) if matched_pairs else 0} ms")
    return delta_list, matched_pairs
    # logger.debug(f"匹配到的点数量: {len(delta_list)}")
    # logger.debug(f"匹配到的最后物件时间: {max(note for _, note, _ in matched_pairs) if matched_pairs else 0} ms")

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
                # 尝试直接解析为整数（如果后面没有 + 的情况）
                int(part[1:])
                # 如果成功，说明没有 + 干扰，正常处理
                bid = int(part[1:])
                i += 1
                continue
            except ValueError:
                # 解析失败，说明确实有 "+" 干扰，进行拆分
                plus_index = part.find('+')
                bid_part = part[:plus_index]      # 如 "b123456"
                mod_part = part[plus_index:]      # 如 "+DTHR"

                # 替换当前部分为 bid 部分
                cmd_parts[i] = bid_part
                # 在当前位置后插入 mod 部分
                cmd_parts.insert(i + 1, mod_part)
                # 此时列表长度增加，但我们继续处理当前 i（即 bid 部分）
                # 不增加 i，下一次循环仍然处理这个位置（现在是 bid_part）
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

        # 获取反键参数（可选）
        if part.lower().startswith("gap:"):
            if "HO" in cvt_flag:
                err_msg.append(f"模组冲突: IN/HO; ")
                i += 1
                continue
            if "IN" not in cvt_flag:
                err_msg.append(f"面缝参数仅在反键模组中有效，请在模组参数之后输入; ")
                i += 1
                continue
            try:
                gap_value = int(part[4:])
                if 10 <= gap_value <= 1000:
                    cvt_flag.append(gap_value)
                else:
                    err_msg.append(f"面缝参数必须在10到1000之间: gap:{part[4:]}; ")
            except ValueError:
                err_msg.append(f"无效的面缝参数: {part[4:]}; ")
            i += 1
            continue
        i += 1

    return speed_rate, od_flag, cvt_flag, bid, mod_display, err_msg