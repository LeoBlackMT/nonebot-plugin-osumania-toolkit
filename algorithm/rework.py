import os
import zipfile
import asyncio
import time
import shutil

from pathlib import Path
from ..file.osu_file_parser import osu_file

from .xxy_algorithm import calculate
from ..algorithm.convert import convert_mc_to_osu
from ..algorithm.utils import is_mc_file, parse_osu_filename
from ..file.data import sr_intervals_data

# 自定义异常，用于捕获特定错误类型，便于在调用处进行针对性处理
class ParseError(Exception):
    pass


class NotManiaError(Exception):
    pass

def get_rework_result_text(meta_data, mod_display: str, sr: float, speed_rate: float, od_flag, LN_ratio: float, column_count: int):
    
    result = []
    extra_parts = []
    
    if speed_rate != 1.0:
        # 格式化倍速，去掉末尾多余的0和小数点
        speed_str = f"{speed_rate:.2f}".rstrip('0').rstrip('.')
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
        
    if column_count == 4 or column_count == 7 or column_count == 6:
        result.append(f"参考难度 ({column_count}K):  {est_diff(sr, LN_ratio, column_count)}")
        
    result.append(f"Rework结果 => {sr:.2f}")

    return " \n谱面信息：\n" + "\n".join(result)

async def get_rework_result(file_path: str, speed_rate: float, od_flag, cvt_flag):
    loop = asyncio.get_running_loop()
    # 将转换标记传入算法
    result = await loop.run_in_executor(
        None,
        calculate,
        str(file_path),
        speed_rate,
        od_flag,
        cvt_flag
    )

    if isinstance(result, (int, float)):
        if result == -1:
            raise ParseError()
        if result == -2:
            raise NotManiaError()
        raise Exception(f"UnknownCalculateResult: {result}")

    sr = result[0]
    LN_ratio = result[1]
    column_count = result[2]
    if sr == -1:
        raise ParseError()
    if sr == -2:
        raise NotManiaError()
    return sr, LN_ratio, column_count

def extract_zip_file(zip_path: Path, extract_dir: Path) -> list[Path]:
    """解压zip文件并返回所有.osu和.mc文件的路径列表"""
    extracted_files = []
    
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        file_list = zip_ref.namelist()
        chart_files = [f for f in file_list if f.lower().endswith(('.osu', '.mc'))]
        
        if not chart_files:
            raise ValueError("压缩包中没有找到.osu或.mc文件")
        
        for file in chart_files:
            target_path = extract_dir / os.path.basename(file)
            zip_ref.extract(file, extract_dir)
            
            extracted_path = extract_dir / file
            if extracted_path.exists():
                if extracted_path != target_path:
                    extracted_path.rename(target_path)
                extracted_files.append(target_path)
    
    return extracted_files

async def process_chart_file(chart_file: Path, speed_rate: float, od_flag, cvt_flag, mod_display: str) -> str:
    """处理单个谱面文件并返回结果文本"""
    try:
        if is_mc_file(str(chart_file)):
            osu_file_path = convert_mc_to_osu(str(chart_file), str(chart_file.parent))
            chart_file = Path(osu_file_path)
        
        sr, LN_ratio, column_count = await get_rework_result(str(chart_file), speed_rate, od_flag, cvt_flag)
        
        meta_data = parse_osu_filename(chart_file.name)
        if not meta_data:
            osu_obj = osu_file(chart_file)
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
    """处理压缩包文件并返回所有结果"""
    results = []
    
    # 创建唯一的临时目录
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
        # 清理临时目录
        if temp_path.exists():
            shutil.rmtree(temp_path, ignore_errors=True)

def est_diff(sr: float, LN_ratio: float, column_count: int) -> str:
    if column_count == 4:
        RC_diff = None
        for lower, upper, name in sr_intervals_data.RC_intervals_4K:
            if lower <= sr <= upper:
                RC_diff = name
                break
        if RC_diff is None:
            if sr < 1.502:
                RC_diff = "< Intro 1 low"
            elif sr > 11.129:
                RC_diff = "> Theta high"
            else:
                RC_diff = "未知RC难度"

        if LN_ratio < 0.1:
            return f"{RC_diff}"
        
        LN_diff = None
        for lower, upper, name in sr_intervals_data.LN_intervals_4K:
            if lower <= sr <= upper:
                LN_diff = name
                break
        if LN_diff is None:
            if sr < 4.832:
                LN_diff = "< LN 5 mid"
            elif sr > 9.589:
                LN_diff = "> LN 17 high"
            else:
                LN_diff = "未知LN难度"
        
        if LN_ratio > 0.9:
            return f"{LN_diff}"
        
        return f"{RC_diff} || {LN_diff}"

    if column_count == 6:
        RC_diff = None
        for lower, upper, name in sr_intervals_data.RC_intervals_6K:
            if lower <= sr <= upper:
                RC_diff = name
                break
        if RC_diff is None:
            if sr < 3.430:
                RC_diff = "< Regular 0 low"
            elif sr > 7.965:
                RC_diff = "> Regular 9 high"
            else:
                RC_diff = "未知RC难度"

        if LN_ratio < 0.1:
            return f"{RC_diff}"

        LN_diff = None
        for lower, upper, name in sr_intervals_data.LN_intervals_6K:
            if lower <= sr <= upper:
                LN_diff = name
                break
        if LN_diff is None:
            if sr < 3.530:
                LN_diff = "< LN 0 low"
            elif sr > 9.700:
                LN_diff = "> LN Finish high"
            else:
                LN_diff = "未知LN难度"

        if LN_ratio > 0.9:
            return f"{LN_diff}"

        return f"{RC_diff} || {LN_diff}"
    
    if column_count == 7:
        RC_diff = None
        for lower, upper, name in sr_intervals_data.RC_intervals_7K:
            if lower <= sr <= upper:
                RC_diff = name
                break
        if RC_diff is None:
            if sr < 3.5085:
                RC_diff = "< Regular 0 low"
            elif sr > 10.544:
                RC_diff = "> Regular Stellium high"
            else:
                RC_diff = "未知RC难度"

        if LN_ratio < 0.1:
            return f"{RC_diff}"
        
        LN_diff = None
        for lower, upper, name in sr_intervals_data.LN_intervals_7K:
            if lower <= sr <= upper:
                LN_diff = name
                break
        if LN_diff is None:
            if sr < 4.836:
                LN_diff = "< LN 3 low"
            elif sr > 10.666:
                LN_diff = "> LN Stellium high"
            else:
                LN_diff = "未知LN难度"
        
        if LN_ratio > 0.9:
            return f"{LN_diff}"
        
        return f"{RC_diff} || {LN_diff}"
    
    return "未知难度"