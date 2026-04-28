from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent, Bot
from nonebot.exception import FinishedException

from ..data import omtk_help_data
from ..algorithm.utils import send_forward_text_messages

omtk = on_command("omtk")

@omtk.handle()
async def handle_omtk(bot: Bot, event: MessageEvent):
    
    try:
        cmd = event.get_plaintext().strip().split()
        match len(cmd):
            case 1:
                await omtk.finish(omtk_help_data.main_menu_text)
            case 2 | 3:
                # 处理别名
                cmd_name = cmd[1].lower()
                if cmd_name in omtk_help_data.command_aliases:
                    cmd_name = omtk_help_data.command_aliases[cmd_name]

                matched_pages: list[tuple[str, str]] = []
                for cmd_type, type_name, page, total_pages, text in omtk_help_data.help_text:
                    if cmd_name != cmd_type:
                        continue
                    if total_pages == "1":
                        content = cmd_type + "(" + type_name + "):\n" + text
                    else:
                        content = cmd_type + "(" + type_name + "):\n" + text + "\n (第 " + page + " 页，共 " + total_pages + " 页)"
                    matched_pages.append((page, content))

                if not matched_pages:
                    await omtk.finish("无效的命令类型或页码。")

                if len(cmd) == 3:
                    for page, content in matched_pages:
                        if cmd[2] == page:
                            await omtk.finish(content)
                    await omtk.finish("无效的命令类型或页码。")

                matched_pages.sort(key=lambda x: int(x[0]) if x[0].isdigit() else x[0])
                await send_forward_text_messages(bot, event, [content for _, content in matched_pages])
                await omtk.finish()
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
