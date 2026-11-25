from __future__ import annotations

from typing import Any

from .windows import compute_windows
from .accumulator import LaneAccumulator
from .malody import analyze_malody_lanes
from .raw_frames import frames_to_sv1_events
from .chart import LaneChart, hand_groups, build_lane_chart
from .stable_v2 import stable_v2_windows, frames_to_stable_v2_events

_MODE_LABELS = {
    "stbv1": "Stable V1",
    "stbv2": "Stable V2",
    "lzr": "Lazer",
    "mr": "Malody",
}
_WEIGHT_LABELS = {
    "stbv1": "300",
    "stbv2": "305",
    "lzr": "305",
    "mr": "100/75/40/0",
}


def normalize_mode(value: str | None) -> str | None:
    if value is None:
        return None
    mode = str(value).strip().lower()
    if mode == "lazer":
        mode = "lzr"
    if mode not in _MODE_LABELS:
        raise ValueError("模式必须是 stbv1、stbv2、lzr/lazer")
    return mode


def detect_mode(osr_obj: Any = None, mr_obj: Any = None) -> str:
    if mr_obj is not None:
        return "mr"
    if osr_obj is None:
        raise ValueError("缺少回放")
    if int(getattr(osr_obj, "game_version", 0) or 0) >= 30_000_000:
        return "lzr"
    mods = [str(mod).upper() for mod in (getattr(osr_obj, "mods", []) or [])]
    mod_value = int(getattr(osr_obj, "mod", 0) or 0)
    if (mod_value & (1 << 29)) or "SCOREV2" in mods or "SV2" in mods:
        return "stbv2"
    return "stbv1"


def _speed_rate(osr_obj: Any) -> float:
    value = getattr(osr_obj, "score_info_speed_rate", None)
    if value is None:
        value = getattr(osr_obj, "speed_factor", 1.0)
    try:
        rate = float(value)
    except (TypeError, ValueError):
        rate = 1.0
    return rate if rate > 0 else 1.0


def _osr_frames(osr_obj: Any, rate: float) -> list[tuple[float, int]]:
    """把 .osr 的 LZMA 帧还原为绝对谱面时间（.osr 帧已是 chart time）。"""
    del rate  # 仅用于窗口缩放；帧时间不再乘 rate
    compressed = getattr(osr_obj, "compressed_data", None)
    if not compressed:
        return [
            (float(time_ms), int(mask))
            for time_ms, mask in (getattr(osr_obj, "replay_data_chart", []) or [])
        ]
    import lzma

    try:
        text = lzma.decompress(compressed).decode("ascii", "ignore")
    except Exception:
        return []
    current = 0.0
    last_state = 256
    frames: list[tuple[float, int]] = []
    for entry in text.split(","):
        parts = entry.split("|")
        if len(parts) < 2 or parts[0] == "-12345":
            continue
        try:
            current += float(parts[0])
            state = int(parts[1])
        except (TypeError, ValueError):
            continue
        if state != last_state:
            frames.append((current, state))
            last_state = state
    return frames


def _mr_frames(mr_obj: Any) -> list[tuple[float, int]]:
    frames: list[tuple[float, int]] = []
    mask = 0
    last = -1
    for time_ms, action, column in getattr(mr_obj, "actions", []) or []:
        col = int(column)
        if col < 0 or col >= 32:
            continue
        bit = 1 << col
        if int(action) == 1:
            mask |= bit
        elif int(action) == 2:
            mask &= ~bit
        else:
            continue
        if mask != last:
            frames.append((float(time_ms), mask))
            last = mask
    return frames


def _column_presses(
    frames: list[tuple[float, int]], column_count: int, mirror: bool = False
) -> tuple[list[list[float]], list[list[float]]]:
    press = [[] for _ in range(column_count)]
    release = [[] for _ in range(column_count)]
    prev = 0
    for time_ms, raw_mask in frames:
        mask = int(raw_mask)
        if mirror:
            mirrored = 0
            for col in range(column_count):
                if mask & (1 << col):
                    mirrored |= 1 << (column_count - 1 - col)
            mask = mirrored
        changed = mask ^ prev
        if changed:
            for col in range(column_count):
                bit = 1 << col
                if changed & bit:
                    (press if mask & bit else release)[col].append(float(time_ms))
        prev = mask
    return press, release


def _no_regrab_drop_notes(
    chart: LaneChart,
    frames: list[tuple[float, int]],
    windows,
    mods: list[str],
) -> set[int]:
    """帧级识别“早松手且尾前无 regrab”的 LN（源 noRegrabDrops 的语义重建）。"""
    mirror = any(str(mod).upper() == "MR" for mod in mods)
    press, release = _column_presses(frames, chart.column_count, mirror)
    result: set[int] = set()
    for col in range(chart.column_count):
        notes = [i for i in range(chart.note_count) if int(chart.columns[i]) == col]
        press_index = 0
        release_index = 0
        for note in notes:
            start = float(chart.note_starts[note])
            end = float(chart.note_ends[note])
            while (
                press_index < len(press[col])
                and press[col][press_index] < start - windows.miss
            ):
                press_index += 1
            if (
                press_index >= len(press[col])
                or press[col][press_index] > start + windows.ok
            ):
                continue
            press_time = press[col][press_index]
            press_index += 1
            if not bool(chart.is_hold[note]):
                continue
            while (
                release_index < len(release[col])
                and release[col][release_index] < press_time - 5.0
            ):
                release_index += 1
            if release_index >= len(release[col]):
                continue
            release_time = release[col][release_index]
            if release_time > end + windows.ok:
                continue
            release_index += 1
            if release_time - end >= -windows.meh:
                continue
            regrabbed = any(
                release_time < press_time_value < end + windows.miss
                for press_time_value in press[col][press_index:]
            )
            if not regrabbed:
                result.add(note)
    return result


def _lane_payload(snapshot: dict, column_count: int) -> tuple[list[dict], dict]:
    middle = column_count // 2 if column_count % 2 == 1 else -1
    lanes = [lane for lane in snapshot["lanes"] if lane["column"] != middle]
    overall = {
        "acc": snapshot.get("acc"),
        "judged": snapshot.get("judged", 0),
        "miss": sum(lane["miss"] for lane in snapshot["lanes"]),
        "counts": snapshot.get("counts", []),
        "source": "accumulator",
    }
    return lanes, overall


def analyze_laneacc(
    osu_obj: Any,
    *,
    osr_obj: Any = None,
    mr_obj: Any = None,
    mode_override: str | None = None,
) -> dict[str, Any]:
    chart = build_lane_chart(osu_obj)
    if mr_obj is not None and mode_override:
        raise ValueError(".mr 回放不支持 -mode，自动按 Malody 模式分析")
    mode = normalize_mode(mode_override) or detect_mode(osr_obj=osr_obj, mr_obj=mr_obj)
    if mode == "mr" and mr_obj is None:
        raise ValueError(".mr 模式缺少 Malody 回放")
    if mode != "mr" and osr_obj is None:
        raise ValueError("缺少 .osr 回放")

    warnings: list[str] = []
    if mode == "mr":
        malody = analyze_malody_lanes(mr_obj, chart)
        middle = chart.column_count // 2 if chart.column_count % 2 == 1 else -1
        lanes = [lane for lane in malody.lanes if lane["column"] != middle]
        overall = malody.overall
        warnings.extend(malody.warnings)
        rate = malody.rate
        hands = {"left": None, "right": None, "space": None}
        groups = hand_groups(chart.column_count, "independent")
        # Malody 只做每轨；左右手按同一套列分组汇总
        for key in ("left", "right"):
            bounds = groups.get(key)
            if bounds is None:
                continue
            subset = [lane for lane in lanes if bounds[0] <= lane["column"] < bounds[1]]
            counts = [sum(lane["counts"][i] for lane in subset) for i in range(4)]
            judged = sum(counts)
            points = counts[0] * 100 + counts[1] * 75 + counts[2] * 40
            hands[key] = {
                "acc": points / judged if judged else None,
                "judged": judged,
                "miss": counts[3],
                "counts": counts,
            }
    else:
        rate = _speed_rate(osr_obj)
        mods = list(getattr(osr_obj, "mods", []) or [])
        frames = _osr_frames(osr_obj, rate)
        if not frames:
            raise ValueError("回放没有可用帧")
        if mode == "stbv1":
            windows = compute_windows(float(chart.od), rate, mods)
            force_drops = _no_regrab_drop_notes(chart, frames, windows, mods)
            events = frames_to_sv1_events(
                chart, frames, windows, mods, rate, force_drops=force_drops
            )
            accumulator = LaneAccumulator(
                chart, windows, score_mode="stable-v1", lane_weights=300
            )
        else:
            judgement_mode = "stable" if mode == "stbv2" else "lazer"
            v2_windows = stable_v2_windows(float(chart.od), rate, mods)
            events = frames_to_stable_v2_events(
                chart,
                frames,
                od_flag=None,
                mods=mods,
                speed_rate=rate,
                judgement_mode=judgement_mode,
            )
            accumulator = LaneAccumulator(
                chart,
                v2_windows,
                score_mode="stable-native",
                lane_weights=305,
            )
        accumulator.apply_events(events)
        accumulator.finish()
        snapshot = accumulator.snapshot()
        lanes, overall = _lane_payload(snapshot, chart.column_count)
        hands = snapshot["hands"]
        if mode == "lzr":
            warnings.append("Lazer 回放按 Lazer 式 V2 帧重建，非原生 HitEvent。")
        elif mode == "stbv2":
            warnings.append("Stable V2 分轨由原始帧重建。")

    return {
        "mode": mode,
        "mode_label": _MODE_LABELS[mode],
        "weights_label": _WEIGHT_LABELS[mode],
        "rate": rate,
        "keys": chart.column_count,
        "lanes": lanes,
        "hands": hands,
        "overall": overall,
        "warnings": warnings,
        "data_source": "mr" if mode == "mr" else "osr",
    }
