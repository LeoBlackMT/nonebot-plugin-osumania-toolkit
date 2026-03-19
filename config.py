from pydantic import BaseModel


class Config(BaseModel):
    """Plugin Config Here"""

    # 缓存文件最大保留时间（小时），默认 24 小时
    omtk_cache_max_age: int = 24

    # 允许自动清理的临时文件目录列表，仅这些目录下的源文件会在复制后被删除
    # 例如: omtk_temp_cleanup_dirs=["C:\\Users\\Demo\\Downloads"]
    omtk_temp_cleanup_dirs: list[str] = []
    
    # 作弊分析阈值
    bin_max_time: int = 500 # 直方图最大时间(ms)
    bin_width: int = 1 # 直方图bin数
    sim_right_cheat_threshold: float = 0.99 # 轨道相似度上作弊阈值
    sim_right_sus_threshold: float = 0.985 # 轨道相似度上可疑阈值
    sim_left_cheat_threshold: float = 0.4 # 轨道相似度下作弊阈值
    sim_left_sus_thresholdS: float = 0.55 # 轨道相似度下可疑阈值
    abnormal_peak_threshold: float = 0.33 # 异常高峰占比阈值
    low_sample_rate_threshold: float = 165 # 低采样率阈值
    
    # .mc 转 .osu 的默认 OverallDifficulty 和 HPDrainRate
    default_convert_od: int = 8
    default_convert_hp: int = 8
