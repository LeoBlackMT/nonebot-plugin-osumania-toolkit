from __future__ import annotations

import json
import asyncio
import hashlib
from typing import Any
from pathlib import Path
from collections import OrderedDict

from nonebot import require

require("nonebot_plugin_htmlkit")
from nonebot_plugin_htmlkit import html_to_pic

from ._template_cache import get_template_env

_FUTURE_NOT_READY_TEXT = "Future object is not initialized"
_LANEACC_RENDER_LOCK = asyncio.Lock()
_IMAGE_CACHE_MAX = 32
_image_cache: OrderedDict[tuple[str, int, str], bytes] = OrderedDict()


def _template_stamp(template_dir: Path) -> int:
    try:
        return (template_dir / "laneacc.html").stat().st_mtime_ns
    except OSError:
        return 0


def _image_cache_key(template_dir: Path, data: dict[str, Any]) -> tuple[str, int, str]:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return (str(template_dir), _template_stamp(template_dir), digest)


def _acc_text(value: Any) -> str:
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "--"


def _counts_text(counts: list[int]) -> str:
    values = [int(value) for value in counts]
    if len(values) == 6:
        values = list(reversed(values))
    return " / ".join(str(value) for value in values)


def build_laneacc_template(
    result: dict[str, Any],
    *,
    display_name: str,
    player: str,
) -> dict[str, Any]:
    lanes = list(result.get("lanes") or [])
    accs = [
        float(lane["acc"])
        for lane in lanes
        if lane.get("acc") is not None and lane["judged"] >= 8
    ]
    if accs:
        bar_min = max(0.0, min(accs) - 1.0)
        bar_max = max(accs)
        if bar_max <= bar_min:
            bar_max = bar_min + 1.0
    else:
        bar_min, bar_max = 0.0, 100.0

    lane_rows: list[dict[str, Any]] = []
    for lane in lanes:
        acc = lane.get("acc")
        width = 0.0
        if acc is not None and lane["judged"] >= 8:
            width = max(
                0.0, min(100.0, (float(acc) - bar_min) / (bar_max - bar_min) * 100.0)
            )
        lane_rows.append(
            {
                "index": int(lane["column"]) + 1,
                "acc": _acc_text(acc),
                "judged": int(lane["judged"]),
                "counts_text": _counts_text(lane.get("counts", [])),
                "bar_width": f"{width:.2f}%",
                "dim": lane["judged"] < 8,
            }
        )

    hands = []
    for key, label in (("left", "L"), ("right", "R")):
        hand = (result.get("hands") or {}).get(key) or {}
        hands.append(
            {
                "label": label,
                "acc": _acc_text(hand.get("acc")),
                "judged": int(hand.get("judged", 0) or 0),
                "miss": int(hand.get("miss", 0) or 0),
            }
        )

    overall = result.get("overall") or {}
    mode_label = str(result.get("mode_label", "-"))
    rate = result.get("rate", 1.0)
    meta_line = (
        f"Player: {player or '-'} · Keys: {result.get('keys', '-')}K · "
        f"Rate: x{float(rate):g} · Weights: {result.get('weights_label', '-')}"
    )
    warnings = "；".join(str(item) for item in (result.get("warnings") or []))
    if result.get("data_source") == "mr":
        footer_note = "Overall 为 .mr 头计数；分轨由动作帧重建。"
    elif result.get("keys", 0) % 2:
        footer_note = "Overall 含隐藏中列；L/R 仅统计左右手。"
    else:
        footer_note = "Overall 与 L/R 均统计全部轨道。"
    data = {
        "display_name": display_name,
        "mode_label": mode_label,
        "meta_line": meta_line,
        "overall_acc": _acc_text(overall.get("acc")),
        "overall_judged": int(overall.get("judged", 0) or 0),
        "overall_miss": int(overall.get("miss", 0) or 0),
        "overall_counts": _counts_text(overall.get("counts", [])),
        "hands": hands,
        "lanes": lane_rows,
        "warning": warnings,
        "footer_note": footer_note,
        "card_height": min(980, 330 + 52 * len(lane_rows)),
    }
    return data


async def _render_once(template_dir: Path, data: dict[str, Any]) -> bytes:
    template = get_template_env(template_dir).get_template("laneacc.html")
    html = await template.render_async(**data)
    return await html_to_pic(
        html=html,
        base_url=f"file://{template_dir.as_posix()}/",
        max_width=475,
        device_height=int(data["card_height"]),
        allow_refit=False,
    )


async def render_laneacc_card(template_dir: Path, data: dict[str, Any]) -> bytes:
    cache_key = _image_cache_key(template_dir, data)
    cached = _image_cache.get(cache_key)
    if cached is not None:
        _image_cache.move_to_end(cache_key)
        return cached

    async with _LANEACC_RENDER_LOCK:
        cached = _image_cache.get(cache_key)
        if cached is not None:
            _image_cache.move_to_end(cache_key)
            return cached
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                image = await _render_once(template_dir, data)
                _image_cache[cache_key] = image
                _image_cache.move_to_end(cache_key)
                while len(_image_cache) > _IMAGE_CACHE_MAX:
                    _image_cache.popitem(last=False)
                return image
            except Exception as exc:
                if _FUTURE_NOT_READY_TEXT not in str(exc):
                    raise
                last_error = exc
                await asyncio.sleep(0.05 * (attempt + 1))
        raise RuntimeError("htmlkit 渲染器尚未完成初始化，请稍后重试。") from last_error
