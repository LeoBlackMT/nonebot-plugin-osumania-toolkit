import os
import shutil
import time
import asyncio
from pathlib import Path
from typing import Any

from .conversion import convert_mc_to_osu
from .estimator.companella import estimate_companella_result
from .estimator.mixed import apply_companella_to_mixed_result
from .estimator.mixed import estimate_mixed_result
from .estimator.sunny import build_sunny_result
from .pattern import PatternNotManiaError, PatternParseError, analyze_pattern_file
from .estimator.exceptions import ParseError, NotManiaError
from .rework.rework import get_rework_result
from .utils import extract_zip_file, is_mc_file, resolve_meta_data
from ..data import sr_color

color = sr_color()

STAR_BG_STOPS = sr_color.STAR_BG_STOPS
STAR_TEXT_STOPS = sr_color.STAR_TEXT_STOPS

def _specific_types_text(specific_types: list[tuple[str, float]]) -> str:
    if not specific_types:
        return ""
    return ", ".join(f"{name} ({ratio * 100:.1f}%)" for name, ratio in specific_types)

def _merge_duplicate_clusters(clusters: list[Any]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}

    for cluster in clusters:
        key = cluster.Pattern.value
        if key not in merged:
            merged[key] = {
                "label": key,
                "amount": 0.0,
                "specific": {},
            }

        row = merged[key]
        amount = float(cluster.Amount or 0.0)
        row["amount"] += amount

        for name, ratio in list(cluster.SpecificTypes or []):
            weighted = float(ratio or 0.0) * amount
            row["specific"][name] = row["specific"].get(name, 0.0) + weighted

    out: list[dict[str, Any]] = []
    for row in merged.values():
        total = row["amount"] if row["amount"] > 0 else 1.0
        normalized = sorted(
            [(name, weighted / total) for name, weighted in row["specific"].items()],
            key=lambda x: x[1],
            reverse=True,
        )
        out.append(
            {
                "label": row["label"],
                "amount": row["amount"],
                "subtype": _specific_types_text(normalized) or "-",
            }
        )
    return out


def _format_diff_for_display(diff_text: str) -> str:
    return " ".join(str(diff_text).split())


def _split_diff_lines(diff_text: str) -> tuple[str, str | None]:
    clean = _format_diff_for_display(diff_text)
    if "||" not in clean:
        return clean, None

    left, right = clean.split("||", 1)
    top = left.strip()
    bottom = right.strip()
    if top == bottom:
        return top or "-", None
    return (top or "-"), (bottom or "-")


def _render_meta_title(meta_data: Any) -> str:
    if isinstance(meta_data, dict):
        need = {"Creator", "Artist", "Title", "Version"}
        if need.issubset(meta_data.keys()):
            return f"{meta_data['Artist']} - {meta_data['Title']} [{meta_data['Version']}] // {meta_data['Creator']}"
    return "*Failed to parse meta data*"


def _format_parse_error_detail(error: Exception, max_len: int = 240) -> str:
    text = str(error or "").strip().replace("\n", " ")
    if not text:
        return "未知解析错误"
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


async def analyze_mapview_chart(
    chart_file: Path,
    file_name: str,
    speed_rate: float,
    od_flag: str | float | None,
    cvt_flag: list[str],
    mod_display: str,
    cache_dir: Path,
) -> dict[str, Any]:
    target_file = chart_file
    target_name = file_name

    if is_mc_file(str(target_file)):
        try:
            osu_file_path = await asyncio.to_thread(
                convert_mc_to_osu,
                str(target_file),
                str(cache_dir),
            )
            target_file = Path(osu_file_path)
            target_name = os.path.basename(osu_file_path)
        except Exception as e:
            raise ParseError(f".mc 转 .osu 失败: {e}") from e

    try:
        sr, ln_ratio, column_count = await get_rework_result(
            str(target_file), speed_rate, od_flag, cvt_flag
        )
    except ParseError as e:
        detail = _format_parse_error_detail(e)
        raise ParseError(f"Rework 解析阶段失败: {detail}") from e

    sunny_result = build_sunny_result(sr, ln_ratio, column_count)
    mixed_result: dict[str, Any] | None = None

    try:
        mixed_result = await asyncio.to_thread(
            estimate_mixed_result,
            str(target_file),
            speed_rate,
            od_flag,
            cvt_flag,
            sunny_result,
        )
        mixed_diff_text = str(mixed_result.get("estDiff", sunny_result["estDiff"]))
    except Exception:
        mixed_diff_text = sunny_result["estDiff"]

    if isinstance(mixed_result, dict) and mixed_result.get("mixedCompanellaPlan"):
        try:
            companella_result = await asyncio.to_thread(
                estimate_companella_result,
                str(target_file),
                speed_rate,
                cvt_flag,
                sunny_result=sunny_result,
            )
            mixed_result = apply_companella_to_mixed_result(mixed_result, companella_result)
            mixed_diff_text = str(mixed_result.get("estDiff", mixed_diff_text))
        except Exception:
            pass

    try:
        pattern_result = await analyze_pattern_file(str(target_file), rate=speed_rate)
    except PatternParseError as e:
        detail = _format_parse_error_detail(e)
        raise PatternParseError(f"键型解析阶段失败: {detail}") from e

    meta_data = resolve_meta_data(target_file, target_name)

    merged_clusters = _merge_duplicate_clusters(pattern_result.report.Clusters)
    top_five = merged_clusters[:5]
    while len(top_five) < 5:
        top_five.append({"label": "-", "amount": 0.0, "subtype": "-"})

    max_amount = max((row["amount"] for row in top_five), default=1.0)
    cluster_rows: list[dict[str, Any]] = []

    for row in top_five:
        width = 0.0 if max_amount <= 0 else (float(row["amount"]) / max_amount) * 100.0
        cluster_rows.append(
            {
                "label": row["label"],
                "width": f"{width:.2f}%",
                "subtype": row["subtype"],
            }
        )

    extra_parts = []
    if speed_rate != 1.0:
        speed_str = f"{speed_rate:.2f}".rstrip("0").rstrip(".")
        extra_parts.append(f"x{speed_str}")
    if isinstance(od_flag, (int, float)):
        extra_parts.append(f"OD{od_flag}")

    mod_line = mod_display
    if extra_parts:
        mod_line += f" ({', '.join(extra_parts)})"

    diff_top, diff_bottom = _split_diff_lines(mixed_diff_text)
    star_bg = color._color_for(sr, STAR_BG_STOPS, "#6d7894")
    star_text_pref = color._color_for(sr, STAR_TEXT_STOPS, "#f6fbff")
    star_text = color._pick_readable_text_color(sr, star_bg, star_text_pref)

    return {
        "file_name": target_name,
        "template": {
            "status_text": _render_meta_title(meta_data),
            "mode_tag": pattern_result.report.ModeTag,
            "mode_tag_class": color._mode_tag_class(pattern_result.report.ModeTag),
            "rework_star": f"{sr:.2f}",
            "star_bg_color": star_bg,
            "star_text_color": star_text,
            "rework_meta_lines": [
                f"LN%: {ln_ratio:.2%}",
                f"Keys: {column_count}K",
                f"Mods: {mod_line}",
            ],
            "rework_diff_top": diff_top,
            "rework_diff_bottom": diff_bottom,
            "clusters": cluster_rows,
        },
    }


async def analyze_mapview_zip(
    zip_file: Path,
    speed_rate: float,
    od_flag: str | float | None,
    cvt_flag: list[str],
    mod_display: str,
    cache_dir: Path,
) -> tuple[list[dict[str, Any]], list[str]]:
    temp_dir = cache_dir / f"mapview_batch_{int(time.time())}_{os.getpid()}"
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
                row = await analyze_mapview_chart(
                    chart_file,
                    chart_file.name,
                    speed_rate,
                    od_flag,
                    cvt_flag,
                    mod_display,
                    cache_dir,
                )
                results.append(row)
            except (ParseError, PatternParseError) as e:
                detail = _format_parse_error_detail(e)
                errors.append(f"{chart_file.name}: 谱面解析失败 - {detail}")
            except (NotManiaError, PatternNotManiaError):
                errors.append(f"{chart_file.name}: 该谱面不是 mania 模式")
            except Exception as e:
                errors.append(f"{chart_file.name}: 分析失败 - {e}")

        return results, errors
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def format_parse_error_for_user(error: Exception) -> str:
    detail = str(error or "").strip().replace("\n", " ")
    if not detail:
        detail = "未知解析错误"
    if len(detail) > 240:
        detail = detail[:237] + "..."

    return (
        "谱面解析失败，无法完成 /mapview。\n"
        "可能原因：\n"
        "1. .mc 转换后存在冲突音符（如 LN 尾与同列同毫秒按下重叠）\n"
        "2. 文件损坏、字段缺失或格式不兼容\n"
        f"调试信息: {detail}"
    )
