import os
import struct
import lzma
import datetime
import numpy as np
from collections import Counter
from nonebot.log import logger

# ---------- 辅助函数 ----------
def read_uleb128(data, offset):
    """从字节流中读取ULEB128编码的整数，返回(值, 新偏移)"""
    result = 0
    shift = 0
    while True:
        b = data[offset]
        offset += 1
        result |= (b & 0x7F) << shift
        if (b & 0x80) == 0:
            break
        shift += 7
    return result, offset

def read_string(data, offset):
    """读取osu!专用变长字符串，返回(字符串, 新偏移)"""
    if offset >= len(data):
        return "", offset
    flag = data[offset]
    offset += 1
    if flag == 0x00:
        return "", offset
    elif flag == 0x0B:
        length, offset = read_uleb128(data, offset)
        if offset + length > len(data):
            return "", offset
        s = data[offset:offset+length].decode('utf-8')
        offset += length
        return s, offset
    else:
        # 无效标志，返回空
        return "", offset

class ReplayEvent:
    """模拟osrparse的事件对象，仅包含time_delta和keys"""
    def __init__(self, time_delta, keys):
        self.time_delta = time_delta
        self.keys = keys

def findkey(x=0):
    """将按键掩码转换为18位二进制数组"""
    keyset = [0] * 18
    a, keyset[0] = x // 2, x % 2
    j = 1
    while a != 0:
        a, keyset[j] = a // 2, a % 2
        j += 1
    return np.array(keyset)

class osr_file:
    def __init__(self, file_path):
        self.file_path = file_path
        self.status = "init"

        # 读取整个文件
        with open(file_path, 'rb') as f:
            data = f.read()

        offset = 0
        # 游戏模式 (1 byte)
        if offset >= len(data):
            self.status = "ParseError"
            return
        self.game_mode = data[offset]
        offset += 1
        if self.game_mode != 3:
            self.status = "NotMania"
            return

        # 游戏版本 (4 bytes, int)
        if offset + 4 > len(data):
            self.status = "ParseError"
            return
        self.game_version = struct.unpack('<i', data[offset:offset+4])[0]
        offset += 4

        # 谱面hash
        self.beatmap_hash, offset = read_string(data, offset)
        # 玩家名
        self.player_name, offset = read_string(data, offset)
        # 回放hash
        self.replay_hash, offset = read_string(data, offset)

        # 统计信息 (6个short + 1个int + 1个short + 1个byte)
        if offset + 19 > len(data):
            self.status = "ParseError"
            return
        self.number_300s = struct.unpack('<h', data[offset:offset+2])[0]
        offset += 2
        self.number_100s = struct.unpack('<h', data[offset:offset+2])[0]
        offset += 2
        self.number_50s = struct.unpack('<h', data[offset:offset+2])[0]
        offset += 2
        self.gekis = struct.unpack('<h', data[offset:offset+2])[0]
        offset += 2
        self.katus = struct.unpack('<h', data[offset:offset+2])[0]
        offset += 2
        self.misses = struct.unpack('<h', data[offset:offset+2])[0]
        offset += 2
        self.score = struct.unpack('<i', data[offset:offset+4])[0]
        offset += 4
        self.max_combo = struct.unpack('<h', data[offset:offset+2])[0]
        offset += 2
        self.is_perfect_combo = data[offset] != 0
        offset += 1

        # mod组合 (4 bytes)
        if offset + 4 > len(data):
            self.status = "ParseError"
            return
        self.mod = struct.unpack('<i', data[offset:offset+4])[0]
        offset += 4

        # HP字符串
        self.life_bar_graph, offset = read_string(data, offset)

        # 时间戳 (8 bytes, ticks)
        if offset + 8 > len(data):
            self.status = "ParseError"
            return
        ticks = struct.unpack('<q', data[offset:offset+8])[0]
        offset += 8
        # Windows ticks: 从0001-01-01开始的100ns间隔
        self.timestamp = datetime.datetime.min + datetime.timedelta(microseconds=ticks/10)

        # 压缩数据长度
        if offset + 4 > len(data):
            self.status = "ParseError"
            return
        replay_data_length = struct.unpack('<i', data[offset:offset+4])[0]
        offset += 4

        # 压缩数据
        if offset + replay_data_length > len(data):
            self.status = "ParseError"
            return
        compressed_data = data[offset:offset+replay_data_length]
        self.compressed_data = compressed_data

        # 在线成绩ID (8 bytes)
        if offset + 8 > len(data):
            # 有些老版本没有？尝试读取，如果不够则忽略
            self.replay_id = 0
        else:
            self.replay_id = struct.unpack('<q', data[offset:offset+8])[0]
            offset += 8

        # 附加模组信息 (Target Practice等) 暂时忽略
        self.extra_mod_data = None

        # 初始化派生数据
        self.play_data = []          # 将在process中填充
        self.pressset = [[] for _ in range(18)]
        self.intervals = []
        self.press_times = []
        self.press_events = []
        self.sample_rate = float('inf')
        self.acc = 0.0
        self.ratio = 0.0
        self.judge = {
            "320": self.gekis,
            "300": self.number_300s,
            "200": self.katus,
            "100": self.number_100s,
            "50": self.number_50s,
            "0": self.misses,
        }
        totObj = self.gekis + self.number_300s + self.number_100s + self.number_50s + self.misses + self.katus
        if totObj > 0:
            self.acc = ((self.gekis + self.number_300s) * 300 + self.katus * 200 +
                        self.number_100s * 100 + self.number_50s * 50) / (totObj * 300) * 100
        self.ratio = self.gekis / self.number_300s if self.number_300s > 0 else 0

        # 如果之前状态正常，则继续，否则标记
        if self.status == "init" and self.game_mode == 3:
            self.status = "OK"
        else:
            self.status = "ParseError" if self.status != "NotMania" else "NotMania"

    def process(self):
        """解压LZMA数据并处理事件"""
        if self.status not in ["OK", "init"]:
            return

        try:
            decompressed = lzma.decompress(self.compressed_data).decode('ascii')
        except Exception as e:
            logger.error(f"LZMA解压失败: {e}")
            self.status = "ParseError"
            return

        frames = decompressed.split(',')
        pressed_start = {}
        current_time = 0
        onset = np.zeros(18)
        timeset = np.zeros(18)

        for frame in frames:
            if not frame:
                continue
            parts = frame.split('|')
            if len(parts) < 4:
                continue
            w = int(parts[0])
            x_val = float(parts[1])
            if w == -12345:
                # 种子帧，跳过
                continue
            current_time += w
            self.intervals.append(w)
            keys_bitmask = int(x_val)

            # 记录原始事件
            self.play_data.append(ReplayEvent(w, keys_bitmask))

            r_onset = findkey(keys_bitmask)

            # 检测新按下的键
            for k, l in enumerate(r_onset):
                if onset[k] == 0 and l == 1:
                    self.press_times.append(current_time)
                    self.press_events.append((k, current_time))

            timeset += onset * w
            for k, l in enumerate(r_onset):
                if onset[k] != 0 and l == 0:
                    self.pressset[k].append(int(timeset[k]))
                    timeset[k] = 0
            onset = r_onset

        # 过滤无效轨道
        valid_pressset = [p for p in self.pressset if len(p) > 5]
        if len(valid_pressset) < 2:
            self.status = "tooFewKeys"
        else:
            self.status = "OK"

        # 估算采样率
        if self.intervals:
            interval_counts = Counter(self.intervals)
            most_common_interval, _ = interval_counts.most_common(1)[0]
            self.sample_rate = 1000 / most_common_interval
        else:
            self.sample_rate = float('inf')
            
        logger.debug(f"按下事件总数(len(self.press_events)): {len(self.press_events)}")
        logger.debug(f"按下事件总数(len(self.press_times))：{len(self.press_times)}")
        logger.debug(f"按下事件时间样本（前10个）：{str(self.press_times[:10])}")
        logger.debug(f"按下事件时间样本（后10个）：{str(self.press_times[-10:])}")

    def get_data(self):
        return {
            "status": self.status,
            "player_name": self.player_name,
            "mod": self.mod,
            "score": self.score,
            "accuracy": self.acc,
            "ratio": self.ratio,
            "pressset": self.pressset,
            "press_times": self.press_times,
            "press_events": self.press_events,
            "intervals": self.intervals,
            "life_bar_graph": self.life_bar_graph,
            "sample_rate": self.sample_rate,
            "timestamp": self.timestamp,
            "file_path": self.file_path,
            "judge": self.judge
        }