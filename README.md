<div align="center">

# nonebot-plugin-osumania-toolkit

_✨ 本插件提供多种osu!mania高级分析功能和实用工具 ✨_


<a href="./LICENSE">
    <img src="https://img.shields.io/github/license/LeoBlackMT/nonebot-plugin-osumania-toolkit.svg" alt="license">
</a>
<a href="https://pypi.python.org/pypi/nonebot-plugin-osumania-toolkit">
    <img src="https://img.shields.io/pypi/v/nonebot-plugin-osumania-toolkit.svg" alt="pypi">
</a>
<img src="https://img.shields.io/badge/python-3.10--3.12-blue.svg" alt="python">

</div>

## 功能特性

1. **谱面分析与难度估计 (/rework)** - 通过分析谱面结构和特征，提供键型分析和难度估计功能，支持多种参数和模组（基于项目[ManiaMapAnalyser](https://github.com/LeoBlackMT/osumania_map_analyser)中的Mixed难度估计算法）
2. **作弊分析 (/analyze)** - 基于回放和谱面的多维度高级分析，检测可能的作弊行为
3. **单曲ACC计算 (/acc)** - 计算osu!mania段位的单曲ACC，支持交互计算、自定义物量和单曲个数、根据bid或提供文件自动划分单曲等功能
4. **投皮修改 (/percy)** - 对 LN 皮肤图修改投机取巧程度，支持 Stable/Lazer 两种模式
5. **键型分析 (/pattern)** - 分析谱面键型，支持RC/LN/多k键型分析
6. **Etterna难度计算 (/ett)** - 将谱面按 Etterna 方式计算难度，提供更符合 Etterna 玩家习惯的难度评估（基于Etterna官方算法）。
7. **成绩转换 (/cvtscore)** - 将成绩转换为其他游戏的成绩，支持多种游戏的多个判定，支持自定义规则，支持模板规则。
8. **文件格式支持** - 支持.osr、.mr、.osu、.mc多种文件格式，允许图包分析（.osz/.mcz），并支持通过bid或mania谱面网址指定谱面进行分析
9. **丰富的配置选项** - 可配置键型分析和作弊分析的丰富参数，满足不同需求
10. **支持模板规则集** - 可自定义规则模板，方便快速使用预设的规则集进行成绩转换等操作。

## 安装方法

<details open>
<summary>使用 nb-cli 安装</summary>
在 nonebot2 项目的根目录下打开命令行, 输入以下指令即可安装

    nb plugin install nonebot-plugin-osumania-toolkit

</details>

<details>
<summary>使用包管理器安装</summary>
在 nonebot2 项目的插件目录下, 打开命令行, 根据你使用的包管理器, 输入相应的安装命令

<details>
<summary>pip</summary>

    pip install nonebot-plugin-osumania-toolkit
</details>
<details>
<summary>pdm</summary>

    pdm add nonebot-plugin-osumania-toolkit
</details>
<details>
<summary>poetry</summary>

    poetry add nonebot-plugin-osumania-toolkit
</details>


打开 nonebot2 项目根目录下的 `pyproject.toml` 文件, 在 `[tool.nonebot]` 部分追加写入

    plugins = ["nonebot_plugin_osumania_toolkit"]

</details>

## 使用提示

1. 对 bot 发送 `/omtk` 获取帮助信息
2. 如果插件运行在 Unix 系统上，需要对 `algorithm/ett/official_minaclac_runner` 授予执行权限（`chmod +x official_minaclac_runner`），以确保`/ett`功能正常使用。
3. 如果需要为`/cvtscore`添加其他规则集，请参考[规则集示例](docs/ruleset-description.jsonc)和[规则集模板示例](docs/ruleset-template-description.jsonc)。
4. 如果未来Etterna官方算法有更新而本插件尚未更新，或你想使用自定义的算法版本时，可以参考[构建指南](docs/builder_usage.md)自行构建并替换`algorithm/ett/official_minacalc_runner`。
5. 关于估计算法的准确度和表现，你可以前往[ManiaMapAnalyser Benchmark](https://leoblackmt.github.io/osumania_map_analyser/?algorithm=Mixed&scope=ALL)查看基于真实谱面数据的评测结果。
6. 如果你有任何问题或建议，欢迎提交issue或pr。


## 配置说明
| 配置项 | 是否必填 | 类型 | 默认值 | 说明 |
|:-----:|:----:|:----:|:----:|:----:|
| omtk_cache_max_age | 否 | int | 24 | 缓存文件最大保留时间（小时） |
| default_convert_od | 否 | int | 8 | .mc转.osu的默认OverallDifficulty值 |
| default_convert_hp | 否 | int | 8 | .mc转.osu的默认HPDrainRate值 |
| max_file_size_mb | 否 | int | 50 | 允许处理的最大文件大小（MB） |

注: 其他内容的相关配置项过多，这里只列出基础配置部分。如有修改需要请查看[配置文件](src/nonebot_plugin_osumania_toolkit/config.py)中的注释。

## 参考内容
- [Suuny Rework](https://github.com/sunnyxxy/Star-Rating-Rebirth): 使用了Suuny Rework的算法进行难度估计。
- [Interlude](https://github.com/YAVSRG/YAVSRG): 使用了Interlude的RC键型分析算法并在基础上新增LN检测算法。
- [Daniel](https://thebagelofman.github.io/Daniel/): 使用了Daniel的算法进行难度估计。
- [Companella](https://github.com/Leinadix/companella): 使用了Companella的算法进行难度估计。
- [Etterna](https://github.com/etternagame/etterna): 使用了Etterna官方的算法进行难度计算，并提供了构建指南以便用户自行构建和替换。

## 特别鸣谢

- 感谢 wds0 对本项目的资助和支持！
- 感谢[ElainaFanBoy](https://github.com/ElainaFanBoy)对文件管理的优化！
