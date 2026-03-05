from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent

omtk = on_command("omtk")

# help_text 结构: (命令, 命令名称, 页码, 总页码, 帮助文本)
help_text = [("rework", "星数重算", "1", "2",
              "你可以回复包含 .osu 文件的消息，或使用 bid 指定谱面。\n命令格式：/rework b<bid> +[mods] x[speed] OD[OD] gap:[gap] \n示例：/rework b4094064 +EZHO x1.25\n/rework b4094064 +IN OD8 gap:50\n注意：如果你回复了一个包含 .osu 文件的消息，你可以不填写bid参数，命令将忽略bid。\n注意部分模组和参数冲突。"),
             ("rework", "星数重算", "2", "2",
              "/rework参数说明：\n- bid: 以 b 开头，后跟整数，从官网获取谱面。\n- mods: 以 + 开头，后跟模组名缩写（支持 HR/EZ、DT/HT、IN/HO、DC/NC）。不区分大小写，格式如雨沐。\n- speed: 以 x 或 * 开头，后跟倍速数值（如 x1.5）。倍速必须在 0.25 到 3.0 之间。\n- OD: 以 OD 开头, OD值必须在 -15 到 15 之间。\n- gap: 反键面缝参数，以 gap: 开头，后跟整数，单位ms, 默认150， 仅在 IN 模组启用时有效。"),
             
             ("pressingtime", "按键时间", "1", "1", "你可以使用/pressingtime命令来分析一个回放的按压时长分布图，并提供轨道相似度与作弊嫌疑作为参考。")]

@omtk.handle()
async def handle_omtk(event: MessageEvent):
    page = 1
    
    try:
        cmd = event.get_plaintext().strip().split()
        match len(cmd):
            case 1:
                omtk.finish(">osu!mania工具箱<\n发送/omtk显示此信息。发送/omtk <命令名>获取该命令的详细用法。\n\n简要介绍：\n 1.对一个osr文件回复并发送/pressingtime以分析按压时长\n 2.使用/rework以重算星数\n") # 基础帮助信息
            case 2 | 3:
                if len(cmd) == 2:
                    cmd[2] = "1" # 默认页码为1
                for type, type_name, page, total_pages, text in help_text:
                    if cmd[1].lower() == type and cmd[2] == page:
                        if total_pages == "1":
                            omtk.finish(type + "(" + type_name + "):\n" + text) # 详细帮助信息
                        omtk.finish(type + "(" + type_name + "):\n" + text + " (第 " + page + " 页，共 " + total_pages + " 页)") # 分页详细帮助信息
                omtk.finish("无效的命令类型或页码。")
            case _:
                omtk.finish("请检查命令格式后重试。")
                
    except ValueError:
        omtk.finish("请检查命令格式后重试。")
    except Exception as e:
        omtk.finish(f"发生错误: {str(e)}")
