from __future__ import annotations

import math

from .windows import Windows
from .events import LaneEvent
from .chart import LaneChart, hand_groups

_MISS = 1
_IGNORE_MISS = 13
_IGNORE_HIT = 14
_COMBO_BREAK = 15
_FORCE_DROP = 50
_LAZER_WEIGHTS = (0, 50, 100, 200, 300, 305)
_SV1_GAME_WEIGHTS = (0, 50, 100, 200, 300, 300)
_SV1_WEIGHTS = (300, 300, 200, 100, 50, 0)


def _accuracy(points: float, judged: int, denominator: int) -> float | None:
    return (points / (denominator * judged)) * 100.0 if judged > 0 else None


def _judge_stable_tap(offset: float, windows: Windows) -> int:
    raw = float(offset)
    if raw >= windows.ok:
        return 6
    error = abs(math.trunc(raw))
    if error <= windows.perfect:
        return 1
    if error <= windows.great:
        return 2
    if error <= windows.good:
        return 3
    if error <= windows.ok:
        return 4
    if error <= windows.meh:
        return 5
    return 6


def _judge_stable_hold(
    start: float,
    end: float,
    head_offset: float,
    tail_offset: float | None,
    dropped: bool,
    windows: Windows,
) -> int:
    press_time = start + math.trunc(head_offset)
    if press_time < start - windows.meh:
        num2 = end - 1.0
    elif press_time >= start:
        num2 = press_time
    else:
        num2 = start + (start - press_time)

    if tail_offset is None or not math.isfinite(tail_offset):
        num3 = end + windows.meh
    else:
        release_time = end + math.trunc(tail_offset)
        num3 = end + windows.meh if release_time > end + windows.meh else release_time

    num4 = abs(num2 - start)
    num5 = abs(num3 - end)
    num6 = num4 + num5
    if num3 < end - windows.miss:
        return 6
    if num3 < end - windows.meh:
        return 5
    if num4 <= windows.perfect * 1.2 and num6 <= windows.perfect * 2.4:
        judgment = 1
    elif num4 <= windows.great * 1.1 and num6 <= windows.great * 2.2:
        judgment = 2
    elif num4 <= windows.good - 2 and num6 <= windows.good * 2:
        judgment = 3
    elif num4 <= windows.ok and num6 <= windows.ok * 2:
        judgment = 4
    else:
        judgment = 5
    if dropped and judgment < 3:
        judgment = 3
    return judgment


class LaneAccumulator:
    """源 ``createAccumulator`` 的 Python 移植（保留完整事件状态机）。"""

    def __init__(
        self,
        chart: LaneChart,
        windows: Windows,
        *,
        score_mode: str = "stable-v1",
        lane_weights: int = 300,
        space_mode: str = "independent",
    ):
        self.chart = chart
        self.windows = windows
        self.score_mode = score_mode
        self.lane_weights = tuple(
            _SV1_GAME_WEIGHTS if lane_weights == 300 else _LAZER_WEIGHTS
        )
        self.lane_weight_max = 300 if lane_weights == 300 else 305
        self.space_mode = space_mode
        self.column_count = chart.column_count
        self.note_count = chart.note_count

        self.game_counts = [0] * (self.column_count * 6)
        self.sv1_counts = [0] * 6
        self.final = bytearray(self.note_count)
        self.broken = bytearray(self.note_count)
        self.head_offset = [math.nan] * self.note_count
        self.tail_offset = [math.nan] * self.note_count
        self.drop_offset = [math.nan] * self.note_count
        self.force_grade = bytearray(self.note_count)
        self.regrabbed = bytearray(self.note_count)
        self.sv1_grade = bytearray(self.note_count)
        self.next_press = [math.nan] * self.column_count
        self.head_result = bytearray(self.note_count)
        self.game_tail = bytearray(self.note_count)
        self.pending = [-1] * self.column_count
        self.cursor = [0] * self.column_count
        self.lane_combo = [0] * self.column_count
        self.lane_max_combo = [0] * self.column_count
        self.hand_combo = [0, 0]
        self.hand_max_combo = [0, 0]
        self.last_tick_time = [-1.0] * self.column_count
        self.combo = 0
        self.max_combo = 0
        self.sv1_combo = 0
        self.sv1_max_combo = 0
        self.game_total = 0
        self.sv1_total = 0
        self.unmatched = 0
        self.finished = False
        self.col_hand = [-1] * self.column_count
        self._rebuild_hand_map()

    def _rebuild_hand_map(self) -> None:
        groups = hand_groups(self.column_count, self.space_mode)
        self.col_hand = [-1] * self.column_count
        left = groups.get("left")
        right = groups.get("right")
        if left is not None:
            for col in range(left[0], left[1]):
                self.col_hand[col] = 0
        if right is not None:
            for col in range(right[0], right[1]):
                self.col_hand[col] = 1

    def reset(self) -> None:
        self.game_counts = [0] * (self.column_count * 6)
        self.sv1_counts = [0] * 6
        self.final = bytearray(self.note_count)
        self.broken = bytearray(self.note_count)
        self.head_offset = [math.nan] * self.note_count
        self.tail_offset = [math.nan] * self.note_count
        self.drop_offset = [math.nan] * self.note_count
        self.force_grade = bytearray(self.note_count)
        self.regrabbed = bytearray(self.note_count)
        self.sv1_grade = bytearray(self.note_count)
        self.next_press = [math.nan] * self.column_count
        self.head_result = bytearray(self.note_count)
        self.game_tail = bytearray(self.note_count)
        self.pending = [-1] * self.column_count
        self.cursor = [0] * self.column_count
        self.lane_combo = [0] * self.column_count
        self.lane_max_combo = [0] * self.column_count
        self.hand_combo = [0, 0]
        self.hand_max_combo = [0, 0]
        self.last_tick_time = [-1.0] * self.column_count
        self.combo = 0
        self.max_combo = 0
        self.sv1_combo = 0
        self.sv1_max_combo = 0
        self.game_total = 0
        self.sv1_total = 0
        self.unmatched = 0
        self.finished = False

    def _register_judgement(self, col: int, success: bool) -> None:
        if not success:
            self.combo = 0
            self.lane_combo[col] = 0
            hand = self.col_hand[col]
            if hand >= 0:
                self.hand_combo[hand] = 0
            return
        self.combo += 1
        self.lane_combo[col] += 1
        if self.combo > self.max_combo:
            self.max_combo = self.combo
        if self.lane_combo[col] > self.lane_max_combo[col]:
            self.lane_max_combo[col] = self.lane_combo[col]
        hand = self.col_hand[col]
        if hand >= 0:
            self.hand_combo[hand] += 1
            if self.hand_combo[hand] > self.hand_max_combo[hand]:
                self.hand_max_combo[hand] = self.hand_combo[hand]

    def _register_sv1_combo(self, success: bool) -> None:
        if not success:
            self.sv1_combo = 0
            return
        self.sv1_combo += 1
        if self.sv1_combo > self.sv1_max_combo:
            self.sv1_max_combo = self.sv1_combo

    def _next_slot(self, col: int) -> int:
        start = int(self.chart.slot_start[col])
        count = int(self.chart.slot_count[col])
        index = self.cursor[col]
        if index >= count:
            return -1
        self.cursor[col] = index + 1
        return start + index

    def _advance_ticks(self, current_time: float) -> None:
        for col in range(self.column_count):
            note = self.pending[col]
            if note < 0 or self.broken[note]:
                continue
            end = float(self.chart.note_ends[note])
            target = min(end, current_time)
            last_tick = self.last_tick_time[col]
            if last_tick >= 0:
                while last_tick + 100.0 <= target:
                    last_tick += 100.0
                    self._register_sv1_combo(True)
                self.last_tick_time[col] = last_tick

    def _finalize(self, note: int) -> None:
        if self.final[note]:
            return
        self.final[note] = 1
        if self.force_grade[note] > 0:
            judgment = int(self.force_grade[note])
        elif math.isfinite(self.head_offset[note]):
            judgment = _judge_stable_hold(
                float(self.chart.note_starts[note]),
                float(self.chart.note_ends[note]),
                float(self.head_offset[note]),
                self.tail_offset[note] if math.isfinite(self.tail_offset[note]) else None,
                bool(self.broken[note]),
                self.windows,
            )
        else:
            judgment = 6
        self.sv1_counts[judgment - 1] += 1
        self.sv1_total += 1
        self.sv1_grade[note] = judgment
        self._register_sv1_combo(judgment != 6)

    def _flush_pending(self, col: int) -> None:
        note = self.pending[col]
        if note < 0:
            return
        self._advance_ticks(float(self.chart.note_ends[note]))
        if not self.final[note]:
            self._finalize(note)
        self.pending[col] = -1
        self.last_tick_time[col] = -1.0

    def apply_event(self, event: LaneEvent) -> None:
        col = int(event.col)
        result = int(event.result)
        offset = float(event.offset)
        if col < 0 or col >= self.column_count or not math.isfinite(offset):
            self.unmatched += 1
            return

        if 1 <= result <= 6:
            if self.score_mode == "stable-native":
                self.game_counts[col * 6 + result - 1] += 1
                self.game_total += 1
                self._register_judgement(col, result != _MISS)
                return

            if self.pending[col] >= 0:
                index = self.cursor[col]
                same_tail = (
                    index < int(self.chart.slot_count[col])
                    and int(self.chart.slot_note[int(self.chart.slot_start[col]) + index])
                    == self.pending[col]
                    and int(self.chart.slot_part[int(self.chart.slot_start[col]) + index])
                    == 1
                )
                if not same_tail:
                    self._flush_pending(col)
            slot = self._next_slot(col)
            if slot < 0:
                self.unmatched += 1
                return
            note = int(self.chart.slot_note[slot])
            part = int(self.chart.slot_part[slot])
            event_offset = offset
            if part == 0 and math.isfinite(self.next_press[col]):
                event_offset = self.next_press[col] - float(self.chart.note_starts[note])
                self.next_press[col] = math.nan
            self.game_counts[col * 6 + result - 1] += 1
            self.game_total += 1
            self._register_judgement(col, result != _MISS)
            if part == 1:
                self.game_tail[note] = 1
                if result == _MISS and abs(event_offset) < 1e-9:
                    self.tail_offset[note] = math.nan
                else:
                    self.tail_offset[note] = event_offset
                release_time = float(self.chart.note_ends[note]) + math.trunc(
                    event_offset
                )
                self._advance_ticks(release_time)
                if event_offset < -self.windows.meh:
                    self.broken[note] = 1
                    self._register_sv1_combo(False)
                return
            if result == _MISS and abs(event_offset) < 1e-9:
                self.head_offset[note] = math.nan
            else:
                self.head_offset[note] = event_offset
            self.head_result[note] = result
            if not bool(self.chart.is_hold[note]):
                judgment = (
                    6
                    if result == _MISS and abs(offset) < 1e-9
                    else _judge_stable_tap(event_offset, self.windows)
                )
                self.sv1_counts[judgment - 1] += 1
                self.sv1_total += 1
                self.sv1_grade[note] = judgment
                self._register_sv1_combo(judgment != 6)
                return
            no_press = result == _MISS and abs(offset) < 1e-9
            self.pending[col] = note
            self.last_tick_time[col] = (
                -1.0
                if no_press
                else float(self.chart.note_starts[note]) + math.trunc(event_offset)
            )
            if self.last_tick_time[col] >= 0:
                self._advance_ticks(
                    float(self.chart.note_starts[note]) + math.trunc(event_offset)
                )
            return

        if result == _FORCE_DROP:
            if self.pending[col] >= 0 and not self.final[self.pending[col]]:
                note = self.pending[col]
                self.tail_offset[note] = offset
                self.force_grade[note] = 4 if abs(self.head_offset[note]) > 30 else 5
                self._finalize(note)
                self.pending[col] = -1
                self.last_tick_time[col] = -1.0
            return

        if result == _COMBO_BREAK:
            self._register_judgement(col, False)
            if self.pending[col] >= 0:
                note = self.pending[col]
                break_time = float(self.chart.note_ends[note]) + math.trunc(offset)
                self._advance_ticks(break_time)
                self.drop_offset[note] = offset
                self.broken[note] = 1
                self._register_sv1_combo(False)
            return

        if result in (_IGNORE_MISS, _IGNORE_HIT):
            if result == _IGNORE_MISS:
                self._register_judgement(col, False)
            if self.pending[col] >= 0 and not self.final[self.pending[col]]:
                note = self.pending[col]
                drop = self.drop_offset[note]
                if result == _IGNORE_HIT:
                    self.regrabbed[note] = 1
                    if math.isfinite(drop) and offset >= drop:
                        self.tail_offset[note] = offset
                        self.broken[note] = 1
                    elif self.game_tail[note] == 0 and not math.isfinite(
                        self.tail_offset[note]
                    ):
                        self.tail_offset[note] = offset
                elif math.isfinite(drop):
                    self.tail_offset[note] = drop
                    if offset > drop + 1:
                        self.next_press[col] = float(self.chart.note_ends[note]) + offset
                elif self.game_tail[note] == 0 and math.isfinite(offset):
                    self.tail_offset[note] = offset
                release_time = float(self.chart.note_ends[note]) + math.trunc(
                    self.tail_offset[note]
                    if math.isfinite(self.tail_offset[note])
                    else offset
                )
                self._advance_ticks(release_time)
                self._finalize(note)
                self.pending[col] = -1
                self.last_tick_time[col] = -1.0
            return

    def apply_events(self, events: list[LaneEvent]) -> None:
        self.reset()
        for event in events:
            self.apply_event(event)

    def finish(self) -> None:
        for col in range(self.column_count):
            self._flush_pending(col)
        self.finished = True

    def no_regrab_drop_notes(self) -> list[int]:
        notes: list[int] = []
        for note in range(self.note_count):
            if (
                math.isfinite(self.drop_offset[note])
                and not self.regrabbed[note]
                and math.isfinite(self.head_offset[note])
                and self.sv1_grade[note] == 6
            ):
                notes.append(note)
        return notes

    def _lane_snapshot(self, col: int) -> dict:
        counts = self.game_counts[col * 6 : col * 6 + 6]
        judged = sum(counts)
        points = sum(count * weight for count, weight in zip(counts, self.lane_weights))
        return {
            "column": col,
            "counts": list(counts),
            "judged": judged,
            "miss": counts[0],
            "points": points,
            "acc": _accuracy(points, judged, self.lane_weight_max),
            "max_combo": self.lane_max_combo[col],
        }

    def _hand_snapshot(
        self, bounds: tuple[int, int] | None, hand_index: int = -1
    ) -> dict | None:
        if bounds is None:
            return None
        counts = [0] * 6
        judged = 0
        points = 0
        miss = 0
        for col in range(bounds[0], bounds[1]):
            lane = self._lane_snapshot(col)
            judged += lane["judged"]
            points += lane["points"]
            miss += lane["miss"]
            for index in range(6):
                counts[index] += lane["counts"][index]
        return {
            "judged": judged,
            "points": points,
            "miss": miss,
            "acc": _accuracy(points, judged, self.lane_weight_max),
            "counts": counts,
            "max_combo": self.hand_max_combo[hand_index] if hand_index >= 0 else 0,
        }

    def snapshot(self) -> dict:
        groups = hand_groups(self.column_count, self.space_mode)
        lanes = [self._lane_snapshot(col) for col in range(self.column_count)]
        total_counts = [0] * 6
        for lane in lanes:
            for index in range(6):
                total_counts[index] += lane["counts"][index]
        total_judged = sum(total_counts)
        total_points = sum(lane["points"] for lane in lanes)
        return {
            "finished": self.finished,
            "spaceMode": self.space_mode,
            "columnCount": self.column_count,
            "lanes": lanes,
            "hands": {
                "left": self._hand_snapshot(groups.get("left"), 0),
                "right": self._hand_snapshot(groups.get("right"), 1),
                "space": self._hand_snapshot(groups.get("space"), -1),
            },
            "gameTotal": self.game_total,
            "counts": total_counts,
            "judged": total_judged,
            "points": total_points,
            "acc": _accuracy(total_points, total_judged, self.lane_weight_max),
            "maxCombo": self.sv1_max_combo,
            "gameMaxCombo": self.max_combo,
            "sv1Total": self.sv1_total,
            "sv1Counts": list(self.sv1_counts),
            "unmatched": self.unmatched,
            "windows": self.windows,
        }
