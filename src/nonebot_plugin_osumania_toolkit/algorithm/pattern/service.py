from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from .osu_parser import parse_osu_mania
from .output_writer import render_output_lines
from .summary import PatternReport, from_chart


class PatternParseError(Exception):
    pass


class PatternNotManiaError(Exception):
    pass


@dataclass
class PatternAnalysisResult:
    keys: int
    report: PatternReport


def _is_mania_osu(file_path: str) -> bool:
    try:
        in_general = False
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                if line.startswith("[") and line.endswith("]"):
                    in_general = (line == "[General]")
                    continue
                if in_general and line.lower().startswith("mode:"):
                    mode_val = line.split(":", 1)[1].strip()
                    return mode_val == "3"
        # 若缺失 Mode 字段，保持兼容旧谱面，按 mania 继续尝试解析。
        return True
    except Exception:
        return True


def _analyze_pattern_file_sync(file_path: str) -> PatternAnalysisResult:
    path = Path(file_path)
    if not path.exists():
        raise PatternParseError(f"文件不存在: {file_path}")

    if path.suffix.lower() != ".osu":
        raise PatternParseError("仅支持 .osu 谱面文件")

    if not _is_mania_osu(file_path):
        raise PatternNotManiaError("该谱面不是 mania 模式")

    try:
        chart = parse_osu_mania(file_path)
        report = from_chart(chart)
        return PatternAnalysisResult(keys=chart.Keys, report=report)
    except PatternNotManiaError:
        raise
    except Exception as exc:
        raise PatternParseError(str(exc)) from exc


async def analyze_pattern_file(file_path: str, rate: float = 1.0) -> PatternAnalysisResult:
    _ = rate
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, _analyze_pattern_file_sync, file_path)
    except Exception as exc:
        # 兼容偶发运行时失败：“Future object is not initialized”。
        if "Future object is not initialized" in str(exc):
            return _analyze_pattern_file_sync(file_path)
        raise


def _format_meta_line(meta_data) -> str:
    if isinstance(meta_data, dict):
        required = {"Creator", "Artist", "Title", "Version"}
        if required.issubset(meta_data.keys()):
            return f"{meta_data['Creator']} // {meta_data['Artist']} - {meta_data['Title']} [{meta_data['Version']}]"
    return "谱面信息解析失败"


def format_pattern_result_text(meta_data, result: PatternAnalysisResult, rate: float = 1.0) -> str:
    lines: list[str] = ["键型分析结果", _format_meta_line(meta_data)]
    lines.extend(
        render_output_lines(
            rate=rate,
            category=result.report.Category,
            clusters=result.report.Clusters,
            duration_ms=result.report.Duration,
        )
    )
    return "\n".join(lines)



