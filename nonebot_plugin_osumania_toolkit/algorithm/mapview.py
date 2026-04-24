import os
import shutil
import time
import asyncio
from pathlib import Path
from typing import Any
from nonebot import require

require("nonebot_plugin_htmlkit")
from nonebot_plugin_htmlkit import template_to_pic  # type: ignore[import-not-found]

from .convert import convert_mc_to_osu
from .estimator.mixed import estimate_mixed_result
from .estimator.sunny import build_sunny_result
from .patterns import PatternNotManiaError, PatternParseError, analyze_pattern_file
from .rework import ParseError, NotManiaError, get_rework_result
from .utils import extract_zip_file, is_mc_file, resolve_meta_data


STAR_BG_STOPS = [
    (0.0, "#aaaaaa"),
    (0.9, "#4bb3fd"),
    (2.0, "#4fffd5"),
    (3.0, "#d3f557"),
    (4.0, "#fda265"),
    (5.0, "#f94d79"),
    (6.0, "#b64cc1"),
    (7.0, "#5654ca"),
    (8.0, "#14117d"),
    (9.0, "#000000"),
    (9999.9, "#000000"),
]

STAR_TEXT_STOPS = [
    (0.0, "#000000"),
    (6.49, "#000000"),
    (6.5, "#ffd966"),
    (8.9, "#ffd966"),
    (9.0, "#f6f05c"),
    (10.0, "#ff7a69"),
    (11.0, "#e74a95"),
    (12.0, "#9a57ce"),
    (12.39, "#6563de"),
    (9999.9, "#6563de"),
]

_FUTURE_NOT_READY_TEXT = "Future object is not initialized"
_MAPVIEW_RENDER_LOCK = asyncio.Lock()


async def _render_mapview_card_once(template_dir: Path, data: dict) -> bytes:
    return await template_to_pic(
        template_path=template_dir,
        template_name="mapview.html",
        templates=data,
        max_width=475,
        device_height=490,
        allow_refit=False,
    )

async def render_analysis_card(TEMPLATE_DIR: Path, data: dict) -> bytes:
    # 使用串行渲染避免并发竞争触发 htmlkit future 初始化竞态。
    async with _MAPVIEW_RENDER_LOCK:
        last_future_error: Exception | None = None

        for attempt in range(3):
            try:
                return await _render_mapview_card_once(TEMPLATE_DIR, data)
            except Exception as exc:
                if _FUTURE_NOT_READY_TEXT not in str(exc):
                    raise
                last_future_error = exc
                await asyncio.sleep(0.05 * (attempt + 1))

        # 保留一次最终重试，兼容极端延迟初始化场景。
        try:
            return await _render_mapview_card_once(TEMPLATE_DIR, data)
        except Exception as exc:
            if _FUTURE_NOT_READY_TEXT in str(exc) and last_future_error is not None:
                raise RuntimeError("htmlkit 渲染器尚未完成初始化，请稍后重试。") from last_future_error
            raise

def _specific_types_text(specific_types: list[tuple[str, float]]) -> str:
    if not specific_types:
        return ""
    return ", ".join(f"{name} ({ratio * 100:.1f}%)" for name, ratio in specific_types)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    color = hex_color.lstrip("#")
    if len(color) == 3:
        color = "".join(ch + ch for ch in color)
    value = int(color, 16)
    return ((value >> 16) & 255, (value >> 8) & 255, value & 255)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def _interpolate_color(hex_a: str, hex_b: str, t: float) -> str:
    ar, ag, ab = _hex_to_rgb(hex_a)
    br, bg, bb = _hex_to_rgb(hex_b)
    r = round(ar + (br - ar) * t)
    g = round(ag + (bg - ag) * t)
    b = round(ab + (bb - ab) * t)
    return _rgb_to_hex(r, g, b)


def _color_for(value: float, stops: list[tuple[float, str]], fallback: str) -> str:
    if not isinstance(value, (int, float)):
        return fallback
    if value <= stops[0][0]:
        return stops[0][1]
    for i in range(len(stops) - 1):
        lv, lc = stops[i]
        rv, rc = stops[i + 1]
        if lv <= value <= rv:
            t = (value - lv) / (rv - lv or 1.0)
            return _interpolate_color(lc, rc, t)
    return stops[-1][1]


def _relative_luminance(hex_color: str) -> float:
    r, g, b = _hex_to_rgb(hex_color)

    def convert(v: int) -> float:
        c = v / 255.0
        if c <= 0.03928:
            return c / 12.92
        return ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * convert(r) + 0.7152 * convert(g) + 0.0722 * convert(b)


def _contrast_ratio(hex_a: str, hex_b: str) -> float:
    l1 = _relative_luminance(hex_a)
    l2 = _relative_luminance(hex_b)
    bright = max(l1, l2)
    dark = min(l1, l2)
    return (bright + 0.05) / (dark + 0.05)


def _pick_readable_text_color(star_value: float, bg_color: str, preferred_color: str) -> str:
    if isinstance(star_value, (int, float)) and star_value > 12:
        return "#6563de"

    if isinstance(star_value, (int, float)) and 6.0 <= star_value <= 6.49:
        return "#000000"

    if isinstance(star_value, (int, float)) and 6.5 <= star_value <= 8.9:
        return "#ffd966"

    preferred = preferred_color or "#f6fbff"
    if _contrast_ratio(bg_color, preferred) >= 4.5:
        return preferred

    candidate_dark = "#111111"
    candidate_light = "#f6fbff"
    candidate_gold = "#FFD966"

    dark_ratio = _contrast_ratio(bg_color, candidate_dark)
    light_ratio = _contrast_ratio(bg_color, candidate_light)
    gold_ratio = _contrast_ratio(bg_color, candidate_gold)

    if 7.0 <= star_value <= 10.0:
        if gold_ratio >= 4.5:
            return candidate_gold
        return candidate_light if light_ratio >= dark_ratio else candidate_dark

    if dark_ratio >= 4.5 or dark_ratio > light_ratio:
        return candidate_dark
    return candidate_light


def _mode_tag_class(tag: str) -> str:
    normalized = tag if tag in {"RC", "LN", "HB", "Mix"} else "Mix"
    return f"mode-{normalized.lower()}"


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
            osu_file_path = convert_mc_to_osu(str(target_file), str(cache_dir))
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
    star_bg = _color_for(sr, STAR_BG_STOPS, "#6d7894")
    star_text_pref = _color_for(sr, STAR_TEXT_STOPS, "#f6fbff")
    star_text = _pick_readable_text_color(sr, star_bg, star_text_pref)

    return {
        "file_name": target_name,
        "template": {
            "status_text": _render_meta_title(meta_data),
            "mode_tag": pattern_result.report.ModeTag,
            "mode_tag_class": _mode_tag_class(pattern_result.report.ModeTag),
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
            chart_files = extract_zip_file(zip_file, temp_dir)
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
