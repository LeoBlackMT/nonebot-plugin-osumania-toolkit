import numpy as np


def safe_sample_rate(data: dict) -> float:
    """安全获取采样率。

    Args:
        data: 回放数据字典。

    Returns:
        采样率（Hz）。
    """

    fft_info = data.get("fft_analysis")
    if fft_info is not None and fft_info.get("peak_frequency") not in (None, 0):
        return fft_info["peak_frequency"]
    return data.get("sample_rate", 0)


def is_mr_replay(data: dict) -> bool:
    """判断是否为 .mr 转换回放。

    Args:
        data: 回放数据字典。

    Returns:
        是则为 True。
    """

    return data.get("player_name") == "ConvertedFromMalody"


def normalize_histogram(arr: np.ndarray) -> np.ndarray:
    """对直方图做归一化。

    Args:
        arr: 原始直方图数组。

    Returns:
        归一化后的数组。
    """

    arr = arr.astype(float)
    s = arr.sum()
    return (arr / s) if s > 0 else arr


def build_chord_groups(note_times: dict[int, list[float]]) -> list[list[tuple[int, float]]]:
    """将时间近同步物件分组成多押组。

    Args:
        note_times: 按列存储的物件时间。

    Returns:
        多押组列表，每组为 (col, note_time) 列表。
    """

    note_times_flat: list[tuple[int, float]] = []
    for col, times in note_times.items():
        for t in times:
            note_times_flat.append((col, t))

    note_times_flat.sort(key=lambda x: x[1])
    chord_groups: list[list[tuple[int, float]]] = []
    i = 0
    while i < len(note_times_flat):
        group = [note_times_flat[i]]
        j = i + 1
        while j < len(note_times_flat) and abs(note_times_flat[j][1] - note_times_flat[i][1]) < 1:
            group.append(note_times_flat[j])
            j += 1
        if len(group) > 1:
            chord_groups.append(group)
        i = j
    return chord_groups
