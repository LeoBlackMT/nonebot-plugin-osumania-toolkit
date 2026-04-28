# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import List

from .clustering import Cluster


def format_specific_types(specific_types: List[tuple[str, float]]) -> str:
    if not specific_types:
        return ""
    parts = []
    for name, ratio in specific_types:
        parts.append(f"{ratio*100:.0f}% {name}")
    return ", ".join(parts)


def render_output_lines(rate: float, category: str, clusters: List[Cluster], duration_ms: float) -> List[str]:
    lines: List[str] = []
    lines.append(f"Category: {category}")
    lines.append("")

    if not clusters:
        lines.append("No clusters found.")
    else:
        for c in clusters:
            amount_ratio = (c.Amount / duration_ms * 100.0) if duration_ms > 0 else 0.0
            header = f"{c.Format(rate)} | Amount={amount_ratio:.2f}%"
            st = format_specific_types(c.SpecificTypes)
            if st:
                header += f" | {st}"
            lines.append(header)

    return lines


def write_output_txt(path: str, rate: float, category: str, clusters: List[Cluster], duration_ms: float) -> None:
    lines = render_output_lines(rate, category, clusters, duration_ms)

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))