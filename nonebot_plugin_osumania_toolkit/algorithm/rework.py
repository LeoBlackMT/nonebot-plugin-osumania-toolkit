from __future__ import annotations

import asyncio
import os
import shutil
import time
from pathlib import Path

from ..file.osu_file_parser import osu_file

from .convert import convert_mc_to_osu
from .estimator.exceptions import NotManiaError, ParseError
from .estimator.sunny import est_diff, estimate_sunny_result
from .utils import extract_zip_file, is_mc_file, parse_osu_filename


async def get_rework_result(file_path: str, speed_rate: float, od_flag, cvt_flag):
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            estimate_sunny_result,
            str(file_path),
            speed_rate,
            od_flag,
            cvt_flag,
        )
    except Exception as exc:
        if "Future object is not initialized" in str(exc):
            result = estimate_sunny_result(str(file_path), speed_rate, od_flag, cvt_flag)
        else:
            raise

    return result["star"], result["lnRatio"], result["columnCount"]


def get_rework_result_text(meta_data, mod_display: str, sr: float, speed_rate: float, od_flag, LN_ratio: float, column_count: int):
    result = []
    extra_parts = []

    if speed_rate != 1.0:
        speed_str = f"{speed_rate:.2f}".rstrip("0").rstrip(".")
        extra_parts.append(f"x{speed_str}")
    if isinstance(od_flag, (int, float)):
        extra_parts.append(f"OD{od_flag}")

    if isinstance(meta_data, dict):
        result.append(f"{meta_data['Creator']} // {meta_data['Artist']} - {meta_data['Title']} [{meta_data['Version']}]")
    else:
        result.append("解析元信息出错")

    if extra_parts:
        result.append(f"Mods: {mod_display}, " + ", ".join(extra_parts))
    else:
        result.append(f"Mods: {mod_display}")

    if LN_ratio:
        result.append(f"LN占比: {LN_ratio:.2%}")

    if column_count in (4, 6, 7):
        result.append(f"参考难度 ({column_count}K):  {est_diff(sr, LN_ratio, column_count)}")

    result.append(f"Rework结果 => {sr:.2f}")

    return " \n谱面信息：\n" + "\n".join(result)


async def process_chart_file(chart_file: Path, speed_rate: float, od_flag, cvt_flag, mod_display: str) -> str:
    try:
        if is_mc_file(str(chart_file)):
            osu_file_path = convert_mc_to_osu(str(chart_file), str(chart_file.parent))
            chart_file = Path(osu_file_path)

        sr, LN_ratio, column_count = await get_rework_result(str(chart_file), speed_rate, od_flag, cvt_flag)

        meta_data = parse_osu_filename(chart_file.name)
        if not meta_data:
            osu_obj = osu_file(str(chart_file))
            osu_obj.process()
            meta_data = osu_obj.meta_data

        return get_rework_result_text(meta_data, mod_display, sr, speed_rate, od_flag, LN_ratio, column_count)

    except ParseError:
        return f"{chart_file.name}: 谱面解析失败"
    except NotManiaError:
        return f"{chart_file.name}: 不是mania模式"
    except Exception as e:
        return f"{chart_file.name}: 计算失败 - {e}"


async def process_zip_file(CACHE_DIR: Path, zip_file: Path, speed_rate: float, od_flag, cvt_flag, mod_display: str) -> list[str]:
    results = []
    temp_dir_name = f"rework_batch_{int(time.time())}_{os.getpid()}"
    temp_path = CACHE_DIR / temp_dir_name
    temp_path.mkdir(parents=True, exist_ok=True)

    try:
        chart_files = extract_zip_file(zip_file, temp_path)

        if not chart_files:
            return ["压缩包中没有找到可处理的谱面文件"]

        tasks = []
        for chart_file in chart_files:
            task = process_chart_file(chart_file, speed_rate, od_flag, cvt_flag, mod_display)
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append(f"{chart_files[i].name}: 处理异常 - {result}")
            else:
                processed_results.append(result)

        return processed_results

    except Exception as e:
        return [f"压缩包处理失败: {e}"]
    finally:
        if temp_path.exists():
            shutil.rmtree(temp_path, ignore_errors=True)
