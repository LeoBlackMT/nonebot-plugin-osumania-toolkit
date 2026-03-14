# nonebot_plugin_osumania_toolkit

这是一个 Nonebot 插件，提供多种osu!mania高级分析功能和实用工具。
目前该插件处于开发中，如果你想使用，克隆仓库后在Nonebot中[加载插件](https://nonebot.dev/docs/2.4.2/tutorial/create-plugin#%E5%8A%A0%E8%BD%BD%E6%8F%92%E4%BB%B6)即可。

## 功能概述

0. 使用/omtk查看帮助信息。
1. **星数重算 (Rework)** - 基于\[Crz\]sunnyxxy算法重新计算谱面星数，支持自定义模组、倍速、OD等参数
2. **作弊分析 (Analyze)** - 基于回放文件的时域和频域分析，检测可能的作弊行为
3. **按压时间分析 (Pressingtime)** - 分析玩家按键按压时长分布
4. **判定偏差分析 (Delta)** - 显示打击判定偏差分布（按列着色）
5. **血条分析 (Lifebar)** - 可视化回放过程中的血条变化
6. **频谱分析 (Spectrum)** - 分析回放打击事件的频谱特征
7. **散点图分析 (Scatter)** - 显示打击位置的二维散点图
8. **文件格式支持** - 支持.osr、.mr、.osu、.mc多种文件格式

## 配置说明
| 配置项 | 是否必填 | 类型 | 默认值 | 说明 |
|:-----:|:----:|:----:|:----:|:----:|
| omtk_cache_max_age | 否 | int | 24 | 缓存文件最大保留时间（小时） |
| bin_max_time | 否 | int | 500 | 按压分布直方图最大时间（ms） |
| bin_width | 否 | int | 1 | 按压分布直方图最大bin数 |
| sim_right_cheat_threshold | 否 | float | 0.99 | 轨道相似度上作弊阈值 |
| sim_right_sus_threshold | 否 | float | 0.985 | 轨道相似度上可疑阈值 |
| sim_left_cheat_threshold | 否 | float | 0.4 | 轨道相似度下作弊阈值 |
| sim_left_sus_thresholdS | 否 | float | 0.55 | 轨道相似度下可疑阈值 |
| abnormal_peak_threshold | 否 | float | 0.33 | 异常高峰占比阈值 |
| low_sample_rate_threshold | 否 | float | 165 | 低采样率阈值 |
| default_convert_od | 否 | int | 8 | .mc转.osu的默认OverallDifficulty值 |
| default_convert_hp | 否 | int | 8 | .mc转.osu的默认HPDrainRate值 |

## Todo
- ~~支持malody文件格式.mr与.mc~~
- ~~支持rework图包~~
- 计算单曲acc，支持提供谱面自动划分各单曲物量
- ~~支持.mr转换到.osr~~
  - 由于转换后的回放文件通常无法根据hash找到谱面文件(原始文件是.mc, osu读不了)，该功能不再开发。
- 分析谱面键型（基于interlude）
- 由回放与谱面转换成绩
- 修复.mr在rework和analyze上可能导致的问题
- 尝试添加对.mrv的支持

### Special Thanks

感谢[ElainaFanBoy](https://github.com/ElainaFanBoy)大佬的pr