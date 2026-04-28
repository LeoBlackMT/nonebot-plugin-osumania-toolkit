from __future__ import annotations

from pathlib import Path
from typing import Any

from ...parser.osu_file_parser import osu_file


def normalize_cvt_flags(value: Any) -> tuple[bool, bool, str]:
    normalized = str(value or "").strip().upper()
    return ("IN" in normalized, "HO" in normalized, normalized)


def resolve_chart_path(source: Any) -> Path:
    if isinstance(source, Path):
        return source

    if isinstance(source, str):
        return Path(source)

    path_value = getattr(source, "file_path", None)
    if path_value:
        return Path(str(path_value))

    raise TypeError("Unsupported chart source; expected a file path or Path-like object")


def load_osu_chart(source: Any) -> osu_file:
    path = resolve_chart_path(source)
    chart = osu_file(str(path))
    chart.process()
    return chart
