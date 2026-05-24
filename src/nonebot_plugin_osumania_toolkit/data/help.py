from nonebot import get_plugin_config
from .utils import _build_cvtscore_ruleset_listing_text, format_dan_list_grouped
from .dan import dan_data
from ..config import Config

config = get_plugin_config(Config)

# 帮助文本数据
class omtk_help_data:
    main_menu_text = (
        ">osu!mania工具箱<\n"
        "发送/omtk显示此信息。发送/omtk <命令名> [页码]获取该命令的详细用法。\n\n"
        "可用命令：\n"
        "1. /mapview - 谱面键型分析与难度估计\n"
        "2. /pressingtime 或 /按压 - 回放按键时间分析\n"
        "3. /analyze 或 /分析 - 作弊分析\n"
        "4. /delta 或 /偏差 - 判定偏差柱状图\n"
        "5. /lifebar 或 /血条 - 血条变化折线图\n"
        "6. /spectrum 或 /频谱 - 回放频谱\n"
        "7. /scatter 或 /散点 - 判定散点图\n"
        "8. /pattern 或 /键型 - 谱面键型分析\n"
        "9. /percy 或 /投皮 - 投皮修改\n"
        "10. /acc 或 /单曲 - 单曲ACC计算\n"
        "11. /ett 或 /msd - 计算谱面MSD\n"
        "12. /cvtscore 或 /转换 - 按目标规则重算回放成绩\n"
        "13. /omtk report - 反馈问题"
    )
    # help_text 结构：(命令, 命令名称, 页码, 总页码, 帮助文本)
    help_text = [("rework", "星数重算", "1", "1",
            "提示：/rework命令现已重定向至/mapview，后者统一提供键型分析和难度估计功能。\n请使用/mapview命令来分析谱面键型和估计难度，支持更多参数和模组。\n详情请输入/omtk mapview获取命令的使用说明。"),
            
            ("pressingtime", "回放按键时间分析", "1", "1", 
            "你可以使用/pressingtime (/按压) 命令的同时回复一个 .osr/.mr 文件以分析其按压时长分布图。"),
            
            ("analyze", "作弊分析", "1", "3",
            "*警告* 该命令开销较大，请勿滥用。\n-注意- 作弊分析由算法生成，仅供参考，如有问题请反馈。\n/analyze (/分析) 命令基于回放和谱面做多维度检测（时域、频谱、delta_t）。发送命令的同时回复 .osr/.mr 触发分析；指定 bid (或输入网址)会直接分析 delta_t；未指定 bid 时可继续发送 .osu/.mc 或输入 1 执行无谱面分析。\n命令格式：/analyze [-reason] [b<bid>]\n示例：/analyze b4094064\n参数 -reason：在未检测到作弊时仍输出分析详情。作弊/可疑时始终输出。"),
            
            ("analyze", "作弊分析", "2", "3",
            "分析结果图片说明：\n当提供谱面时，将生成四格图：\n1. 按压时长分布图（左上）：各轨道的按压时长分布，异常高峰/分布差异可能意味着宏或脚本。\n2. 脉冲序列频谱图（右上）：回放按键序列的频谱，突出高频峰可用于发现固定速度的脚本或检测采样率。\n3. delta_t 直方图（左下）：按键时间与谱面时间的偏差分布柱状图，过窄或尖峰异常需关注。\n4. delta_t 散点图（右下）：偏差随时间的散点，固定偏移或规则走势可能可疑。\n\n不提供谱面时，只生成前两个图表。"),

            ("analyze", "作弊分析", "3", "3",
            "机器人返回说明：\n- 文本会按分析模块给出结论：'时域与按压时长分析'、'脉冲序列分析'、'偏移分析'，若检测到异常会在结论前标记 <!> (作弊) 或 <*> (可疑)。\n- 常见术语速览：\n1. 轨道相似度：各列按压分布的相似程度，过高/过低都不正常。\n2. 隐频/主峰 Hz：按键节奏在频谱中的突出频率，高频大峰常见于脚本。\n3. delta_t：打击时间与谱面时间差，标准差/独特值越小越刻板。\n4. MAD：中位绝对偏差，衡量波动幅度。\n5. 记忆/AR1/BDS：偏移序列的自相关与非线性记忆度，过于规则可能脚本。\n6. 多押同步/模板：同时按键的时间差，若近乎固定或反复复用模板则可疑。\n7. 长空段空敲/Gap：谱面空白区的敲击，数量或节奏过于规律会被标记。\n输出结果仅供参考，请结合图表、录像与常识综合判断。"),
            
            ("delta", "判定偏差柱状图", "1", "1", 
            "你可以使用/delta (/偏差)回复包含 .osr/.mr 文件的消息的同时使用 bid (或输入网址)指定谱面，来显示打击的判定偏差分布(按列着色)。\n命令格式：/delta [b<bid>]\n示例：/delta b4094064（同时回复回放文件）\n"),
            
            ("lifebar", "血条变化折线图", "1", "1",
            "你可以使用/lifebar (/血条)命令回复包含 .osr 文件的消息来显示一个回放的血条变化图表。\n用法：回复包含 .osr 文件的消息，同时发送 /lifebar 命令。"),
            
            ("spectrum", "回放频谱", "1", "1",
            "你可以使用/spectrum (/频谱)命令来显示一个回放的打击频谱图表。\n用法：回复包含 .osr/.mr 文件的消息，同时发送 /spectrum 命令。"),
            
            ("scatter", "判定散点图", "1", "1",
            "你可以使用/scatter (/散点)回复包含 .osr/.mr 文件的消息的同时使用 bid (或输入网址)指定谱面，来显示打击位置的二维散点图。\n命令格式：/scatter [b<bid>]\n示例：/scatter b4094064（同时回复回放文件）\n"),

            ("pattern", "键型分析", "1", "1",
            f"你可以使用/pattern (/键型)分析谱面键型。注意：键型分析由算法生成，仅供参考。LN键型键型分析处于实验性状态，如有问题请反馈。\n用法1：回复一条包含 .osu/.mc/.osz/.mcz 文件的消息，然后发送 /pattern。限制：单文件大小 {config.max_file_size_mb if config.max_file_size_mb > 0 else '无限制'} MB; 处理上限 {config.batch_max_charts if config.batch_max_charts > 0 else '无限制'} 个。\n用法2：直接使用谱面ID：/pattern b<bid>\n示例：/pattern b4094064\n说明：如果要获取详细结果，请在命令中添加-d或-detail，随后将以合并转发消息发送。"),

            ("percy", "投皮", "1", "1",
            "你可以使用/percy (/投皮)命令来查看或修改 LN 面身图片的投机取巧程度。\n用法：回复一条包含 .png 图片文件的消息，同时发送 /percy [d] [lazer|lzr]。（推荐用文件形式发送以避免被压缩）\n参数说明：\n1. d：目标投机取巧程度（整数）。不填写时仅识别并返回当前程度。\n2. lazer/lzr：按 Lazer 规则处理与显示（可选）。\n示例：/percy（仅识别当前程度）\n/percy 150（将投皮程度调整到 150px）\n/percy 225 lzr（按 Lazer 模式调整）\n注意:\n1. Lazer 模式会进行 -75px 修正（下限 0），同时将图片长度固定在32800px。\n2. 本程序暂不支持渐变颜色面身、非单一颜色、身尾分离或含有图案面身的皮肤。\n3. 请确保回复的图片文件为 .png 格式。\n\n如果你需要批处理、修复面尾白线等高级功能，请前往仓库LeoBlackMT/percy_skin_editor"),
            
            ("acc", "单曲ACC计算", "1", "3",
            "你可以使用/acc (/单曲)命令来计算osu!mania段位的单曲ACC，或通过单曲ACC推算段内变化。\n支持两种使用方式：\n1. 直接命令模式: /acc [-r] <段位名> <acc>\n/acc [-r] b<bid> [单曲个数] <acc> [-sv2]\n2. 交互模式: 直接发送 /acc [-r]，然后按照提示进行操作。\n本命令可以根据bid或提供文件自动划分单曲且支持自定义物量以及单曲个数。\n\n注意事项:\n1. 使用 ‘-’ 分隔acc。如 99.4-99.3-98.8-97.6\n2. 使用 ‘,’ (半角) 分隔自定义物量。如1145,1419,1981(3首歌的段位)\n3. 支持上传 .osu/.mc 谱面文件。\n4. 命令中包含 -sv2 （即sv2标识）时启用sv2模组\n5. 命令中包含 -r （即反向计算标识）时通过单曲ACC推算段内变化\n\n查看可用段位列表请发送: /omtk acc 2"),
            
            ("acc", "单曲ACC计算", "2", "3",
            "可用段位列表(*替换为具体的数字，$替换为版本):\n1. Malody 4K Dan: 使用 *danv$ 或 ex*v$\n2. Malody 4K Extra Dan v2 (Sample): 使用 spex*\n3. osu!mania 4K Dan ~ REFORM (DDMythical): 使用 rf* 或 希腊字母(如alpha)\n备注: zeta和eta默认为Thaumiel，spz为Emik，额外支持haku(白段)\n4. osu!mania 4K LN Dan Courses v2: 使用 ln* \n5. xfpsb: 使用 xfpsb*, 其中*还可以是f \n6. wds0 Dan: 使用 wds0_* ,其中*还可以是j,n,f\n7. Senpai Dan v1: 使用 senpai* 或 senpaiex* \n8. osu!mania 7K Regular Dan Course: 使用 7k*dan 或 7k*, 其中后者包含s,g,z,a \n9. osu!mania 7K LN Dan Course: 使用 7kln*, 其中*还可以是s,g,z,a \n\n查看全部内置段位详情请发送: /omtk acc 3"),
            
            ("acc", "单曲ACC计算", "3", "3",
            "全部内置段位列表:\n" + format_dan_list_grouped(sorted(dan_data.dan_notes.keys()))),

            ("mapview", "键型分析与难度估计", "1", "2",
            f"你可以回复包含 .osu/.mc 文件的消息，或回复包含 .osz/.mcz 的消息，或使用 bid/网址 指定谱面来分析键型和估计难度。本命令别名/rework。\n命令格式：/mapview b<bid> +[mods] x[speed] OD[OD] \n示例：/mapview b4094064 +EZHO x1.25\n/mapview b4094064 +IN OD8\n警告：图包分析开销较大，请勿滥用。限制：单文件大小 {config.max_file_size_mb if config.max_file_size_mb > 0 else '无限制'} MB; 处理上限 {config.batch_max_charts if config.batch_max_charts > 0 else '无限制'} 个。\n注意：1. 如果你回复了一个包含谱面/图包文件的消息，命令将忽略bid。\n2. 部分模组和参数冲突。"),
            
            ("mapview", "键型分析与难度估计", "2", "2",
            "/mapview 参数说明：\n- bid: 以 b 开头，后跟整数，从官网获取谱面。或输入网址。\n- mods: 以 + 开头，后跟模组名缩写（支持 HR/EZ、DT/HT、IN/HO、DC/NC）。不区分大小写，格式同雨沐机器人。\n- speed: 以 x 或 * 或 × 开头，后跟倍速数值（如 x1.5）。倍速必须在 0.25 到 3.0 之间。\n- OD: 以 OD 开头, OD值必须在 -15 到 15 之间。"),
            
            ("ett", "Etterna难度计算", "1", "1",
             f"你可以回复包含 .osu/.mc 文件的消息，或回复包含 .osz/.mcz 的消息，或使用 bid/网址 指定谱面来计算谱面MSD。\n命令格式：/ett b<bid> x[speed]\n示例：/ett b4094064 x1.25\n警告：图包分析开销较大，请勿滥用。限制：单文件大小 {config.max_file_size_mb if config.max_file_size_mb > 0 else '无限制'} MB; 处理上限 {config.batch_max_charts if config.batch_max_charts > 0 else '无限制'} 个。\n注意：1. 如果你回复了一个包含谱面/图包文件的消息，命令将忽略bid。\n2. 该命令仅支持 rate（如 x1.5），不支持 mods、OD 覆写和 IN/HO。\n3. 计算结果仅供参考，MSD在不同版本下因算法差异可能不同，本插件使用0.74.0 MinaClac。\n4. 命令别名 /msd"),

            ("cvtscore", "成绩转换", "1", "3",
             "你可以使用 /cvtscore (/转换) 将同一回放按目标 ruleset 重算成绩。\n"
             "输入：回放(.osr/.mr) + 谱面(bid 或 .osu/.mc) + 目标 ruleset。\n"
             "注意：该功能目前处于实验性状态，如有问题请反馈。"
             "命令示例：\n"
             "1. /cvtscore Quaver/chill sc diff4 （然后发送回放）\n"
             "2. /cvtscore b4094064 -sv2 （然后发送回放和谱面）\n"
             "3. 直接发送 /cvtscore 进入交互模式。\n"
             "目标 ruleset 写法：模板优先（如 sc diff4、wife3 j7），具体规则用 Group/Name（如 Quaver/chill）。\n"
             "参数匹配大小写不敏感。查看参数详解：/omtk cvtscore 2；查看全部 ruleset：/omtk cvtscore 3"),

            ("cvtscore", "成绩转换", "2", "3",
             "/cvtscore 参数详解：\n"
             "1. 回放文件：支持 .osr / .mr。\n"
             "2. 谱面输入：.osu / .mc，或 b<bid> / mania 链接。\n"
             "3. sv2 开关：-sv2 / sv2 / +sv2（开启）；-nosv2 / nosv2 / sv1（关闭）。\n"
             "4. 目标 ruleset：\n"
             "   - 模板优先：sc j4、wife3 j7、template/sc diff4\n"
             "   - 具体规则：Quaver/chill、Malody/A\n"
             "   - 模板参数支持：diff 4、diff4、diff=4、j7\n"
             "5. 交互流程：回放 -> 谱面 -> 目标 ruleset。\n"
             "6. 大小写不敏感：上述所有参数大小写均不敏感。"),

            ("cvtscore", "成绩转换", "3", "3",
             "全部可用模板和 ruleset：\n" + _build_cvtscore_ruleset_listing_text()),
            
            ("report", "反馈问题", "1", "1",
             "如果你在使用过程中遇到任何问题、错误或有任何建议，欢迎提交GitHub Issues来反馈给开发者：\nhttps://github.com/LeoBlackMT/nonebot-plugin-osumania-toolkit/issues/new")
            ]
    command_aliases = {
        "按压": "pressingtime",
        "分析": "analyze",
        "偏差": "delta",
        "血条": "lifebar",
        "频谱": "spectrum",
        "散点": "scatter",
        "键型": "pattern",
        "投皮": "percy",
        "单曲": "acc",
        "转换": "cvtscore",
        }