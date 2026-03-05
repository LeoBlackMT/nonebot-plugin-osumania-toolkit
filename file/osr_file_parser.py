import osrparse
import os
import numpy as np

from collections import Counter
from osrparse import GameMode
from osrparse import Mod

from ..algorithm.utils import findkey

class osr_file:
    def __init__(self, file_path):
        info = osrparse.parse_replay_file(file_path)
        self.file_path = file_path
        if self.info.game_mode != GameMode.MANIA:
            self.status = "NotMania"
        else:
            self.status = "init"
            
        self.player_name = info.player_name
        self.judge = {
            "320" : info.gekis,
            "300" : info.number_300s,
            "200" : info.katus,
            "100" : info.number_100s,
            "50" : info.number_50s,
            "0" : info.misses
        }
        self.score = info.score
        self.acc = ((info.gekis + info.number_300s) * 300 + info.katus * 200 + info.number_100s * 100 + info.number_50s * 50) / (info.gekis + info.number_300s + info.number_100s + info.number_50s + info.misses + info.katus * 300) * 100
        self.ratio = info.gekis / info.number_300s if info.number_300s > 0 else 0
        self.timestamp = info.timestamp
        self.mod = str(Mod(info.mod_combination))
        self.play_data = info.play_data
        
        self.sample_rate = float('inf')
        self.pressset = [[] for _ in range(18)]
        self.intervals = []
        self.press_times = []
        self.press_events = []
        
    def process(self):
        onset = np.zeros(18)
        timeset = np.zeros(18)
        current_time = 0
        
        for i, j in enumerate(self.play_data):
            if (j.time_delta == 0 and j.keys == 0) or i < 3:
                continue
            self.intervals.append(j.time_delta)
            current_time += j.time_delta
            r_onset = findkey(j.keys)

            # 检测新按下的键
            for k, l in enumerate(r_onset):
                if onset[k] == 0 and l == 1:
                    self.press_times.append(current_time)
                    self.press_events.append((k, current_time))

            timeset += onset * j.time_delta
            for k, l in enumerate(r_onset):
                if onset[k] != 0 and l == 0:
                    self.pressset[k].append(int(timeset[k]))
                    timeset[k] = 0
            onset = r_onset

        # 过滤无效轨道
        valid_pressset = [p for p in self.pressset if len(p) > 5]
        if len(valid_pressset) < 2:
            self.status = "tooFewKeys"

        # 估算采样率
        if self.intervals:
            interval_counts = Counter(self.intervals)
            most_common_interval, _ = interval_counts.most_common(1)[0]
            self.sample_rate = 1000 / most_common_interval
        else:
            self.sample_rate = float('inf')
            
        self.status = "OK"
        
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
            "sample_rate": self.sample_rate,
            "timestamp": self.timestamp,
            "file_path": self.file_path,
            "judge": self.judge
        }        