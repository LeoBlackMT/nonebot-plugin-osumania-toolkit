# -*- coding: utf-8 -*-
"""
严格使用 YAVSRG: prelude/src/Formats/osu!/Converter.fs 的 osu!mania -> Chart 转换逻辑

实现范围：
- keys：从 [Difficulty] CircleSize 读取（失败默认 4）
- hitobjects：支持 HitCircle 与 Hold（mania LN）
- timingpoints：按 convert_timing_points 算 BPM + SV
- SV 清洗：按 Conversions.cleaned_sv 算法去重 + 过滤

注意：由于解析逻辑和需要的数据与 osu_file_parser.py 中相差较大，因此 /pattern 使用了独立的 osu_parser.py 来实现解析功能，保持与 Converter.fs 的等价性；而不是在 osu_file_parser.py 中添加相关逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .chart import Chart, BPM, NoteRow, NoteType, TimeItem
from .time_types import Time


# ----------------------------
# 轻量分段解析
# ----------------------------

def _parse_sections(lines: List[str]) -> Dict[str, List[str]]:
    sec = None
    out: Dict[str, List[str]] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("[") and line.endswith("]"):
            sec = line[1:-1]
            out.setdefault(sec, [])
        else:
            if sec is None:
                continue
            out[sec].append(line)
    return out


def _parse_kv(section_lines: List[str]) -> Dict[str, str]:
    out = {}
    for line in section_lines:
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


# ----------------------------
# osu timing point 数据结构（对应 TimingPoints.fs）
# ----------------------------

@dataclass
class UninheritedTimingPoint:
    Time: float
    MsPerBeat: float
    Meter: int


@dataclass
class InheritedTimingPoint:
    Time: float
    Multiplier: float


TimingPoint = Tuple[str, object]  # ("Uninherited", UninheritedTimingPoint) or ("Inherited", InheritedTimingPoint)


# ----------------------------
# osu hitobject 数据结构（对应 HitObjects + Converter match 分支）
# ----------------------------

@dataclass
class HitCircle:
    X: float
    Time: int


@dataclass
class Hold:
    X: float
    Time: int
    EndTime: int


HitObject = Tuple[str, object]  # ("HitCircle", HitCircle) or ("Hold", Hold) or others


# ----------------------------
# Converter.fs: convert_hit_objects 完全等价实现
# ----------------------------

def _time_of_number(x: float | int) -> Time:
    # F# Time.of_number：内部单位是 ms（float32<ms>），这里直接 float
    return float(x)


def convert_hit_objects(objects: List[HitObject], keys: int) -> List[TimeItem[NoteRow]]:
    output: List[TimeItem[NoteRow]] = []
    holding_until: List[Optional[Time]] = [None for _ in range(keys)]
    last_row: TimeItem[NoteRow] = TimeItem(Time=float("-inf"), Data=[])

    def x_to_column(x: float) -> int:
        # x / 512.0 * keys |> int |> min(keys-1) |> max 0
        col = int(x / 512.0 * float(keys))
        if col < 0:
            col = 0
        if col > keys - 1:
            col = keys - 1
        return col

    def find_earliest_upcoming_release() -> Time:
        earliest = float("inf")
        for h in holding_until:
            if h is not None:
                earliest = min(earliest, h)
        return earliest

    def finish_holds(time: Time) -> None:
        nonlocal last_row
        earliest = find_earliest_upcoming_release()

        while earliest < time:
            for k in range(keys):
                if holding_until[k] == earliest:
                    assert earliest >= last_row.Time

                    if earliest > last_row.Time:
                        last_row = TimeItem(Time=earliest, Data=[NoteType.NOTHING for _ in range(keys)])
                        output.append(last_row)

                        for kk in range(keys):
                            if holding_until[kk] is not None:
                                last_row.Data[kk] = NoteType.HOLDBODY

                    if last_row.Data[k] in (NoteType.NOTHING, NoteType.HOLDBODY):
                        last_row.Data[k] = NoteType.HOLDTAIL
                        holding_until[k] = None
                    else:
                        raise ValueError("impossible (HOLDTAIL overwrite conflict)")

            earliest = find_earliest_upcoming_release()

    def add_note(column: int, time: Time) -> None:
        nonlocal last_row
        finish_holds(time)
        assert time >= last_row.Time

        if time > last_row.Time:
            last_row = TimeItem(Time=time, Data=[NoteType.NOTHING for _ in range(keys)])
            output.append(last_row)

            for k in range(keys):
                if holding_until[k] is not None:
                    last_row.Data[k] = NoteType.HOLDBODY

        cur = last_row.Data[column]
        if cur == NoteType.NOTHING:
            last_row.Data[column] = NoteType.NORMAL
        elif cur in (NoteType.NORMAL, NoteType.HOLDHEAD):
            # F# 这里 Logging.Debug "Fixing stacked note..."
            # 等价行为：不抛错，不改写
            pass
        else:
            # HOLDBODY/HOLDTAIL 冲突：skip_conversion
            raise ValueError(f"Stacked note at {time}, column {column+1}, coincides with {cur}")

    def start_hold(column: int, time: Time, end_time: Time) -> None:
        nonlocal last_row
        finish_holds(time)
        assert time >= last_row.Time
        assert end_time > time

        if time > last_row.Time:
            last_row = TimeItem(Time=time, Data=[NoteType.NOTHING for _ in range(keys)])
            output.append(last_row)

            for k in range(keys):
                if holding_until[k] is not None:
                    last_row.Data[k] = NoteType.HOLDBODY

        cur = last_row.Data[column]
        if cur == NoteType.NOTHING:
            last_row.Data[column] = NoteType.HOLDHEAD
            holding_until[column] = end_time
        elif cur == NoteType.NORMAL:
            # F#：Fixing stacked note + LN head：允许覆盖成 HOLDHEAD
            last_row.Data[column] = NoteType.HOLDHEAD
            holding_until[column] = end_time
        else:
            raise ValueError(f"Stacked LN at {time}, column {column+1}, head coincides with {cur}")

    for kind, obj in objects:
        if kind == "HitCircle":
            o: HitCircle = obj  # type: ignore
            add_note(x_to_column(o.X), _time_of_number(o.Time))
        elif kind == "Hold":
            o: Hold = obj  # type: ignore
            if o.EndTime > o.Time:
                start_hold(x_to_column(o.X), _time_of_number(o.Time), _time_of_number(o.EndTime))
            else:
                add_note(x_to_column(o.X), _time_of_number(o.Time))
        else:
            # Slider/Spinner 等在 mania 理论上不该出现；F# 是 _ -> ()
            pass

    finish_holds(float("inf"))
    return output


# ----------------------------
# Converter.fs: convert_timing_points 等价实现
# ----------------------------

def _find_bpm_durations(points: List[TimingPoint], end_time: Time) -> Dict[float, float]:
    """
    返回 dict[ms_per_beat] = duration_ms
    等价 Converter.fs 中 find_bpm_durations（只统计 Uninherited）
    """
    uninherited: List[UninheritedTimingPoint] = []
    for kind, p in points:
        if kind == "Uninherited":
            uninherited.append(p)  # type: ignore

    if len(uninherited) == 0:
        raise ValueError("Beatmap has no BPM points set")

    data: Dict[float, float] = {}
    x = uninherited[0]
    xs = uninherited[1:]

    current = float(x.MsPerBeat)  # ms/beat
    time = _time_of_number(x.Time)

    for b in xs:
        if current not in data:
            data[current] = 0.0
        data[current] += (_time_of_number(b.Time) - time)
        time = _time_of_number(b.Time)
        current = float(b.MsPerBeat)

    if current not in data:
        data[current] = 0.0
    data[current] += max(end_time - time, 0.0)

    return data


def convert_timing_points(points: List[TimingPoint], end_time: Time) -> Tuple[List[TimeItem[BPM]], List[TimeItem[float]]]:
    durations = _find_bpm_durations(points, end_time)
    # most_common_mspb = durations.OrderByDescending(Value).First().Key
    most_common_mspb = sorted(durations.items(), key=lambda kv: kv[1], reverse=True)[0][0]

    sv: List[TimeItem[float]] = []
    bpm: List[TimeItem[BPM]] = []

    current_bpm_mult = 1.0

    for kind, p in points:
        if kind == "Uninherited":
            b: UninheritedTimingPoint = p  # type: ignore
            mspb = float(b.MsPerBeat)
            bpm.append(TimeItem(Time=_time_of_number(b.Time), Data=BPM(Meter=int(b.Meter), MsPerBeat=mspb)))
            current_bpm_mult = float(most_common_mspb) / float(mspb) if mspb != 0 else 1.0
            sv.append(TimeItem(Time=_time_of_number(b.Time), Data=current_bpm_mult))
        else:
            s: InheritedTimingPoint = p  # type: ignore
            sv.append(TimeItem(Time=_time_of_number(s.Time), Data=current_bpm_mult * float(s.Multiplier)))

    return bpm, sv


# ----------------------------
# Conversions.fs: cleaned_sv 等价实现（你之前片段里给出的逻辑）
# ----------------------------

def cleaned_sv(sv: List[TimeItem[float]]) -> List[TimeItem[float]]:
    """
    等价 prelude/src/Formats/Conversions.fs cleaned_sv
    - 先按 Time 去重：保留同时间点的“最后一个”（F# 做法是 rev -> distinctBy Time -> rev）
    - 再过滤掉与 previous_value 差小于等于 0.005 的点
    """
    if not sv:
        return []

    # dedup: keep last for each time
    rev = list(reversed(sv))
    seen = set()
    dedup_rev: List[TimeItem[float]] = []
    for item in rev:
        if item.Time in seen:
            continue
        seen.add(item.Time)
        dedup_rev.append(item)
    dedup = list(reversed(dedup_rev))

    out: List[TimeItem[float]] = []
    previous_value = 1.0
    for s in dedup:
        if abs(float(s.Data) - previous_value) > 0.005:
            out.append(s)
            previous_value = float(s.Data)
    return out


# ----------------------------
# .osu 文件解析为 HitObjects + TimingPoints（够 Converter 用）
# ----------------------------

def _parse_timing_points(lines: List[str]) -> List[TimingPoint]:
    out: List[TimingPoint] = []
    for line in lines:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        t = float(parts[0])
        beat_len = float(parts[1])
        meter = int(parts[2]) if len(parts) > 2 and parts[2] else 4
        uninherited = int(parts[6]) if len(parts) > 6 and parts[6] else 1

        if uninherited == 1:
            # UninheritedTimingPoint: MsPerBeat=max 0.0（TimingPoints.fs Create）
            out.append(("Uninherited", UninheritedTimingPoint(Time=t, MsPerBeat=max(0.0, beat_len), Meter=meter)))
        else:
            # Inherited: Multiplier = -100.0/beatLength (TimingPoints.fs ToString 反推)
            # beat_len 通常为负；若为 0 则跳过
            if beat_len == 0:
                continue
            mult = (-100.0 / beat_len)
            out.append(("Inherited", InheritedTimingPoint(Time=t, Multiplier=mult)))
    # osu 文件一般已按时间排序；这里不额外排序（保持原文件顺序，等价 Converter 的 for p in points）
    return out


def _parse_hit_objects(lines: List[str]) -> List[HitObject]:
    out: List[HitObject] = []
    for line in lines:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        x = float(parts[0])
        time = int(float(parts[2]))
        typ = int(parts[3])

        is_hold = (typ & 128) != 0  # mania hold flag
        if is_hold:
            # mania hold: objectParams 在 parts[5]，格式 "endTime:..."
            if len(parts) >= 6 and parts[5]:
                end_part = parts[5].split(":")[0]
                try:
                    end_time = int(float(end_part))
                except Exception:
                    end_time = time
            else:
                end_time = time
            out.append(("Hold", Hold(X=x, Time=time, EndTime=end_time)))
        else:
            # mania 普通 note：按 HitCircle 处理
            out.append(("HitCircle", HitCircle(X=x, Time=time)))
    return out


def parse_osu_mania(path: str) -> Chart:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    sections = _parse_sections(lines)

    diff = _parse_kv(sections.get("Difficulty", []))
    try:
        keys = int(float(diff.get("CircleSize", "4")))
    except Exception:
        keys = 4

    timing_points = _parse_timing_points(sections.get("TimingPoints", []))
    hit_objects = _parse_hit_objects(sections.get("HitObjects", []))

    # 等价 Converter.convert_internal 的关键部分：
    snaps = convert_hit_objects(hit_objects, keys)
    if len(snaps) == 0:
        # Converter 里会因为 TimeArray.last snaps 报错；这里给个更可读错误
        raise ValueError("Beatmap has no hitobjects after conversion")

    end_time = snaps[-1].Time
    bpm, sv = convert_timing_points(timing_points, end_time)
    sv = cleaned_sv(sv)

    return Chart(
        Keys=keys,
        Notes=snaps,
        BPM=bpm,
        SV=sv,
    )