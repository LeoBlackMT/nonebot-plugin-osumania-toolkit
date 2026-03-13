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

## Todo
- ~~支持malody文件格式.mr与.mc~~
- ~~支持rework图包~~
- 计算单曲acc，支持提供谱面自动划分各单曲物量
- 支持.mr转换到.osr
- 分析谱面键型（基于interlude）
- 由回放与谱面转换成绩
- 修复.mr在rework和analyze上可能导致的问题
- 尝试添加对.mrv的支持
