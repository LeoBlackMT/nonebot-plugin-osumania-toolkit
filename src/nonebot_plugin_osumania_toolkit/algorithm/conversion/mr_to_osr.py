"""Convert Malody .mr replays to osu! .osr format."""
from __future__ import annotations

import datetime

from nonebot.log import logger

from .mods_ma_to_osu import malody_mods_to_osu_mods
from ...parser.mr_file_parser import mr_file
from ...parser.osr_file_parser import osr_file


def convert_mr_to_osr(mr_obj: mr_file) -> osr_file:
    """
    summary:
        将 mr_file 对象转换为 osr_file 实例，并保持旧字段兼容。
        .mr 时间通常已是 1.0x chart 时间，因此本转换默认保持 real/chart 一致，
        但仍显式填充 press_events_real / press_events_chart 双时间线字段。
    Args:
        mr_obj: 解析后的 mr_file 对象。
    Returns:
        可直接用于旧流程的 osr_file 对象。
    """
    osr = osr_file.__new__(osr_file)
    osr._init_derived_attrs()

    osr.assume_replay_times_scaled = False
    osr.keep_float_times = True
    osr.log_level_override = None
    osr.allow_force_no_scale = True

    osr.file_path = mr_obj.file_path
    osr.status = mr_obj.status
    osr.player_name = "ConvertedFromMalody"
    osr.mod, osr.mods = malody_mods_to_osu_mods(mr_obj.mods_flags)

    osr.speed_factor = 1.0
    osr.corrector = 1.0
    osr.scale_applied = False

    osr.judge = {
        "320": mr_obj.best_count,
        "300": 0,
        "200": mr_obj.cool_count,
        "100": mr_obj.good_count,
        "50": 0,
        "0": mr_obj.miss_count,
    }
    osr.score = 0
    osr.ratio = 0

    tot_obj = mr_obj.best_count + mr_obj.cool_count + mr_obj.good_count + mr_obj.miss_count
    if tot_obj > 0:
        osr.acc = (mr_obj.best_count * 100 + mr_obj.cool_count * 75 + mr_obj.good_count * 40) / (tot_obj * 100) * 100
    else:
        osr.acc = 0.0

    osr.timestamp = datetime.datetime.fromtimestamp(mr_obj.timestamp) if mr_obj.timestamp else datetime.datetime.min
    osr.life_bar_graph = ""

    osr.pressset_raw = [list(col) for col in mr_obj.pressset_raw]
    osr.pressset = [list(col) for col in mr_obj.pressset]
    osr.intervals_raw = list(mr_obj.intervals_raw)
    osr.intervals = list(mr_obj.intervals)

    osr.press_times_raw = list(mr_obj.press_times_raw)
    osr.press_events_raw = list(mr_obj.press_events_raw)

    osr.press_times_real_float = list(mr_obj.press_times_real_float)
    osr.press_events_real_float = list(mr_obj.press_events_real_float)
    osr.press_times_real = list(mr_obj.press_times_real)
    osr.press_events_real = list(mr_obj.press_events_real)

    osr.press_times_chart_float = list(mr_obj.press_times_chart_float)
    osr.press_events_chart_float = list(mr_obj.press_events_chart_float)
    osr.press_times_chart = list(mr_obj.press_times_chart)
    osr.press_events_chart = list(mr_obj.press_events_chart)

    osr.press_times_float = list(osr.press_times_chart_float)
    osr.press_events_float = list(osr.press_events_chart_float)
    osr.press_times = list(osr.press_times_chart)
    osr.press_events = list(osr.press_events_chart)

    osr.play_data = list(mr_obj.play_data)
    osr.replay_data_real = list(mr_obj.replay_data_real)
    osr.replay_data_chart = list(mr_obj.replay_data_chart)

    if osr.intervals_raw:
        osr.sample_rate = osr._estimate_sample_rate(osr.intervals_raw)
    else:
        osr.sample_rate = float("inf")

    if mr_obj.status != "OK":
        osr.status = mr_obj.status
        return osr

    valid_pressset = [p for p in osr.pressset if len(p) > 5]
    if len(valid_pressset) < 2:
        osr.status = "tooFewKeys"
    else:
        osr.status = "OK"

    logger.debug(f"按下事件总数(len(press_events)): {len(osr.press_events)}")
    logger.debug(f"按下事件总数(len(press_times))：{len(osr.press_times)}")
    logger.debug(f"按下事件时间样本（前10个）：{str(osr.press_times[:10])}")
    logger.debug(f"按下事件时间样本（后10个）：{str(osr.press_times[-10:])}")
    return osr
