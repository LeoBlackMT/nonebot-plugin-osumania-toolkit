"""Note-press matching engine — ported from YAVSRG Interlude Events.fs / HitMechanics.fs."""
from __future__ import annotations

from collections import defaultdict
from typing import Optional, Any

from nonebot.log import logger

from ...parser.osr_file_parser import osr_file
from ...parser.osu_file_parser import NOTE_HOLD_HEAD, NOTE_HOLD_TAIL, NOTE_NORMAL, osu_file
from ...parser.ruleset_file_parser import ruleset_file

from .helpers import (
    BLOCKED,
    FOUND,
    HIT_ACCEPTED,
    HIT_HOLD_REQUIRED,
    HIT_REQUIRED,
    H_DROPPED,
    H_HOLDING,
    H_MISSED_HEAD_DROPPED,
    H_MISSED_HEAD_REGRABBED,
    H_NOTHING,
    H_REGRABBED,
    NOTFOUND,
    NOTE_KIND_ANY,
    RELEASE_ACCEPTED,
    RELEASE_REQUIRED,
    HoldState,
    NoteEntry,
    _build_hitflagdata,
    _determine_speed_factor,
    _empty_result,
    _first_tail_at_or_after,
    _hitmechanics_etterna,
    _hitmechanics_interlude,
    _hitmechanics_osumania,
    _infer_judgement_index,
    _is_number,
    _legacy_event_dict,
    _note_windows,
    _release_judgement_windows,
    _release_windows,
    _retime_frames,
    f32,
)

MIRROR_MOD = 1 << 30  # osu! Mirror


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
    按 interlude Events.fs 语义对谱面 note 与回放按键进行确定性匹配。

    - 帧时间线从 .osr 原始 LZMA 载荷按 decode 语义重建（f32 累加、
      仅状态变化帧、首音符归零）。
    - rate 由速度模组推导（DT/NC=1.5、HT=0.75），窗口 ×rate、存储 delta ÷rate。
    - 命中检测按 NotePriority 逐字复刻（cbrush / earliest / closest）。
    - 输出同时提供 F# 等价事件流 events_f 与旧版 schema 的 matched_events。
    """
    meta = {
        "rate_used": float(rate),
        "speed_factor": 1.0,
        "scale_applied": False,
        "chart_time_offset": 0.0,
        "note_priority": "OsuMania",
        "algorithm_version": "interlude_v2",
    }

    try:
        if osu is None or osr is None or ruleset is None:
            return _empty_result("InvalidInput", "osu/osr/ruleset 不能为空", meta)

        if str(getattr(osu, "GameMode", "3")) not in {"3", "None", ""} and getattr(osu, "status", "") == "NotMania":
            return _empty_result("NotMania", "仅支持 mania 谱面", meta)

        if not isinstance(getattr(ruleset, "raw_data", None), dict):
            return _empty_result("InvalidInput", "ruleset.raw_data 缺失或无效", meta)

        mirror = (int(getattr(osr, "mod", 0) or 0) & MIRROR_MOD) != 0
        notes, notes_by_col, tails_by_col, keys, row_times = _build_hitflagdata(osu, mirror=mirror)
        if not notes or keys <= 0:
            return _empty_result("InvalidInput", "谱面 note_rows 为空或列数无效", meta)

        ruleset_data = ruleset.raw_data
        early_note_raw, late_note_raw, judgement_windows, has_any_window = _note_windows(ruleset_data)
        release_early_raw, release_late_raw = _release_windows(ruleset_data, early_note_raw, late_note_raw)
        release_judgement_windows = _release_judgement_windows(ruleset_data, judgement_windows)

        speed_factor = _determine_speed_factor(osr)
        effective_rate = float(rate) if abs(float(rate) - 1.0) > 1e-9 else speed_factor
        rate_f = f32(effective_rate)
        meta["rate_used"] = float(effective_rate)
        meta["speed_factor"] = float(speed_factor)

        early_note_s = f32(early_note_raw * rate_f)
        late_note_s = f32(late_note_raw * rate_f)
        early_release_s = f32(release_early_raw * rate_f)
        late_release_s = f32(release_late_raw * rate_f)
        early_s = min(early_release_s, early_note_s)
        late_s = max(late_release_s, late_note_s)

        note_priority = (
            ((ruleset_data.get("HitMechanics") or {}).get("NotePriority"))
            if isinstance(ruleset_data.get("HitMechanics"), dict)
            else "OsuMania"
        )
        meta["note_priority"] = note_priority

        cbrush_threshold_raw = 0.0
        if isinstance(note_priority, dict) and _is_number(note_priority.get("Interlude")):
            cbrush_threshold_raw = float(note_priority["Interlude"])
        cbrush_s = f32(cbrush_threshold_raw * rate_f)

        first_note_f = f32(float(notes[0].time_ms))
        frames = _retime_frames(osr, notes[0].time_ms, 1.0)
        if not frames:
            # 缺少原始载荷时的兜底：从绝对帧时间线重建相对帧（仅状态变化帧）。
            replay_chart = getattr(osr, "replay_data_chart", None) or []
            prev = 256
            for t_abs, mask in replay_chart:
                mask = int(mask)
                if mask != prev:
                    frames.append((f32(f32(float(t_abs)) - first_note_f), mask))
                    prev = mask

        # HitFlagData 初始化：普通/头预置 late note 窗口，尾预置 late release 窗口。
        for note in notes:
            if note.note_kind == NOTE_HOLD_TAIL:
                note.delta = f32(release_late_raw)
            else:
                note.delta = f32(late_note_raw)

        rows_notes: dict[int, list[int]] = defaultdict(list)
        for note in notes:
            rows_notes[note.row_index].append(note.index)

        hold_states: list[HoldState] = [HoldState() for _ in range(keys)]
        search_ptr: dict[int, int] = {col: 0 for col in range(keys)}
        expired_row_ptr = 0
        current_pressed = 0

        matched_events: list[dict[str, Any]] = []
        events_f: list[dict[str, Any]] = []
        offset_vector: list[Optional[float]] = [None for _ in range(len(notes))]
        delta_list: list[tuple[int, float]] = []
        matched_pairs: list[tuple[int, float, float]] = []
        unmatched_presses: list[tuple[int, float]] = []
        press_count = 0

        def emit_f(*, index: int, time: float, column: int, action: str, delta: Optional[float], **extra: Any) -> None:
            event: dict[str, Any] = {
                "index": int(index),
                "time": float(time),
                "column": int(column),
                "action": action,
                "delta": None if delta is None else float(delta),
            }
            event.update(extra)
            events_f.append(event)

        def emit_legacy(
            *,
            index: int,
            time_ms: float,
            column: int,
            action: str,
            note_kind: int,
            press_time: Optional[float],
            release_time: Optional[float],
            delta: Optional[float],
            head_delta: Optional[float],
            tail_delta: Optional[float],
            hold_state: Optional[str],
            blocked: bool,
            judgement_index: Optional[int],
            notes_map_index: Optional[int],
        ) -> None:
            matched_events.append(
                _legacy_event_dict(
                    index=index,
                    time_ms=time_ms,
                    column=column,
                    action=action,
                    note_kind=note_kind,
                    press_time=press_time,
                    release_time=release_time,
                    delta=delta,
                    head_delta=head_delta,
                    tail_delta=tail_delta,
                    hold_state=hold_state,
                    blocked=blocked,
                    judgement_index=judgement_index,
                    notes_map_index=notes_map_index,
                )
            )

        def expire(ct: float) -> None:
            """MissUnhitExpiredNotes (Events.fs) verbatim."""
            nonlocal expired_row_ptr
            now = f32(first_note_f + f32(ct)) if ct != float("inf") else float("inf")
            end = f32(now - late_s) if now != float("inf") else float("inf")

            while expired_row_ptr < len(row_times) and row_times[expired_row_ptr] < end:
                for note_idx in rows_notes.get(expired_row_ptr, []):
                    note = notes[note_idx]
                    k = note.column
                    ev_time = f32(f32(f32(note.time_ms) - first_note_f) + f32(late_s))

                    if note.status == HIT_REQUIRED:
                        note.status = HIT_ACCEPTED
                        note.matched = True
                        note.hold_state = "MissedHead" if note.note_kind == NOTE_HOLD_HEAD else None
                        emit_f(index=note.row_index, time=ev_time, column=k, action="HIT", delta=note.delta, missed=True)
                        emit_legacy(
                            index=note.index,
                            time_ms=ev_time,
                            column=k,
                            action="MISS",
                            note_kind=note.note_kind,
                            press_time=None,
                            release_time=None,
                            delta=None,
                            head_delta=None,
                            tail_delta=None,
                            hold_state=note.hold_state,
                            blocked=False,
                            judgement_index=None,
                            notes_map_index=note.index,
                        )
                    elif note.status == HIT_HOLD_REQUIRED:
                        hold_states[k] = HoldState(H_MISSED_HEAD_DROPPED, note.index)
                        note.status = HIT_ACCEPTED
                        note.matched = True
                        note.hold_state = "MissedHead"
                        emit_f(index=note.row_index, time=ev_time, column=k, action="HOLD", delta=note.delta, missed=True)
                        emit_legacy(
                            index=note.index,
                            time_ms=ev_time,
                            column=k,
                            action="MISS",
                            note_kind=note.note_kind,
                            press_time=None,
                            release_time=None,
                            delta=None,
                            head_delta=None,
                            tail_delta=None,
                            hold_state="MissedHead",
                            blocked=False,
                            judgement_index=None,
                            notes_map_index=note.index,
                        )
                    elif note.status == RELEASE_REQUIRED:
                        state = hold_states[k]
                        overhold = (
                            state.state in (H_REGRABBED, H_HOLDING, H_MISSED_HEAD_REGRABBED)
                            and (current_pressed & (1 << k)) != 0
                        )
                        dropped = state.IsDropped
                        missed_head = state.MissedHead
                        head_delta = (
                            notes[state.head_index].head_delta or notes[state.head_index].delta
                            if state.head_index is not None
                            else None
                        )
                        note.status = RELEASE_ACCEPTED
                        note.matched = True
                        note.release_time = now if now != float("inf") else note.time_ms
                        note.tail_delta = note.delta
                        hold_states[k] = HoldState()
                        emit_f(
                            index=note.row_index,
                            time=ev_time,
                            column=k,
                            action="RELEASE",
                            delta=note.delta,
                            missed=True,
                            overhold=overhold,
                            dropped=dropped,
                            missed_head=missed_head,
                        )
                        emit_legacy(
                            index=note.index,
                            time_ms=ev_time,
                            column=k,
                            action="RELEASE",
                            note_kind=note.note_kind,
                            press_time=None,
                            release_time=note.release_time,
                            delta=note.delta,
                            head_delta=head_delta,
                            tail_delta=note.delta,
                            hold_state="MissedHead" if missed_head else None,
                            blocked=False,
                            judgement_index=None,
                            notes_map_index=note.index,
                        )
                expired_row_ptr += 1

        def kill_existing_hold(ct: float, k: int) -> None:
            """KillExistingHold (Events.fs) verbatim."""
            state = hold_states[k]
            if state.state == H_NOTHING or state.head_index is None:
                return

            tails = tails_by_col[k]
            i = _first_tail_at_or_after(tails, notes, state.head_index)
            head = notes[state.head_index]
            while i < len(tails):
                tail = notes[tails[i]]
                if tail.status == RELEASE_ACCEPTED:
                    i = len(tails)
                elif tail.status == RELEASE_REQUIRED:
                    tail.status = RELEASE_ACCEPTED
                    tail.matched = True
                    hold_states[k] = HoldState()
                    head_delta = head.head_delta if head.head_delta is not None else head.delta
                    emit_f(
                        index=tail.row_index,
                        time=ct,
                        column=k,
                        action="RELEASE",
                        delta=f32(release_late_raw),
                        missed=True,
                        overhold=False,
                        dropped=True,
                        missed_head=state.MissedHead,
                    )
                    emit_legacy(
                        index=tail.index,
                        time_ms=ct,
                        column=k,
                        action="RELEASE",
                        note_kind=tail.note_kind,
                        press_time=None,
                        release_time=None,
                        delta=f32(release_late_raw),
                        head_delta=head_delta,
                        tail_delta=f32(release_late_raw),
                        hold_state="Dropped",
                        blocked=False,
                        judgement_index=None,
                        notes_map_index=tail.index,
                    )
                    i = len(tails)
                i += 1

        def key_down(ct: float, k: int) -> None:
            nonlocal press_count
            expire(ct)
            now = f32(first_note_f + f32(ct))
            press_count += 1

            column_notes = notes_by_col[k]
            while search_ptr[k] < len(column_notes):
                idx = column_notes[search_ptr[k]]
                if notes[idx].time_ms >= now - late_note_s:
                    break
                search_ptr[k] += 1

            if isinstance(note_priority, dict) and "Interlude" in note_priority:
                outcome, target_idx, target_delta = _hitmechanics_interlude(
                    now=now,
                    col=k,
                    note_indices=column_notes,
                    start_index=search_ptr[k],
                    notes=notes,
                    early_window=early_note_s,
                    late_window=late_note_s,
                    cbrush_window=cbrush_s,
                    cbrush_raw=cbrush_threshold_raw,
                )
            elif str(note_priority) == "Etterna":
                outcome, target_idx, target_delta = _hitmechanics_etterna(
                    now=now,
                    note_indices=column_notes,
                    start_index=search_ptr[k],
                    notes=notes,
                    early_window=early_note_s,
                    late_window=late_note_s,
                )
            else:
                outcome, target_idx, target_delta = _hitmechanics_osumania(
                    now=now,
                    note_indices=column_notes,
                    start_index=search_ptr[k],
                    notes=notes,
                    early_window=early_note_s,
                    late_window=late_note_s,
                )

            if outcome == BLOCKED:
                unmatched_presses.append((k, float(now)))
                return

            if outcome == FOUND and target_idx is not None and target_delta is not None:
                kill_existing_hold(ct, k)
                note = notes[target_idx]
                is_hold = note.status == HIT_HOLD_REQUIRED
                note.status = HIT_ACCEPTED
                note.matched = True
                note.press_time = float(now)
                delta_gametime = f32(f32(target_delta) / rate_f)
                note.delta = delta_gametime
                if is_hold:
                    note.head_delta = delta_gametime
                    note.hold_state = "Holding"
                    hold_states[k] = HoldState(H_HOLDING, note.index)
                judgement = _infer_judgement_index(delta_gametime, judgement_windows)
                note.judgement_index = judgement
                offset_vector[note.index] = delta_gametime
                delta_list.append((k, delta_gametime))
                matched_pairs.append((k, float(note.time_ms), float(now)))

                action = "HOLD" if is_hold else "HIT"
                legacy_action = "HOLD_HEAD" if is_hold else "HIT"
                emit_f(index=note.row_index, time=ct, column=k, action=action, delta=delta_gametime, missed=False)
                emit_legacy(
                    index=note.index,
                    time_ms=ct,
                    column=k,
                    action=legacy_action,
                    note_kind=note.note_kind,
                    press_time=float(now),
                    release_time=None,
                    delta=delta_gametime,
                    head_delta=note.head_delta if is_hold else None,
                    tail_delta=None,
                    hold_state=note.hold_state,
                    blocked=False,
                    judgement_index=judgement,
                    notes_map_index=note.index,
                )
                return

            # NOTFOUND
            unmatched_presses.append((k, float(now)))
            state = hold_states[k]
            if state.state == H_MISSED_HEAD_DROPPED and state.head_index is not None:
                head = notes[state.head_index]
                hold_states[k] = HoldState(H_MISSED_HEAD_REGRABBED, state.head_index)
                emit_f(index=head.row_index, time=ct, column=k, action="REGRAB_HOLD", delta=None)
                emit_legacy(
                    index=head.index,
                    time_ms=ct,
                    column=k,
                    action="REGRAB_HOLD",
                    note_kind=head.note_kind,
                    press_time=None,
                    release_time=None,
                    delta=None,
                    head_delta=head.head_delta,
                    tail_delta=None,
                    hold_state="MissedHead",
                    blocked=False,
                    judgement_index=None,
                    notes_map_index=head.index,
                )
            elif state.state == H_DROPPED and state.head_index is not None:
                head = notes[state.head_index]
                hold_states[k] = HoldState(H_REGRABBED, state.head_index)
                emit_f(index=head.row_index, time=ct, column=k, action="REGRAB_HOLD", delta=None)
                emit_legacy(
                    index=head.index,
                    time_ms=ct,
                    column=k,
                    action="REGRAB_HOLD",
                    note_kind=head.note_kind,
                    press_time=None,
                    release_time=None,
                    delta=None,
                    head_delta=head.head_delta,
                    tail_delta=None,
                    hold_state="Dropped",
                    blocked=False,
                    judgement_index=None,
                    notes_map_index=head.index,
                )
            elif state.state == H_NOTHING and ct > 0.0:
                emit_f(index=expired_row_ptr, time=ct, column=k, action="GHOST_TAP", delta=None)
                ghost_tap_judgement: Optional[int] = None
                hit_mechanics = ruleset_data.get("HitMechanics") if isinstance(ruleset_data.get("HitMechanics"), dict) else {}
                ghost_raw = hit_mechanics.get("GhostTapJudgement") if isinstance(hit_mechanics, dict) else None
                if isinstance(ghost_raw, int):
                    ghost_tap_judgement = ghost_raw
                emit_legacy(
                    index=-1,
                    time_ms=ct,
                    column=k,
                    action="GHOST_TAP",
                    note_kind=NOTE_KIND_ANY,
                    press_time=float(now),
                    release_time=None,
                    delta=None,
                    head_delta=None,
                    tail_delta=None,
                    hold_state=None,
                    blocked=False,
                    judgement_index=ghost_tap_judgement,
                    notes_map_index=None,
                )

        def key_up(ct: float, k: int) -> None:
            """HandleKeyUp (Events.fs) verbatim."""
            expire(ct)
            state = hold_states[k]
            if state.state not in (H_HOLDING, H_REGRABBED, H_MISSED_HEAD_REGRABBED) or state.head_index is None:
                return

            now = f32(first_note_f + f32(ct))
            head = notes[state.head_index]
            tails = tails_by_col[k]
            start = _first_tail_at_or_after(tails, notes, state.head_index)

            found = -1
            fdelta = 0.0
            i = start
            while i < len(tails):
                tail = notes[tails[i]]
                if tail.time_ms > f32(now - early_s):
                    break
                if tail.status == RELEASE_ACCEPTED:
                    i = len(tails)
                elif tail.status == RELEASE_REQUIRED:
                    found = tails[i]
                    fdelta = f32(now - f32(tail.time_ms))
                    i = len(tails)
                i += 1

            if found >= 0 and fdelta >= f32(early_release_s):
                tail = notes[found]
                tail.status = RELEASE_ACCEPTED
                tail.matched = True
                tail.release_time = float(now)
                tail.press_time = head.press_time
                overhold = fdelta > f32(late_release_s)
                if overhold:
                    release_delta = tail.delta
                else:
                    tail.delta = f32(fdelta / rate_f)
                    release_delta = tail.delta
                tail.tail_delta = release_delta
                head.release_time = float(now)
                head.tail_delta = release_delta
                head.hold_state = "Released"
                judgement = _infer_judgement_index(release_delta, release_judgement_windows)
                tail.judgement_index = judgement
                offset_vector[tail.index] = release_delta
                hold_states[k] = HoldState()

                emit_f(
                    index=tail.row_index,
                    time=ct,
                    column=k,
                    action="RELEASE",
                    delta=release_delta,
                    missed=overhold,
                    overhold=overhold,
                    dropped=state.IsDropped,
                    missed_head=state.MissedHead,
                )
                emit_legacy(
                    index=tail.index,
                    time_ms=ct,
                    column=k,
                    action="RELEASE",
                    note_kind=tail.note_kind,
                    press_time=tail.press_time,
                    release_time=float(now),
                    delta=release_delta,
                    head_delta=tail.head_delta,
                    tail_delta=release_delta,
                    hold_state="Released",
                    blocked=False,
                    judgement_index=judgement,
                    notes_map_index=tail.index,
                )
            else:
                if state.state in (H_HOLDING, H_REGRABBED):
                    hold_states[k] = HoldState(H_DROPPED, state.head_index)
                else:
                    hold_states[k] = HoldState(H_MISSED_HEAD_DROPPED, state.head_index)
                head.hold_state = "Dropped"
                emit_f(index=head.row_index, time=ct, column=k, action="DROP_HOLD", delta=None)
                tail = notes[head.tail_index] if head.tail_index is not None else head
                emit_legacy(
                    index=tail.index,
                    time_ms=ct,
                    column=k,
                    action="DROP_HOLD",
                    note_kind=tail.note_kind,
                    press_time=head.press_time,
                    release_time=float(now),
                    delta=None,
                    head_delta=head.head_delta,
                    tail_delta=fdelta if found >= 0 else None,
                    hold_state="Dropped",
                    blocked=False,
                    judgement_index=None,
                    notes_map_index=tail.index,
                )

        for ct, mask in frames:
            changed = current_pressed ^ mask
            if changed:
                for k in range(keys):
                    bit = 1 << k
                    if (changed & bit) == 0:
                        continue
                    prev_down = (current_pressed & bit) != 0
                    now_down = (mask & bit) != 0
                    if prev_down and not now_down:
                        key_up(ct, k)
                    elif now_down and not prev_down:
                        key_down(ct, k)
            current_pressed = mask

        expire(float("inf"))

        unmatched_notes = [
            (note.index, float(note.time_ms))
            for note in notes
            if not note.matched
        ]

        if not has_any_window:
            logger.warning("ruleset 未提供有效 TimingWindows，返回匹配结构但判定窗口可信度较低")

        return {
            "status": "OK",
            "error": None,
            "matched_events": matched_events,
            "events_f": events_f,
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