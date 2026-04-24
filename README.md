# nonebot_plugin_osumania_toolkit

这是一个 Nonebot 插件，提供多种osu!mania高级分析功能和实用工具。
目前该插件处于开发中，如果你想使用，下载仓库nonebot_plugin_osumania_toolkit文件夹后在Nonebot2中[加载插件](https://nonebot.dev/docs/2.4.2/tutorial/create-plugin#%E5%8A%A0%E8%BD%BD%E6%8F%92%E4%BB%B6)即可。

注：如果你要在Linux上运行，可能要对algorithm/ett/official_minaclac_runner授予执行权限（chmod +x official_minaclac_runner）。
这与official_minaclac_runner.exe一致，编译自Etterna官方的mina_clac_runner，最大程度上确保与官方算法一致。

本插件使用了我的另一个项目[ManiaMapAnalyser](https://github.com/LeoBlackMT/osumania_map_analyser)中的Mixed难度估计算法，你可以前往[Benchmark](https://leoblackmt.github.io/osumania_map_analyser/?algorithm=Mixed&scope=ALL)查看基于真实谱面数据的估计算法表现。

## 功能特性

0. **使用/omtk查看帮助信息。**
1. **星数重算 (/rework)** - 现已重定向至/mapview
2. **作弊分析 (/analyze)** - 基于回放和谱面的多维度高级分析，检测可能的作弊行为
3. **按压时间分析 (/pressingtime)** - 分析玩家按键按压时长分布
4. **判定偏差分析 (/delta)** - 显示打击判定偏差分布（按列着色）
5. **血条分析 (/lifebar)** - 可视化回放过程中的血条变化
6. **频谱分析 (/spectrum)** - 分析回放打击事件的频谱特征
7. **散点图分析 (/scatter)** - 显示打击位置的二维散点图
8. **单曲ACC计算 (/acc)** - 计算osu!mania段位的单曲ACC，支持交互计算、自定义物量和单曲个数、根据bid或提供文件自动划分单曲等实用功能
9. **投皮修改 (/percy)** - 对 LN 皮肤图修改投机取巧程度，支持 Stable/Lazer 两种模式
10. **键型分析 (/pattern)** - 初步分析谱面键型，当前只支持RC键型分析
11. **谱面分析与难度估计 (/mapview)** - 通过分析谱面结构和特征，提供键型分析和难度估计功能，支持多种参数和模组（基于\[Crz\]sunnyxxy和interlude算法）
12. **Etterna难度计算 (/ett)** - 将谱面按 Etterna 方式计算难度，提供更符合 Etterna 玩家习惯的难度评估（基于Etterna官方算法）。
13. **成绩转换 (/cvtscore)** - 将成绩转换为其他游戏的成绩，支持多种游戏的多个判定，支持自定义规则，支持模板规则。
14. **文件格式支持** - 支持.osr、.mr、.osu、.mc多种文件格式，允许图包分析（.osz/.mcz），并支持通过bid或mania谱面网址指定谱面进行分析
15. **丰富的配置选项** - 可配置键型分析和作弊分析的丰富参数，满足不同需求
16. **支持模板规则集** - 可自定义规则模板，方便快速使用预设的规则集进行成绩转换等操作。详情请查看[规则集示例](ruleset-description.jsonc)和[规则集模板示例](ruleset-template-description.jsonc)。

## 配置说明
| 配置项 | 是否必填 | 类型 | 默认值 | 说明 |
|:-----:|:----:|:----:|:----:|:----:|
| omtk_cache_max_age | 否 | int | 24 | 缓存文件最大保留时间（小时） |
| default_convert_od | 否 | int | 8 | .mc转.osu的默认OverallDifficulty值 |
| default_convert_hp | 否 | int | 8 | .mc转.osu的默认HPDrainRate值 |
| max_file_size_mb | 否 | int | 50 | 允许处理的最大文件大小（MB） |

注: 其他内容的相关配置项过多，这里只列出基础配置部分。如有修改需要请查看[配置文件](nonebot_plugin_osumania_toolkit/config.py)（config.py）

## Todo
- ~~由回放与谱面转换成绩~~
  - ~~支持图片输出~~
- ~~修复.mr在rework和analyze上可能导致的问题~~
  - 已修复大部分问题，仍有小部分问题未解决
- 尝试添加对.mrv的支持
- ~~尝试对xxy算法进行改进~~
  - ~~暂时做不到。~~
    - 引入了其他估计算法进行了整体优化，特定情况下准确度大幅提升，总体上略有提升。
- 优化代码结构和性能

### Special Thanks
感谢 wds0 对本项目的资助和支持！
感谢[ElainaFanBoy](https://github.com/ElainaFanBoy)大佬对文件管理和架构的优化！
