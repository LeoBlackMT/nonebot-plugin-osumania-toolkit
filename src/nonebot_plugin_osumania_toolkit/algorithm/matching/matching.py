"""Note-press matching engine — ported from YAVSRG Interlude."""
from __future__ import annotations

from typing import Optional, Any

from nonebot.log import logger

from ...parser.osr_file_parser import osr_file
from ...parser.osu_file_parser import osu_file
from ...parser.ruleset_file_parser import ruleset_file

from .helpers import (
    HoldState,
    _apply_press,
    _apply_release,
    _build_hitflagdata,
    _build_event_dict,
    _build_replay_input_events,
    _empty_result,
    _estimate_chart_time_offset,
    _expire_notes,
    _extract_note_windows,
    _extract_release_judgement_windows,
    _extract_release_windows,
    _hitmechanics_etterna,
    _hitmechanics_interlude,
    _hitmechanics_osumania,
    _is_number,
    _select_press_and_replay_stream,
)


def match_notes_and_presses(
    osu: osu_file,
    osr: osr_file,
    ruleset: ruleset_file,
    *,
    use_chart_time: bool = True,
    assume_replay_times_scaled: Optional[bool] = None,
    rate: float = 1.0,
) -> dict:
    """
    使用 Interlude 风格思路对谱面 note 与回放按键进行确定性匹配。

    输入对象最小字段要求：
    - osu: 已执行 process()，且可提供 to_TimeArray() 或 note_rows；需要 column_count/od/status。
    - osr: 已执行 process()，建议提供 press_events_chart_float/replay_data_chart；
      若缺失则会回退到 real 时间字段并根据 speed_factor + assume_replay_times_scaled 决策缩放。
    - ruleset: 已执行 process()，需要 raw_data 中的 Judgements/HitMechanics/HoldMechanics。

    算法概要：
    1. 将谱面 TimeArray 构建为 HitFlagData 等价 note 列表（NORMAL / HOLD_HEAD / HOLD_TAIL），
       并按列建立索引与 start_index 增量指针。
    2. 从回放构建 down/up 输入事件流（优先 replay_data，回退 press_events）。
    3. 对每个 down 事件按 NotePriority 选择命中策略：
       - Interlude: cbrush + blocked 逻辑
       - Etterna: nearest-by-abs
       - OsuMania: earliest-first + steal blocked
    4. 对 up 事件执行 hold release 状态机，记录 RELEASE / DROP_HOLD。
    5. 按窗口过期规则补齐 MISS。

    时间缩放策略（参考 ppy/osu ReplayRecorder 与 ApplyModsToRate 思路）：
    - use_chart_time=True 时优先使用 osr 的 chart 时间线。
    - 若 chart 缺失且只有 real，则在 speed_factor != 1 时默认按 assume_replay_times_scaled 决策是否反缩放。
    - 最终在 meta 中返回 rate_used/speed_factor/scale_applied。

    返回字段：
    - status/error: 执行状态
    - matched_events: 完整事件流（HIT/HOLD_HEAD/RELEASE/DROP_HOLD/GHOST_TAP/MISS）
    - offset_vector: 与 note index 一一对应的偏移，未命中为 None
    - delta_list: 仅命中按键的 (col, delta_ms)
    - matched_pairs: (col, note_time_ms, press_time_ms)
    - unmatched_presses: 未匹配按键
    - unmatched_notes: 未匹配物件
    - note_count/press_count
    - meta: 匹配决策元数据
    """
    meta = {
        "rate_used": float(rate),
        "speed_factor": 1.0,
        "scale_applied": False,
        "chart_time_offset": 0.0,
        "note_priority": "OsuMania",
        "algorithm_version": "interlude_v1",
    }

    try:
        if osu is None or osr is None or ruleset is None:
            return _empty_result("InvalidInput", "osu/osr/ruleset 不能为空", meta)

        if str(getattr(osu, "GameMode", "3")) not in {"3", "None", ""} and getattr(osu, "status", "") == "NotMania":
            return _empty_result("NotMania", "仅支持 mania 谱面", meta)

        if not isinstance(getattr(ruleset, "raw_data", None), dict):
            return _empty_result("InvalidInput", "ruleset.raw_data 缺失或无效", meta)

        if rate <= 0:
            return _empty_result("InvalidInput", "rate 必须大于 0", meta)

        notes, notes_by_col, tails_by_col, keys = _build_hitflagdata(osu)
        if not notes or keys <= 0:
            return _empty_result("InvalidInput", "谱面 note_rows 为空或列数无效", meta)

        ruleset_data = ruleset.raw_data
        early_note_window, late_note_window, judgement_windows, has_any_window = _extract_note_windows(ruleset_data)
        release_early_window, release_late_window = _extract_release_windows(
            ruleset_data,
            default_early=early_note_window,
            default_late=late_note_window,
        )
        release_judgement_windows = _extract_release_judgement_windows(ruleset_data, judgement_windows)

        note_priority = (
            ((ruleset_data.get("HitMechanics") or {}).get("NotePriority"))
            if isinstance(ruleset_data.get("HitMechanics"), dict)
            else "OsuMania"
        )
        meta["note_priority"] = note_priority

        cbrush_threshold = 0.0
        if isinstance(note_priority, dict) and _is_number(note_priority.get("Interlude")):
            cbrush_threshold = float(note_priority["Interlude"])

        ghost_tap_judgement = None
        hit_mechanics = ruleset_data.get("HitMechanics") if isinstance(ruleset_data.get("HitMechanics"), dict) else {}
        ghost_raw = hit_mechanics.get("GhostTapJudgement") if isinstance(hit_mechanics, dict) else None
        if isinstance(ghost_raw, int):
            ghost_tap_judgement = ghost_raw

        press_events, replay_data, speed_factor, scale_applied = _select_press_and_replay_stream(
            osr,
            use_chart_time=use_chart_time,
            assume_replay_times_scaled=assume_replay_times_scaled,
            rate=rate,
        )

        chart_time_offset = _estimate_chart_time_offset(
            osu=osu,
            press_events=press_events,
            replay_data=replay_data,
            use_chart_time=use_chart_time,
        )
        if chart_time_offset != 0.0:
            press_events = [(col, float(t + chart_time_offset)) for col, t in press_events]
            replay_data = [(float(t + chart_time_offset), mask) for t, mask in replay_data]

        meta["speed_factor"] = float(speed_factor)
        meta["scale_applied"] = bool(scale_applied)
        meta["chart_time_offset"] = float(chart_time_offset)

        if not press_events and not replay_data:
            return _empty_result("InvalidInput", "回放按键事件为空", meta)

        mirror = (int(getattr(osr, "mod", 0) or 0) & 1073741824) != 0
        input_events = _build_replay_input_events(
            replay_data=replay_data,
            press_events=press_events,
            keys=keys,
            mirror=mirror,
        )
        if not input_events:
            return _empty_result("InvalidInput", "无法构建输入事件流", meta)

        note_start_index: dict[int, int] = {col: 0 for col in range(keys)}
        search_start_index: dict[int, int] = {col: 0 for col in range(keys)}
        tail_start_index: dict[int, int] = {col: 0 for col in range(keys)}
        hold_states: list[HoldState] = [HoldState() for _ in range(keys)]

        matched_events: list[dict[str, Any]] = []
        offset_vector: list[Optional[float]] = [None for _ in range(len(notes))]
        delta_list: list[tuple[int, float]] = []
        matched_pairs: list[tuple[int, float, float]] = []
        unmatched_presses: list[tuple[int, float]] = []
        accepted_history: list[dict[str, float]] = []

        press_count = 0

        for now, col, action in input_events:
            _expire_notes(
                now=now,
                notes=notes,
                notes_by_col=notes_by_col,
                tails_by_col=tails_by_col,
                note_start_index=note_start_index,
                tail_start_index=tail_start_index,
                late_note_window=late_note_window,
                late_release_window=release_late_window,
                matched_events=matched_events,
                hold_states=hold_states,
            )

            column_notes = notes_by_col[col]
            while search_start_index[col] < len(column_notes):
                idx = column_notes[search_start_index[col]]
                if notes[idx].time_ms >= now - late_note_window:
                    break
                search_start_index[col] += 1

            if action == "up":
                _apply_release(
                    now=now,
                    col=col,
                    notes=notes,
                    hold_states=hold_states,
                    release_early_window=release_early_window,
                    release_late_window=release_late_window,
                    release_judgement_windows=release_judgement_windows,
                    matched_events=matched_events,
                    offset_vector=offset_vector,
                )
                continue

            press_count += 1
            start_idx = search_start_index[col]
            note_indices = notes_by_col[col]

            if isinstance(note_priority, dict) and "Interlude" in note_priority:
                outcome, target_idx, target_delta = _hitmechanics_interlude(
                    now=now,
                    col=col,
                    note_indices=note_indices,
                    start_index=start_idx,
                    notes=notes,
                    early_window=early_note_window,
                    late_window=late_note_window,
                    cbrush_threshold=cbrush_threshold,
                    accepted_history=accepted_history,
                )
            elif str(note_priority) == "Etterna":
                outcome, target_idx, target_delta = _hitmechanics_etterna(
                    now=now,
                    note_indices=note_indices,
                    start_index=start_idx,
                    notes=notes,
                    early_window=early_note_window,
                    late_window=late_note_window,
                )
            else:
                outcome, target_idx, target_delta = _hitmechanics_osumania(
                    now=now,
                    col=col,
                    note_indices=note_indices,
                    start_index=start_idx,
                    notes=notes,
                    early_window=early_note_window,
                    late_window=late_note_window,
                )

            _apply_press(
                now=now,
                col=col,
                outcome=outcome,
                note_index=target_idx,
                delta=target_delta,
                notes=notes,
                hold_states=hold_states,
                matched_events=matched_events,
                offset_vector=offset_vector,
                delta_list=delta_list,
                matched_pairs=matched_pairs,
                unmatched_presses=unmatched_presses,
                accepted_history=accepted_history,
                judgement_windows=judgement_windows,
                ghost_tap_judgement=ghost_tap_judgement,
            )

        _expire_notes(
            now=float("inf"),
            notes=notes,
            notes_by_col=notes_by_col,
            tails_by_col=tails_by_col,
            note_start_index=note_start_index,
            tail_start_index=tail_start_index,
            late_note_window=late_note_window,
            late_release_window=release_late_window,
            matched_events=matched_events,
            hold_states=hold_states,
        )

        # 结尾仍在 hold 中的列，记一次 drop 以便评分器可感知尾判缺失。
        for col, state in enumerate(hold_states):
            if not state.active or state.tail_index is None:
                continue
            tail = notes[state.tail_index]
            if tail.status == "RELEASE_REQUIRED":
                tail.status = "DROP_HOLD"
                tail.hold_state = "Dropped"
                matched_events.append(
                    _build_event_dict(
                        index=tail.index,
                        time_ms=tail.time_ms,
                        column=tail.column,
                        action="DROP_HOLD",
                        note_kind=tail.note_kind,
                        press_time=tail.press_time,
                        release_time=tail.release_time,
                        delta=None,
                        head_delta=tail.head_delta,
                        tail_delta=tail.tail_delta,
                        hold_state="Dropped",
                        blocked=False,
                        judgement_index=None,
                        notes_map_index=tail.index,
                    )
                )

        unmatched_notes = [
            (note.index, float(note.time_ms))
            for note in notes
            if not note.matched
        ]

        matched_events.sort(
            key=lambda event: (
                float(event["time"]),
                int(event["column"]),
                int(event["index"]),
                str(event["action"]),
            )
        )

        if not has_any_window:
            logger.warning("ruleset 未提供有效 TimingWindows，返回匹配结构但判定窗口可信度较低")

        logger.debug(
            "match_notes_and_presses 完成: "
            f"notes={len(notes)}, presses={press_count}, "
            f"hits={len(delta_list)}, unmatched_presses={len(unmatched_presses)}, "
            f"unmatched_notes={len(unmatched_notes)}, strategy={note_priority}\n"
            f"osr.press_events_chart_float (first 10): {press_events[:10]},\n"
            f"osr.press_events_real_float (first 10): {getattr(osr, 'press_events_real_float', [])[:10]},\n"
            f"osr.replay_data_chart (first 10): {replay_data[:10] if replay_data else None},\n"
            f"osr.replay_data_real (first 10): {getattr(osr, 'replay_data_real', [])[:10] if hasattr(osr, 'replay_data_real') else None},\n"
        )

        return {
            "status": "OK",
            "error": None,
            "matched_events": matched_events,
            "offset_vector": offset_vector,
            "delta_list": [(int(col), float(delta)) for col, delta in delta_list],
            "matched_pairs": [(int(col), float(nt), float(pt)) for col, nt, pt in matched_pairs],
            "unmatched_presses": [(int(col), float(t)) for col, t in unmatched_presses],
            "unmatched_notes": unmatched_notes,
            "note_count": len(notes),
            "press_count": press_count,
            "meta": meta,
        }

    except Exception as exc:
        logger.error(f"match_notes_and_presses 执行失败: {exc}")
        return _empty_result("Error", str(exc), meta)
