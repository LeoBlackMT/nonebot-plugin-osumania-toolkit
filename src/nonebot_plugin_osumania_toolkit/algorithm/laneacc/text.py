from __future__ import annotations

from typing import Any


def _acc(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    return f"{number:.2f}%"


def format_laneacc_text(
    result: dict[str, Any], *, display_name: str = "", player: str = ""
) -> str:
    lines: list[str] = []
    if display_name:
        lines.append(display_name)
    lines.append(
        f"Player: {player or '-'} | Mode: {result.get('mode_label', '-')} | "
        f"Keys: {result.get('keys', '-')}K | Weights: {result.get('weights_label', '-')}"
    )
    overall = result.get("overall", {}) or {}
    lines.append(
        f"Overall: {_acc(overall.get('acc'))} "
        f"(judged {overall.get('judged', 0)}, miss {overall.get('miss', 0)})"
    )
    hands = result.get("hands", {}) or {}
    for key, label in (("left", "L"), ("right", "R")):
        hand = hands.get(key) or {}
        lines.append(
            f"{label}: {_acc(hand.get('acc'))} "
            f"(judged {hand.get('judged', 0)}, miss {hand.get('miss', 0)})"
        )
    lane_parts = [
        f"L{lane['column'] + 1} {_acc(lane.get('acc'))}"
        for lane in result.get("lanes", []) or []
    ]
    if lane_parts:
        lines.append(" / ".join(lane_parts))
    for warning in result.get("warnings", []) or []:
        lines.append(f"注: {warning}")
    if result.get("data_source") == "mr":
        lines.append("注: Overall 为 .mr 头计数；分轨由动作帧重建。")
    return "\n".join(lines)
