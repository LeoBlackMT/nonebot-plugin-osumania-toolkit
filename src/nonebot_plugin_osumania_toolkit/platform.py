"""跨适配器平台工具：OneBot v11 与 QQ 官方双适配器共存支持。"""
from __future__ import annotations

from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import (
    MessageSegment as _OBMessageSegment,
)

try:
    from nonebot.adapters.qq import Bot as _QQBot
    from nonebot.adapters.qq import (
        MessageSegment as _QQMessageSegment,
    )
except ImportError:
    _QQBot = None
    _QQMessageSegment = None

from .api.download import get_file_url


def is_qq(bot: Bot) -> bool:
    """判断 bot 是否为 QQ 官方适配器。"""
    return isinstance(bot, _QQBot) if _QQBot is not None else False


async def extract_replied_file(
    bot: Bot, event
) -> tuple[str, str] | None:
    """引用消息中的文件 → (文件名, url)。"""
    if is_qq(bot):
        # QQ 官方：直接读 attachments 属性
        candidate = (
            getattr(event, "reply", None) or event
        )
        attachments = getattr(candidate, "attachments", None)
        if attachments:
            for att in attachments:
                url = getattr(att, "url", None)
                if url:
                    name = getattr(att, "filename", None)
                    return (name or "file", url)
        return None
    # OneBot v11
    reply = getattr(event, "reply", None)
    if reply is None:
        return None
    message = getattr(reply, "message", None)
    if message is None:
        return None
    for seg in message:
        if getattr(seg, "type", None) in ("file", "image"):
            result = await get_file_url(bot, seg)
            if result is not None:
                return result
    return None


async def extract_file_from_message(
    bot: Bot, message
) -> tuple[str, str] | None:
    """任意消息中的文件（got 场景 / 用户新消息）。"""
    # duck-typing：有 attachments 属性视为 QQ 附件
    attachments = getattr(message, "attachments", None)
    if attachments is not None:
        for att in attachments:
            url = getattr(att, "url", None)
            if url:
                name = getattr(att, "filename", None)
                return (name or "file", url)
        return None
    # OneBot Message 遍历
    for seg in message:
        if getattr(seg, "type", None) in ("file", "image"):
            result = await get_file_url(bot, seg)
            if result is not None:
                return result
    return None


async def send_image(
    bot: Bot,
    matcher,
    image_bytes: bytes,
    at_sender: bool = False,
) -> None:
    """发送图片：OneBot 用 MessageSegment.image，QQ 用 file_image。"""
    if is_qq(bot):
        await matcher.send(
            _QQMessageSegment.file_image(image_bytes)
        )
    else:
        await matcher.send(
            _OBMessageSegment.image(image_bytes),
            at_sender=at_sender,
        )


async def send_markdown(
    bot: Bot, matcher, text: str
) -> None:
    """发送 Markdown：QQ 优先 markdown 段，降级纯文本；OneBot 纯文本。"""
    if is_qq(bot):
        try:
            await matcher.send(
                _QQMessageSegment.markdown(text)
            )
        except Exception:
            await matcher.send(text)
    else:
        await matcher.send(text)
