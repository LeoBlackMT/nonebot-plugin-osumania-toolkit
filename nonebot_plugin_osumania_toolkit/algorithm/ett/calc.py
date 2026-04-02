from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

OUTPUT_SKILLSETS = [
    "Stream",
    "Jumpstream",
    "Handstream",
    "Stamina",
    "JackSpeed",
    "Chordjack",
    "Technical",
]

OFFICIAL_RUNNER_ENV = "ETT_MINACALC_RUNNER"
OFFICIAL_RUNNER_CANDIDATES = (
    "official_minacalc_runner",
    "official_minacalc_runner.exe",
)


class OfficialRunnerError(RuntimeError):
    pass


ROW_COUNT_ASSERT_SIGNATURE = (
    "hand_counts[left_hand] + nri.hand_counts[right_hand] == nri.row_count"
)


def _is_row_count_assertion_error(message: str) -> bool:
    msg = str(message or "")
    if ROW_COUNT_ASSERT_SIGNATURE in msg:
        return True

    lower = msg.lower()
    return (
        "hand_counts" in lower
        and "row_count" in lower
        and (
            "assert" in lower
            or "ulbuacolytes.h" in lower
            or "minacalc" in lower
        )
    )


def _ordered_runner_candidates() -> tuple[str, ...]:
    is_windows = platform.system().lower().startswith("win")
    if is_windows:
        return ("official_minacalc_runner.exe", "official_minacalc_runner")
    return ("official_minacalc_runner", "official_minacalc_runner.exe")


def _resolve_official_runner_path() -> Path:
    env_override = os.environ.get(OFFICIAL_RUNNER_ENV, "").strip()
    if env_override:
        p = Path(env_override).expanduser()
        if p.exists():
            return p
        raise FileNotFoundError(
            f"环境变量 {OFFICIAL_RUNNER_ENV} 指向的文件不存在: {p}"
        )

    base = Path(__file__).resolve().parent
    for name in _ordered_runner_candidates():
        candidate = base / name
        if candidate.exists():
            if not platform.system().lower().startswith("win") and not os.access(candidate, os.X_OK):
                continue
            return candidate

    expected = ", ".join(str(base / n) for n in OFFICIAL_RUNNER_CANDIDATES)
    raise FileNotFoundError(
        "未找到 official_minacalc_runner。"
        f"请设置 {OFFICIAL_RUNNER_ENV} 或将 runner 放到目录: {expected}"
    )


def _build_noteinfo_rows(
    osu_obj,
    keycount: int,
    lane_mapper: Optional[Callable[[int], Optional[int]]] = None,
    dropped_lanes: Optional[Set[int]] = None,
) -> List[Tuple[int, float]]:
    if int(keycount) <= 0:
        return []

    lane_max = int(keycount) - 1
    drop_set = dropped_lanes or set()
    rows_by_time: Dict[int, int] = {}

    for col, st in zip(osu_obj.columns, osu_obj.note_starts):
        lane = int(col)
        if lane < 0:
            lane = 0
        elif lane > lane_max:
            lane = lane_max

        if lane in drop_set:
            continue

        if lane_mapper is not None:
            mapped = lane_mapper(lane)
            if mapped is None:
                continue
            lane = int(mapped)

        if lane < 0:
            lane = 0
        elif lane > lane_max:
            lane = lane_max

        t_ms = int(st)
        rows_by_time[t_ms] = rows_by_time.get(t_ms, 0) | (1 << lane)

    out: List[Tuple[int, float]] = []
    for t_ms in sorted(rows_by_time.keys()):
        out.append((rows_by_time[t_ms], float(t_ms) / 1000.0))
    return out


def _parse_runner_stdout(stdout: str) -> Dict[str, float]:
    vals = stdout.strip().split()
    if len(vals) < 8:
        raise OfficialRunnerError(
            f"Runner 输出少于 8 个值: '{stdout.strip()}'"
        )

    try:
        nums = [float(v) for v in vals[:8]]
    except ValueError as ex:
        raise OfficialRunnerError(
            f"Runner 输出包含非浮点值: '{stdout.strip()}'"
        ) from ex

    return {
        "Overall": nums[0],
        "Stream": nums[1],
        "Jumpstream": nums[2],
        "Handstream": nums[3],
        "Stamina": nums[4],
        "JackSpeed": nums[5],
        "Chordjack": nums[6],
        "Technical": nums[7],
    }


def _build_payload(
    keycount: int,
    music_rate: float,
    score_goal: float,
    rows: List[Tuple[int, float]],
) -> str:
    payload_lines = [
        f"{int(keycount)} {float(music_rate):.8f} {float(score_goal):.8f} {len(rows)}"
    ]
    payload_lines.extend(f"{mask} {row_time:.6f}" for mask, row_time in rows)
    return "\n".join(payload_lines) + "\n"


def _run_runner(runner_path: Path, payload: str) -> str:
    try:
        proc = subprocess.run(
            [str(runner_path)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except OSError as ex:
        raise OfficialRunnerError(f"执行 runner 失败 '{runner_path}': {ex}") from ex

    if proc.returncode != 0:
        stderr_msg = proc.stderr.strip() or "<empty stderr>"
        stdout_msg = proc.stdout.strip() or "<empty stdout>"
        raise OfficialRunnerError(
            "official runner 执行失败: "
            f"exit_code={proc.returncode}, stderr={stderr_msg}, stdout={stdout_msg}"
        )

    return proc.stdout


def _map_7k_to_6k(lane: int) -> int:
    # Merge center lane into left-middle lane, shift right side by -1.
    if lane <= 2:
        return lane
    if lane == 3:
        return 2
    return lane - 1


def compute_difficulties(
    osu_obj,
    music_rate: float = 1.0,
    keycount: int = 7,
    score_goal: float = 0.93,
) -> Dict[str, float]:
    runner_path = _resolve_official_runner_path()
    normalized_keycount = int(keycount)
    rows = _build_noteinfo_rows(osu_obj, normalized_keycount)

    if len(rows) <= 1:
        return {k: 0.0 for k in OUTPUT_SKILLSETS + ["Overall"]}

    try:
        payload = _build_payload(normalized_keycount, music_rate, score_goal, rows)
        stdout = _run_runner(runner_path, payload)
        return _parse_runner_stdout(stdout)
    except OfficialRunnerError as err:
        # Some 7K files trigger assertion in MinaCalc hand-count checker.
        # Fallback strategy: retry with safe row transforms instead of hard-failing.
        if normalized_keycount == 7 and _is_row_count_assertion_error(str(err)):
            # Retry 1: drop center lane notes but keep 7K mode.
            rows_without_center = _build_noteinfo_rows(
                osu_obj,
                normalized_keycount,
                dropped_lanes={3},
            )
            if len(rows_without_center) > 1:
                try:
                    payload = _build_payload(normalized_keycount, music_rate, score_goal, rows_without_center)
                    stdout = _run_runner(runner_path, payload)
                    return _parse_runner_stdout(stdout)
                except OfficialRunnerError:
                    pass

            # Retry 2: project 7K rows into stable 6K layout.
            rows_projected_6k = _build_noteinfo_rows(
                osu_obj,
                keycount=6,
                lane_mapper=_map_7k_to_6k,
            )
            if len(rows_projected_6k) > 1:
                payload = _build_payload(6, music_rate, score_goal, rows_projected_6k)
                stdout = _run_runner(runner_path, payload)
                return _parse_runner_stdout(stdout)

        raise
