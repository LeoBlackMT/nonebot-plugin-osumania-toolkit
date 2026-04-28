import json
import zipfile
import os
import re
import shutil

from nonebot.log import logger
from pathlib import Path

from ..parser.osu_file_parser import osu_file
from ..parser.ruleset_file_parser import load_ruleset_json, validate_ruleset_data

from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
    PrivateMessageEvent,
)

_OSU_BEATMAPSET_URL_RE = re.compile(
    r"^https?://osu\.ppy\.sh/beatmapsets/\d+#(?P<mode>[A-Za-z0-9_]+)/(?P<bid>\d+)(?:[/?].*)?$",
    re.IGNORECASE,
)


def parse_bid_or_url(part: str) -> tuple[int | None, str | None]:
    """
    summary:
        解析 b<bid> 或 osu 谱面链接中的 bid。
    Args:
        part: 待解析文本。
    Returns:
        (bid, error_message)。若当前文本不适用则返回 (None, None)。
    """
    token = part.strip()

    # 支持 b<bid>
    if token.lower().startswith("b") and len(token) > 1:
        try:
            return int(token[1:]), None
        except ValueError:
            return None, f"无效的谱面ID: {token[1:]}"

    # 支持 https://osu.ppy.sh/beatmapsets/<sid>#mania/<bid>
    m = _OSU_BEATMAPSET_URL_RE.fullmatch(token)
    if m:
        mode = m.group("mode").lower()
        if mode != "mania":
            return None, f"仅支持 mania 谱面链接，当前模式为 {mode}"
        return int(m.group("bid")), None

    # 其他谱面链接视为无效输入，避免静默回退。
    if token.lower().startswith("https://osu.ppy.sh/beatmapsets/") or token.lower().startswith("http://osu.ppy.sh/beatmapsets/"):
        return None, "谱面链接格式无效，请使用 https://osu.ppy.sh/beatmapsets/<sid>#mania/<bid>"

    return None, None

async def send_forward_text_messages(
    bot: Bot,
    event: MessageEvent,
    texts: list[Message | MessageSegment | str],
    nickname: str = "Bot",
):
    """发送合并转发消息，支持纯文本或包含图片的消息节点。"""
    nodes = []
    for item in texts:
        if isinstance(item, Message):
            content = item
        elif isinstance(item, MessageSegment):
            content = Message(item)
        else:
            content = Message(str(item))

        nodes.append(
            MessageSegment.node_custom(
                user_id=int(bot.self_id),
                nickname=nickname,
                content=content,
            )
        )

    if isinstance(event, GroupMessageEvent):
        await bot.call_api("send_group_forward_msg", group_id=event.group_id, messages=nodes)
    elif isinstance(event, PrivateMessageEvent):
        await bot.call_api("send_private_forward_msg", user_id=event.user_id, messages=nodes)
    else:
        for item in texts:
            if isinstance(item, Message):
                await bot.send(item)
            elif isinstance(item, MessageSegment):
                await bot.send(Message(item))
            else:
                await bot.send(str(item))

def extract_zip_file(zip_path: Path, extract_dir: Path) -> list[Path]:
    """解压zip文件并返回所有.osu和.mc文件的路径列表"""
    extracted_files = []
    name_counter: dict[str, int] = {}
    
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        infos = zip_ref.infolist()
        chart_infos = [i for i in infos if i.filename.lower().endswith(('.osu', '.mc'))]
        
        if not chart_infos:
            raise ValueError("压缩包中没有找到.osu或.mc文件")
        
        for info in chart_infos:
            arc_name = info.filename.replace('\\', '/')
            base_name = os.path.basename(arc_name)
            if not base_name:
                continue

            stem, suffix = os.path.splitext(base_name)
            index = name_counter.get(base_name, 0)
            name_counter[base_name] = index + 1
            safe_name = base_name if index == 0 else f"{stem}_{index}{suffix}"
            target_path = extract_dir / safe_name

            with zip_ref.open(info, 'r') as src, open(target_path, 'wb') as dst:
                shutil.copyfileobj(src, dst)
            extracted_files.append(target_path)

    if not extracted_files:
        raise ValueError("压缩包中没有有效的谱面文件")
    
    return extracted_files

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


def is_ruleset_file_valid(ruleset_path: str | Path) -> bool:
    """判断路径是否指向结构有效的 ruleset 文件。"""
    path = Path(ruleset_path)
    if not path.exists() or not path.is_file():
        return False

    if path.suffix.lower() != ".ruleset":
        return False

    try:
        data = load_ruleset_json(path)
        result = validate_ruleset_data(data)
        return result.is_valid
    except Exception:
        return False
    

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