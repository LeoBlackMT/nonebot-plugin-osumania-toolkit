from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.exception import FinishedException

from ..algorithm.acc_calculate import get_available_dans

omtk = on_command("omtk")

def format_dan_list(dans: list, items_per_line: int = 5) -> str:
    """
    格式化段位列表，每行显示指定数量的段位
    
    参数:
        dans: 段位名列表
        items_per_line: 每行显示的段位数量
    
    返回:
        格式化后的字符串
    """
    formatted_lines = []
    for i in range(0, len(dans), items_per_line):
        line = dans[i:i + items_per_line]
        formatted_lines.append(", ".join(line))
    return "\n".join(formatted_lines)

# 命令别名映射
command_aliases = {
    "按压": "pressingtime",
    "分析": "analyze",
    "偏差": "delta",
    "血条": "lifebar",
    "频谱": "spectrum",
    "散点": "scatter",
    "单曲": "acc"
}

# help_text 结构: (命令, 命令名称, 页码, 总页码, 帮助文本)
help_text = [("rework", "星数重算", "1", "2",
              "你可以回复包含 .osu/.mc 文件的消息，或回复包含 .osz/.mcz 的消息，或使用 bid 指定谱面。\n命令格式：/rework b<bid> +[mods] x[speed] OD[OD] gap:[gap] \n示例：/rework b4094064 +EZHO x1.25\n/rework b4094064 +IN OD8 gap:50\n警告：图包分析开销较大，请勿滥用。结果将发送大量文字，谨防刷屏。\n注意：1. 如果你回复了一个包含谱面/图包文件的消息，命令将忽略bid。\n2. 部分模组和参数冲突。"),
             
             ("rework", "星数重算", "2", "2",
              "/rework参数说明：\n- bid: 以 b 开头，后跟整数，从官网获取谱面。\n- mods: 以 + 开头，后跟模组名缩写（支持 HR/EZ、DT/HT、IN/HO、DC/NC）。不区分大小写，格式如雨沐。\n- speed: 以 x 或 * 开头，后跟倍速数值（如 x1.5）。倍速必须在 0.25 到 3.0 之间。\n- OD: 以 OD 开头, OD值必须在 -15 到 15 之间。\n- gap: 反键面缝参数，以 gap: 开头，后跟整数，单位ms, 默认150， 仅在 IN 模组启用时有效。"),
             
             ("pressingtime", "按键时间", "1", "1", 
              "你可以使用/pressingtime (/按压) 命令的同时回复一个 .osr/.mr 文件以分析其按压时长分布图。\n注：作弊分析已移动至/analyze命令。"),
             
             ("analyze", "作弊分析", "1", "2", 
              "*警告* 该命令开销较大，请勿滥用。\n-注意- 作弊分析由算法生成，仅供参考，仍处于早期实验阶段，如有问题请反馈。\n这是一个基于回放文件和谱面文件的作弊分析命令。你可以使用/analyze (/分析)回复包含 .osr/.mr 文件的消息来分析回放。如果同时指定bid，将分析delta_t，否则将执行无谱面分析，或发送 .osu/.mc 谱面文件继续分析。\n命令格式：/analyze [b<bid>]\n示例：/analyze b4094064"),
             
            ("analyze", "作弊分析", "2", "2",
              "分析结果图片说明：\n当提供谱面时，将生成四格图：\n1. 按压时长分布图（左上）：显示每个轨道的按压时长分布，横轴为按压时长（ms），纵轴为计数。不同轨道用不同颜色表示。正常玩家各轨道分布相似，作弊可能显示异常高峰或分布差异过大。\n2. 脉冲序列频谱图（右上）：将整个回放的按键事件作为脉冲序列进行傅里叶变换，显示其频谱。横轴为频率（Hz），纵轴为幅度。可用于检测周期性按键模式（如连点器）。\n3. delta_t 直方图（左下）：显示玩家按键时间与谱面物件时间的偏差（delta_t）分布。横轴为delta_t（ms），纵轴为计数。正常分布应接近正态分布，作弊可能显示极窄分布或异常峰值。\n4. delta_t 散点图（右下）：以谱面物件时间为横轴，delta_t为纵轴绘制散点图，可观察偏差随时间的变化。正常应随机分布在0附近，作弊可能显示规律模式或固定偏差。\n\n当不提供谱面时，只生成前两个图表（按压时长分布图和脉冲序列频谱图）。"),
             
             ("delta", "判定偏差", "1", "1", 
              "你可以使用/delta (/偏差)回复包含 .osr/.mr 文件的消息的同时使用 bid 指定谱面，来显示打击的判定偏差分布(按列着色)。\n命令格式：/delta [b<bid>]\n示例：/delta b4094064（同时回复osr）\n"),
             
             ("lifebar", "血条", "1", "1",
              "你可以使用/lifebar (/血条)命令来显示一个回放的血条变化图表。\n用法：回复包含 .osr 文件的消息，然后发送 /lifebar 命令。"),
             
             ("spectrum", "频谱", "1", "1",
              "你可以使用/spectrum (/频谱)命令来显示一个回放的打击频谱图表。\n用法：回复包含 .osr/.mr 文件的消息，然后发送 /spectrum 命令。"),
             
             ("scatter", "散点图", "1", "1",
              "你可以使用/scatter (/散点)回复包含 .osr/.mr 文件的消息的同时使用 bid 指定谱面，来显示打击位置的二维散点图。\n命令格式：/scatter [b<bid>]\n示例：/scatter b4094064（同时回复osr）\n"),
             
             ("acc", "单曲ACC计算", "1", "2",
              "你可以使用/acc (/单曲)命令来计算osu!mania段位的单曲ACC。\n支持两种使用方式：\n1. 直接命令模式: /acc <段位名> <acc变化>\n/acc b<bid> [单曲个数] <acc变化> [sv2标识]\n2. 交互模式: 直接发送 /acc，然后按照提示进行操作。\n本功能可以根据bid或提供文件自动划分单曲且支持自定义物量以及单曲个数。\n\n注意事项:\n1. 使用 ‘-’ 分隔acc变化。如 99.4-99.3-98.8-97.6\n2. 使用 ‘,’ (半角) 分隔自定义物量。如1145,1419,1981(3首歌的段位)\n3. 支持上传 .osu/.mc 谱面文件（.mc 会自动转换后计算）。\n4. 命令中包含 -sv2 （即sv2标识）时启用sv2模组\n\n查看所有内置段位请发送: /omtk acc 2"),
             
             ("acc", "单曲ACC计算", "2", "2",
              "可用段位列表:\n" + format_dan_list(get_available_dans()))
             ]

@omtk.handle()
async def handle_omtk(event: MessageEvent):
    page = 1
    
    try:
        cmd = event.get_plaintext().strip().split()
        match len(cmd):
            case 1:
                await omtk.finish(">osu!mania工具箱<\n发送/omtk显示此信息。发送/omtk <命令名> [页码]获取该命令的详细用法。\n\n可用命令：\n1. /rework - 星数重算\n2. /pressingtime 或 /按压 - 按键时间分析\n3. /analyze 或 /分析 - 作弊分析\n4. /delta 或 /偏差 - 判定偏差分析\n5. /lifebar 或 /血条 - 血条显示\n6. /spectrum 或 /频谱 - 频谱显示\n7. /scatter 或 /散点 - 散点图\n8. /acc 或 /单曲 - 单曲ACC计算\n") # 基础帮助信息
            case 2 | 3:
                if len(cmd) == 2:
                    cmd.append("1")  # 默认页码为1
                
                # 处理别名
                cmd_name = cmd[1].lower()
                if cmd_name in command_aliases:
                    cmd_name = command_aliases[cmd_name]
                
                for type, type_name, page, total_pages, text in help_text:
                    if cmd_name == type and cmd[2] == page:
                        if total_pages == "1":
                            await omtk.finish(type + "(" + type_name + "):\n" + text) # 详细帮助信息
                        await omtk.finish(type + "(" + type_name + "):\n" + text + "\n (第 " + page + " 页，共 " + total_pages + " 页)") # 分页详细帮助信息
                await omtk.finish("无效的命令类型或页码。")
            case _:
                await omtk.finish("请检查命令格式后重试。")
                
    except ValueError:
        await omtk.send("请检查命令格式后重试。")
        return
    except FinishedException:
        pass
    except Exception as e:
        await omtk.send(f"发生错误: {str(e)}")
        return
