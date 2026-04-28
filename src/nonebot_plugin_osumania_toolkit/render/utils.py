import gc
import matplotlib
matplotlib.use('Agg')

from matplotlib import pyplot as plt
from functools import wraps
from typing import Optional

from ..algorithm.matching.matching import match_notes_and_presses
from ..parser.osr_file_parser import osr_file
from ..parser.osu_file_parser import osu_file
from ..parser.ruleset_file_parser import ruleset_file

_SCOREV2_MOD_BIT = 536870912

def safe_plot(func):
    """
    装饰器：确保绘图函数即使出错也能正确清理资源
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        finally:
            # 关闭所有打开的图形，释放资源
            plt.close('all')
            # 强制垃圾回收，清理 matplotlib 对象
            gc.collect()
    return wrapper


def has_scorev2_mod(osr_obj: Optional[osr_file]) -> bool:
    if osr_obj is None:
        return False

    mod_value = int(getattr(osr_obj, "mod", 0) or 0)
    if mod_value & _SCOREV2_MOD_BIT:
        return True

    mods = getattr(osr_obj, "mods", [])
    if isinstance(mods, list):
        return any(str(m).lower() == "scorev2" for m in mods)
    return False


def build_default_rulesets(osu_obj: Optional[osu_file], osr_obj: Optional[osr_file]) -> list[ruleset_file]:
    if osu_obj is None:
        return []

    od_value = float(getattr(osu_obj, "od", 8.0) or 8.0)
    prefer_sv2 = has_scorev2_mod(osr_obj)
    template_order = ["osu-sv2", "osu"] if prefer_sv2 else ["osu", "osu-sv2"]

    built: list[ruleset_file] = []
    for name in template_order:
        rs = ruleset_file(("template", name, od_value))
        if rs.status == "OK":
            built.append(rs)
    return built


def match_for_visualization(osu_obj: osu_file, osr_obj: osr_file) -> tuple[list[tuple[int, float]], list[tuple[int, float, float]]]:
    fallback_delta: list[tuple[int, float]] = []
    fallback_pairs: list[tuple[int, float, float]] = []

    for ruleset_obj in build_default_rulesets(osu_obj, osr_obj):
        for use_chart_time in (True, False):
            match_result = match_notes_and_presses(osu_obj, osr_obj, ruleset_obj, use_chart_time=use_chart_time)
            if match_result.get("status") != "OK":
                continue

            delta_list = list(match_result.get("delta_list", []))
            matched_pairs = list(match_result.get("matched_pairs", []))

            if delta_list and matched_pairs:
                return delta_list, matched_pairs

            if not fallback_delta and delta_list:
                fallback_delta = delta_list
            if not fallback_pairs and matched_pairs:
                fallback_pairs = matched_pairs

    return fallback_delta, fallback_pairs