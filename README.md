# nonebot_plugin_osumania_toolkit

这是一个 Nonebot 插件，提供多种osu!mania高级分析功能和实用工具。
目前该插件处于开发中，如果你想使用，下载仓库nonebot_plugin_osumania_toolkit文件夹后在Nonebot2中[加载插件](https://nonebot.dev/docs/2.4.2/tutorial/create-plugin#%E5%8A%A0%E8%BD%BD%E6%8F%92%E4%BB%B6)即可。

## 功能概述

0. **使用/omtk查看帮助信息。**
1. **星数重算 (/rework)** - 基于\[Crz\]sunnyxxy算法重新计算谱面星数，支持自定义模组、倍速、OD等参数
2. **作弊分析 (/analyze)** - 基于回放和谱面的多维度高级分析，检测可能的作弊行为
3. **按压时间分析 (/pressingtime)** - 分析玩家按键按压时长分布
4. **判定偏差分析 (/delta)** - 显示打击判定偏差分布（按列着色）
5. **血条分析 (/lifebar)** - 可视化回放过程中的血条变化
6. **频谱分析 (/spectrum)** - 分析回放打击事件的频谱特征
7. **散点图分析 (/scatter)** - 显示打击位置的二维散点图
8. **单曲ACC计算 (/acc)** - 计算osu!mania段位的单曲ACC，支持交互计算、自定义物量和单曲个数、根据bid或提供文件自动划分单曲等实用功能
9. **投皮修改 (/percy)** - 对 LN 皮肤图修改投机取巧程度，支持 Stable/Lazer 两种模式
10. **键型分析 (/pattern)** - 初步分析谱面键型，当前只支持RC键型分析
11. **文件格式支持** - 支持.osr、.mr、.osu、.mc多种文件格式

## 配置说明
| 配置项 | 是否必填 | 类型 | 默认值 | 说明 |
|:-----:|:----:|:----:|:----:|:----:|
| omtk_cache_max_age | 否 | int | 24 | 缓存文件最大保留时间（小时） |
| default_convert_od | 否 | int | 8 | .mc转.osu的默认OverallDifficulty值 |
| default_convert_hp | 否 | int | 8 | .mc转.osu的默认HPDrainRate值 |
| max_file_size_mb | 否 | int | 50 | 允许处理的最大文件大小（MB） |

注意: 关于作弊分析的相关配置项过多，这里不列出。如有修改需要请查看[配置文件](nonebot_plugin_osumania_toolkit/config.py)（config.py）

## Todo
- 添加更多内置段位
- ~~支持修改投皮~~
  - ~~增加对更多类型皮肤的支持~~
- ~~分析谱面键型（基于interlude）~~
  - 在原来的基础上增加LN键型分析
- ~~大幅优化作弊分析算法~~
- 由回放与谱面转换成绩
- ~~修复.mr在rework和analyze上可能导致的问题~~
  - 已修复大部分问题，仍有小部分问题未解决
- 尝试添加对.mrv的支持
- 尝试对xxy算法进行改进
- 合并pattern和rework并使用图片输出
- 优化代码结构和性能

### Special Thanks

感谢[ElainaFanBoy](https://github.com/ElainaFanBoy)大佬对文件管理和架构的优化！
