from __future__ import annotations

import asyncio
import os
import shutil
import time
from pathlib import Path
from typing import Any


from ...parser.osu_file_parser import osu_file
from ..conversion import convert_mc_to_osu
from ..pattern import analyze_pattern_file
from ..utils import extract_zip_file, is_mc_file, resolve_meta_data
from .calc import OfficialRunnerError, compute_difficulties
from ...data import sr_color

color = sr_color()
DEFAULT_SCORE_GOAL = 0.93
MAX_SKILL_VALUE = 41.0
OVERALL_MAX = 41.0
OVERALL_TO_STAR_MAX = 10.0
FULL_SKILLSET_ORDER = [
    "Stream",
    "Jumpstream",
    "Handstream",
    "Stamina",
    "JackSpeed",
    "Chordjack",
    "Technical",
]


class ETTParseError(Exception):
    pass


class ETTNotManiaError(Exception):
    pass


class ETTUnsupportedKeyError(Exception):
    pass


def _render_meta_title(meta_data: Any) -> str:
    if isinstance(meta_data, dict):
        need = {"Creator", "Artist", "Title", "Version"}
        if need.issubset(meta_data.keys()):
            return f"{meta_data['Artist']} - {meta_data['Title']} [{meta_data['Version']}] // {meta_data['Creator']}"
    return "*Failed to parse meta data*"


def _resolve_keycount(parsed_count: int) -> int:
    if parsed_count in (4, 6, 7):
        return parsed_count
    raise ETTUnsupportedKeyError(
        f"该谱面 key 数为 {parsed_count}，ETT 仅支持 4/6/7 键谱面。"
    )


def _format_rate(rate: float) -> str:
    return f"{rate:.2f}".rstrip("0").rstrip(".")


def _skillset_order_for_keycount(keycount: int) -> list[str]:
    if keycount in (6, 7):
        return [s for s in FULL_SKILLSET_ORDER if s != "Technical"]
    return FULL_SKILLSET_ORDER


def _build_skill_rows(values: dict[str, float], keycount: int) -> list[dict[str, str]]:
    skillset_order = _skillset_order_for_keycount(keycount)
    rows: list[dict[str, str]] = []
    for name in skillset_order:
        value = float(values.get(name, 0.0))
        clamped = max(0.0, min(value, MAX_SKILL_VALUE))
        width = (clamped / MAX_SKILL_VALUE) * 100.0
        label_pos = max(14.0, min(width, 98.0))
        rows.append(
            {
                "label": name,
                "value_text": f"{value:.2f}",
                "width": f"{width:.2f}%",
                "label_pos": f"{label_pos:.2f}%",
            }
        )
    return rows


def _overall_to_star_value(overall: float) -> float:
    normalized = max(0.0, min(overall, OVERALL_MAX)) / OVERALL_MAX
    return normalized * OVERALL_TO_STAR_MAX


def _compute_values(
    chart: osu_file,
    speed_rate: float,
    keycount: int,
    score_goal: float,
) -> dict[str, float]:
    values = compute_difficulties(
        chart,
        music_rate=speed_rate,
        keycount=keycount,
        score_goal=score_goal,
    )
    return {k: float(v) for k, v in values.items()}


async def analyze_ett_chart(
    chart_file: Path,
    file_name: str,
    speed_rate: float,
    cvt_flag: list[str],
    mod_display: str,
    cache_dir: Path,
    score_goal: float = DEFAULT_SCORE_GOAL,
) -> dict[str, Any]:
    target_file = chart_file
    target_name = file_name

    if is_mc_file(str(target_file)):
        osu_file_path = await asyncio.to_thread(
            convert_mc_to_osu,
            str(target_file),
            str(cache_dir),
        )
        target_file = Path(osu_file_path)
        target_name = os.path.basename(osu_file_path)

    chart = osu_file(str(target_file))
    await asyncio.to_thread(chart.process)

    if chart.status == "NotMania":
        raise ETTNotManiaError()
    if chart.status != "OK":
        raise ETTParseError()

    _ = cvt_flag
    _ = mod_display
    ln_ratio = chart.LN_ratio
    keycount = _resolve_keycount(chart.column_count)

    loop = asyncio.get_running_loop()
    try:
        values = await loop.run_in_executor(
            None,
            _compute_values,
            chart,
            speed_rate,
            keycount,
            score_goal,
        )
    except Exception as exc:
        # 兼容偶发运行时失败：“Future object is not initialized”。
        if "Future object is not initialized" in str(exc):
            values = _compute_values(chart, speed_rate, keycount, score_goal)
        else:
            raise
    pattern_result = await analyze_pattern_file(str(target_file), rate=speed_rate)

    meta_data = resolve_meta_data(target_file, target_name)

    meta_lines = [
        f"LN%: {ln_ratio:.2%}",
        f"Rate: x{_format_rate(speed_rate)}",
        f"Keys: {keycount}K",
    ]

    overall = float(values.get("Overall", 0.0))
    star_value = _overall_to_star_value(overall)
    overall_bg = color._color_for(star_value, color.STAR_BG_STOPS, "#6d7894")
    overall_text_pref = color._color_for(star_value, color.STAR_TEXT_STOPS, "#f6fbff")
    overall_text = color._pick_readable_text_color(star_value, overall_bg, overall_text_pref)

    card_height = 500 if keycount in (6, 7) else 520

    return {
        "file_name": target_name,
        "template": {
            "status_text": _render_meta_title(meta_data),
            "mode_tag": pattern_result.report.ModeTag,
            "mode_tag_class": color._mode_tag_class(pattern_result.report.ModeTag),
            "overall_value": f"{overall:.2f}",
            "overall_bg_color": overall_bg,
            "overall_text_color": overall_text,
            "ett_meta_lines": meta_lines,
            "skillsets": _build_skill_rows(values, keycount),
            "card_height": card_height,
        },
    }


async def analyze_ett_zip(
    zip_file: Path,
    speed_rate: float,
    cvt_flag: list[str],
    mod_display: str,
    cache_dir: Path,
    score_goal: float = DEFAULT_SCORE_GOAL,
) -> tuple[list[dict[str, Any]], list[str]]:
    temp_dir = cache_dir / f"ett_batch_{int(time.time())}_{os.getpid()}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    errors: list[str] = []

    try:
        try:
            chart_files = await asyncio.to_thread(extract_zip_file, zip_file, temp_dir)
        except Exception as e:
            errors.append(f"图包分析失败 - {e}")
            return results, errors

        if not chart_files:
            errors.append("图包中没有可分析的谱面文件。")
            return results, errors

        for chart_file in chart_files:
            try:
                row = await analyze_ett_chart(
                    chart_file,
                    chart_file.name,
                    speed_rate,
                    cvt_flag,
                    mod_display,
                    temp_dir,
                    score_goal,
                )
                results.append(row)
            except ETTParseError:
                errors.append(f"{chart_file.name}: 谱面解析失败")
            except ETTNotManiaError:
                errors.append(f"{chart_file.name}: 该谱面不是 mania 模式")
            except ETTUnsupportedKeyError as e:
                errors.append(f"{chart_file.name}: {e}")
            except OfficialRunnerError as e:
                errors.append(f"{chart_file.name}: ETT 计算失败 - {e}")
            except Exception as e:
                errors.append(f"{chart_file.name}: 分析失败 - {e}")

        return results, errors
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
