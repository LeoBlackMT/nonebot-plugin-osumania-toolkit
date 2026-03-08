from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.exception import FinishedException

omtk = on_command("omtk")

# 命令别名映射
command_aliases = {
    "按压": "pressingtime",
    "分析": "analyze",
    "偏差": "delta",
    "血条": "lifebar",
    "频谱": "spectrum",
    "散点": "scatter"
}

# help_text 结构: (命令, 命令名称, 页码, 总页码, 帮助文本)
help_text = [("rework", "星数重算", "1", "2",
              "你可以回复包含 .osu 文件的消息，或使用 bid 指定谱面。\n命令格式：/rework b<bid> +[mods] x[speed] OD[OD] gap:[gap] \n示例：/rework b4094064 +EZHO x1.25\n/rework b4094064 +IN OD8 gap:50\n注意：如果你回复了一个包含 .osu 文件的消息，你可以不填写bid参数，命令将忽略bid。\n注意部分模组和参数冲突。"),
             
             ("rework", "星数重算", "2", "2",
              "/rework参数说明：\n- bid: 以 b 开头，后跟整数，从官网获取谱面。\n- mods: 以 + 开头，后跟模组名缩写（支持 HR/EZ、DT/HT、IN/HO、DC/NC）。不区分大小写，格式如雨沐。\n- speed: 以 x 或 * 开头，后跟倍速数值（如 x1.5）。倍速必须在 0.25 到 3.0 之间。\n- OD: 以 OD 开头, OD值必须在 -15 到 15 之间。\n- gap: 反键面缝参数，以 gap: 开头，后跟整数，单位ms, 默认150， 仅在 IN 模组启用时有效。"),
             
             ("pressingtime", "按键时间", "1", "1", 
              "你可以使用/pressingtime (/按压) 命令的同时回复一个osr文件以分析其按压时长分布图。\n注：作弊分析已移动至/analyze命令。"),
             
             ("analyze", "作弊分析", "1", "1", 
              "*警告* 该命令开销较大，请勿滥用。\n -注意- 作弊分析由算法生成，仅供参考，仍处于早期实验阶段，如有问题请反馈。\n这是一个基于回放文件和谱面文件的作弊分析命令。你可以使用/analyze (/分析)回复包含 .osr 文件的消息，或使用 bid 指定谱面。\n命令格式：/analyze [b<bid>]\n示例：/analyze b4094064\n如果你没有提供bid参数，那么将不分析偏移。"),
             
             ("delta", "判定偏差", "1", "1", 
              "你可以使用/delta (/偏差)回复包含 .osr 文件的消息的同时使用 bid 指定谱面，来显示打击的判定偏差分布(按列着色)。\n命令格式：/delta [b<bid>]\n示例：/delta b4094064（同时回复osr）\n"),
             
             ("lifebar", "血条", "1", "1",
              "你可以使用/lifebar (/血条)命令来显示一个回放的血条变化图表。\n用法：回复包含 .osr 文件的消息，然后发送 /lifebar 命令。"),
             
             ("spectrum", "频谱", "1", "1",
              "你可以使用/spectrum (/频谱)命令来显示一个回放的打击频谱图表。\n用法：回复包含 .osr 文件的消息，然后发送 /spectrum 命令。"),
             
             ("scatter", "散点图", "1", "1",
              "你可以使用/scatter (/散点)回复包含 .osr 文件的消息的同时使用 bid 指定谱面，来显示打击位置的二维散点图。\n命令格式：/scatter [b<bid>]\n示例：/scatter b4094064（同时回复osr）\n")]

@omtk.handle()
async def handle_omtk(event: MessageEvent):
    page = 1
    
    try:
        cmd = event.get_plaintext().strip().split()
        match len(cmd):
            case 1:
                await omtk.finish(">osu!mania工具箱<\n发送/omtk显示此信息。发送/omtk <命令名> [页码]获取该命令的详细用法。\n\n可用命令：\n1. /rework - 星数重算\n2. /pressingtime 或 /按压 - 按键时间分析\n3. /analyze 或 /分析 - 作弊分析\n4. /delta 或 /偏差 - 判定偏差分析\n5. /lifebar 或 /血条 - 血条显示\n6. /spectrum 或 /频谱 - 频谱显示\n7. /scatter 或 /散点 - 散点图\n") # 基础帮助信息
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
        await omtk.finish("请检查命令格式后重试。")
    except FinishedException:
        pass
    except Exception as e:
        await omtk.finish(f"发生错误: {str(e)}")
