from __future__ import annotations

from pathlib import Path
from typing import Any

from ...file.osu_file_parser import osu_file
from .exceptions import NotManiaError, ParseError


def normalize_cvt_flags(cvt_flag: Any) -> tuple[bool, bool, str]:
    if cvt_flag is None:
        return False, False, ""

    if isinstance(cvt_flag, str):
        normalized = cvt_flag.upper()
    else:
        try:
            normalized = " ".join(str(item).upper() for item in cvt_flag if item is not None)
        except TypeError:
            normalized = str(cvt_flag).upper()

    return ("IN" in normalized), ("HO" in normalized), normalized


def resolve_chart_path(source: Any) -> Path:
    if isinstance(source, osu_file):
        path = Path(source.file_path)
    else:
        path = Path(str(source)).expanduser()

    if not path.exists() or not path.is_file():
        raise ParseError("谱面文件不存在")

    return path


def load_osu_chart(source: Any) -> osu_file:
    if isinstance(source, osu_file):
        chart = source
        if chart.status == "init":
            chart.process()
    else:
        chart = osu_file(str(resolve_chart_path(source)))
        chart.process()

    if chart.status == "NotMania":
        raise NotManiaError("Beatmap mode is not mania")
    if chart.status != "OK":
        raise ParseError("Beatmap parse failed")

    return chart
