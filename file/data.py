import re


# 辅助函数
def format_dan_list(dans: list, items_per_line: int = 5) -> str:
    """
    格式化段位列表，每行显示指定数量的段位
    
    参数:
        dans: 段位名列表
        items_per_line: 每行显示的段位数量
    
    返回:
        格式化后的字符串
    """
    formatted_lines = []
    for i in range(0, len(dans), items_per_line):
        line = dans[i:i + items_per_line]
        formatted_lines.append(", ".join(line))
    return "\n".join(formatted_lines)

def _get_dan_group_name(dan_name: str) -> str:
    """根据段位命名规则返回分组名。"""
    greek_names = {"alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "spz"}

    if dan_name.startswith("wds0_"):
        return "wds0"
    if dan_name.startswith("xfpsb"):
        return "xfpsb"
    if dan_name.startswith("7kln"):
        return "7kln"
    if dan_name.startswith("7k"):
        return "7k"
    if dan_name.startswith("ln"):
        return "ln"
    if dan_name.startswith("senpaiex"):
        return "senpaiex"
    if dan_name.startswith("senpai"):
        return "senpai"
    if dan_name.startswith("spex"):
        return "spex"
    if re.match(r"^ex(?:\d+v\d(?:\.\d+)?|fv\d)$", dan_name):
        return "ex"
    if re.match(r"^\d+danv\d$", dan_name):
        return "danv"
    if re.match(r"^rf\d+$", dan_name) or dan_name in greek_names:
        return "rf/reform"
    if dan_name == "haku":
        return "misc"
    return "other"

def format_dan_list_grouped(dans: list, items_per_line: int = 5) -> str:
    """按前缀分组并格式化段位列表。"""
    groups = {}
    for dan in sorted(dans):
        group_name = _get_dan_group_name(dan)
        groups.setdefault(group_name, []).append(dan)

    preferred_order = [
        "danv",
        "ex",
        "spex",
        "rf/reform",
        "ln",
        "xfpsb",
        "7k",
        "7kln",
        "senpai",
        "senpaiex",
        "wds0",
        "misc",
        "other",
    ]

    ordered_group_names = [name for name in preferred_order if name in groups]
    ordered_group_names.extend(sorted(name for name in groups if name not in preferred_order))

    formatted_sections = []
    for group_name in ordered_group_names:
        formatted_sections.append(f"[{group_name}]")
        formatted_sections.append(format_dan_list(groups[group_name], items_per_line))

    return "\n\n".join(formatted_sections)

# 所有数据

# 帮助文本数据
class omtk_help_data:
    # help_text 结构: (命令, 命令名称, 页码, 总页码, 帮助文本)
    main_menu_text = (
        ">osu!mania工具箱<\n"
        "发送/omtk显示此信息。发送/omtk <命令名> [页码]获取该命令的详细用法。\n\n"
        "可用命令：\n"
        "1. /rework - 星数重算\n"
        "2. /pressingtime 或 /按压 - 按键时间分析\n"
        "3. /analyze 或 /分析 - 作弊分析\n"
        "4. /delta 或 /偏差 - 判定偏差分析\n"
        "5. /lifebar 或 /血条 - 血条显示\n"
        "6. /spectrum 或 /频谱 - 频谱显示\n"
        "7. /scatter 或 /散点 - 散点图\n"
        "8. /percy 或 /投皮 - 投皮修改\n"
        "9. /acc 或 /单曲 - 单曲ACC计算\n"
    )
    help_text = [("rework", "星数重算", "1", "2",
            "你可以回复包含 .osu/.mc 文件的消息，或回复包含 .osz/.mcz 的消息，或使用 bid 指定谱面。\n命令格式：/rework b<bid> +[mods] x[speed] OD[OD] gap:[gap] \n示例：/rework b4094064 +EZHO x1.25\n/rework b4094064 +IN OD8 gap:50\n警告：图包分析开销较大，请勿滥用。结果将发送大量文字，谨防刷屏。\n注意：1. 如果你回复了一个包含谱面/图包文件的消息，命令将忽略bid。\n2. 部分模组和参数冲突。"),
            
            ("rework", "星数重算", "2", "2",
            "/rework参数说明：\n- bid: 以 b 开头，后跟整数，从官网获取谱面。\n- mods: 以 + 开头，后跟模组名缩写（支持 HR/EZ、DT/HT、IN/HO、DC/NC）。不区分大小写，格式如雨沐。\n- speed: 以 x 或 * 开头，后跟倍速数值（如 x1.5）。倍速必须在 0.25 到 3.0 之间。\n- OD: 以 OD 开头, OD值必须在 -15 到 15 之间。\n- gap: 反键面缝参数，以 gap: 开头，后跟整数，单位ms, 默认150， 仅在 IN 模组启用时有效。"),
            
            ("pressingtime", "按键时间", "1", "1", 
            "你可以使用/pressingtime (/按压) 命令的同时回复一个 .osr/.mr 文件以分析其按压时长分布图。\n注：作弊分析已移动至/analyze命令。"),
            
            ("analyze", "作弊分析", "1", "2", 
            "*警告* 该命令开销较大，请勿滥用。\n-注意- 作弊分析由算法生成，仅供参考，仍处于早期实验阶段，如有问题请反馈。\n这是一个基于回放文件和谱面文件的作弊分析命令。你可以使用/analyze (/分析)回复包含 .osr/.mr 文件的消息来分析回放。如果同时指定bid，将分析delta_t，否则将执行无谱面分析，或发送 .osu/.mc 谱面文件继续分析。\n命令格式：/analyze [b<bid>]\n示例：/analyze b4094064"),
            
            ("analyze", "作弊分析", "2", "2",
            "分析结果图片说明：\n当提供谱面时，将生成四格图：\n1. 按压时长分布图（左上）：显示每个轨道的按压时长分布，横轴为按压时长（ms），纵轴为计数。不同轨道用不同颜色表示。正常玩家各轨道分布相似，作弊可能显示异常高峰或分布差异过大。\n2. 脉冲序列频谱图（右上）：将整个回放的按键事件作为脉冲序列进行傅里叶变换，显示其频谱。横轴为频率（Hz），纵轴为幅度。可用于检测周期性按键模式（如连点器）。\n3. delta_t 直方图（左下）：显示玩家按键时间与谱面物件时间的偏差（delta_t）分布。横轴为delta_t（ms），纵轴为计数。正常分布应接近正态分布，作弊可能显示极窄分布或异常峰值。\n4. delta_t 散点图（右下）：以谱面物件时间为横轴，delta_t为纵轴绘制散点图，可观察偏差随时间的变化。正常应随机分布在0附近，作弊可能显示规律模式或固定偏差。\n\n当不提供谱面时，只生成前两个图表（按压时长分布图和脉冲序列频谱图）。"),
            
            ("delta", "判定偏差", "1", "1", 
            "你可以使用/delta (/偏差)回复包含 .osr/.mr 文件的消息的同时使用 bid 指定谱面，来显示打击的判定偏差分布(按列着色)。\n命令格式：/delta [b<bid>]\n示例：/delta b4094064（同时回复osr）\n"),
            
            ("lifebar", "血条", "1", "1",
            "你可以使用/lifebar (/血条)命令来显示一个回放的血条变化图表。\n用法：回复包含 .osr 文件的消息，然后发送 /lifebar 命令。"),
            
            ("spectrum", "频谱", "1", "1",
            "你可以使用/spectrum (/频谱)命令来显示一个回放的打击频谱图表。\n用法：回复包含 .osr/.mr 文件的消息，然后发送 /spectrum 命令。"),
            
            ("scatter", "散点图", "1", "1",
            "你可以使用/scatter (/散点)回复包含 .osr/.mr 文件的消息的同时使用 bid 指定谱面，来显示打击位置的二维散点图。\n命令格式：/scatter [b<bid>]\n示例：/scatter b4094064（同时回复osr）\n"),

            ("percy", "投皮", "1", "1",
            "你可以使用/percy (/投皮)命令来查看或修改 LN 图片的投机取巧程度。\n用法：回复一条包含 .png 图片文件的消息，同时发送 /percy [d] [lazer|lzr]。\n参数说明：\n1. d：目标投机取巧程度（整数）。不填写时仅识别并返回当前程度。\n2. lazer/lzr：按 Lazer 规则处理与显示（可选）。\n示例：/percy（仅识别当前程度）\n/percy 150（将投皮程度调整到 150px）\n/percy 225 lzr（按 Lazer 模式调整）\n注意:\n1. Lazer 模式会进行 -75px 修正（下限 0），同时将图片长度固定在32800px。\n2. 本程序暂不支持渐变颜色面身、非单一颜色或含有图案面身的皮肤。\n3. 请确保回复的图片文件为 .png 格式。"),
            
            ("acc", "单曲ACC计算", "1", "3",
            "你可以使用/acc (/单曲)命令来计算osu!mania段位的单曲ACC，或通过单曲ACC推算段内变化。\n支持两种使用方式：\n1. 直接命令模式: /acc [-r] <段位名> <acc>\n/acc [-r] b<bid> [单曲个数] <acc> [-sv2]\n2. 交互模式: 直接发送 /acc [-r]，然后按照提示进行操作。\n本功能可以根据bid或提供文件自动划分单曲且支持自定义物量以及单曲个数。\n\n注意事项:\n1. 使用 ‘-’ 分隔acc。如 99.4-99.3-98.8-97.6\n2. 使用 ‘,’ (半角) 分隔自定义物量。如1145,1419,1981(3首歌的段位)\n3. 支持上传 .osu/.mc 谱面文件。\n4. 命令中包含 -sv2 （即sv2标识）时启用sv2模组\n5. 命令中包含 -r （即反向计算标识）时通过单曲ACC推算段内变化\n\n查看可用段位列表请发送: /omtk acc 2"),
            
            ("acc", "单曲ACC计算", "2", "3",
            "可用段位列表(*替换为具体的数字，$替换为版本号):\n1. Malody 4K Dan: 使用 *danv$ 或 ex*v$\n2. Malody 4K Extra Dan v2 (Sample): 使用 spex*\n3. osu!mania 4K Dan ~ REFORM (DDMythical): 使用 rf* 或 希腊字母(如alpha)\n备注: zeta和eta默认为Thaumiel，spz为Emik，额外支持haku(白段)\n4. osu!mania 4K LN Dan Courses v2: 使用 ln* \n5. xfpsb: 使用 xfpsb*, 其中*还可以是f \n6. wds0 Dan: 使用 wds0_* ,其中*还可以是j,n,f\n7. Senpai Dan v1: 使用 senpai* 或 senpaiex* \n8. osu!mania 7K Regular Dan Course: 使用 7k*dan 或 7k*, 其中后者包含s,g,z,a \n9. osu!mania 7K LN Dan Course: 使用 7kln*, 其中*还可以是s,g,z,a \n\n查看全部内置段位详情请发送: /omtk acc 3"),
            
            ("acc", "单曲ACC计算", "3", "3",
            "全部内置段位列表:\n(正在加载...)")
            ]
    command_aliases = {
        "按压": "pressingtime",
        "分析": "analyze",
        "偏差": "delta",
        "血条": "lifebar",
        "频谱": "spectrum",
        "散点": "scatter",
        "投皮": "percy",
        "单曲": "acc"
        }

# parser数据
class file_parser_data:
    MOD_MAPPING = {
        0: "None",
        1: "NoFail",
        2: "Easy",
        4: "TouchDevice",
        8: "Hidden",
        16: "HardRock",
        32: "SuddenDeath",
        64: "DoubleTime",
        128: "Relax",
        256: "HalfTime",
        512: "Nightcore",
        1024: "Flashlight",
        2048: "Autoplay",
        4096: "SpunOut",
        8192: "Autopilot",
        16384: "Perfect",
        32768: "Key4",
        65536: "Key5",
        131072: "Key6",
        262144: "Key7",
        524288: "Key8",
        1048576: "FadeIn",
        2097152: "Random",
        4194304: "Cinema",
        8388608: "TargetPractice",
        16777216: "Key9",
        33554432: "Coop",
        67108864: "Key1",
        134217728: "Key3",
        268435456: "Key2",
        536870912: "ScoreV2",
        1073741824: "Mirror",
    }

# 段位物量数据
class dan_data:
    """
    段位物量数据
    数据来源：
    https://github.com/uzxn/acc/blob/main/data.js
    结构: dict, 键为段位名，值为:
        [n, note1, ..., noteN] 或
        [n, note1, ..., noteN, sv2_note1, ..., sv2_noteN]
        
    忽略的段位：
    "rf_z": { num: 4, note: [2895, 1292, 1958, 4911], song: ["Koxx - A Fool Moon Night (DDMythical) [Original]", "Lil B - Flex 36 (Skwid, Dump Parade) {1.7}", "Ishikawa Chiaki - Uninstall (Mootz) [Mootz Mix 3]", "Various Artists - Reform Stamina Mega Mix (Various Charters) [Original]"] },
    "rfsp_ea": { num: 4, note: [2531, 2675, 3560, 2855], song: ["SHK - Log-in (Lynessa) [Lynessa's Jack Collection] {1.235x}", "Silentroom - Nhelv (Guilhermeziat) [Silent] {1.14x}", "DJ Sharpnel - Cyber Inductance (Wh1teh) [Valedumps] {1.0925x}", "antiPLUR - Speed of Link (Adaww) [Light] {1.1875x // cut}"] },
    "rfsp_eb": { num: 4, note: [1973, 1943, 2411, 3732], song: ["The Quick Brown Fox - Break (beary605) [Smash] {1.3x}", "YUC'e - Future Candy (Leo137) [Minty Fresh Pack 1] {1.5x}", "Shiraishi - Moon-gate (ATTang) [ATTang's Bad Files] {1.25x}", "DJ Sharpnel - Pacific Girls (Fullerene- & IcyWorld) [Nuclear Blast JS Awesome Bomb Filez 5] {1.5x // cut}"] },
    """
    dan_notes = {
        "ln1": [4, 717, 336, 176, 613, 893, 512, 282, 1014],
        "ln10": [4, 2377, 1656, 1689, 2185, 3925, 3120, 3366, 3655],
        "ln11": [4, 1864, 1493, 2338, 2529, 3507, 2512, 4430, 4525],
        "ln12": [4, 1798, 2633, 1822, 2449, 2986, 4811, 3552, 4390],
        "ln13": [4, 2570, 2452, 2123, 2818, 4725, 4203, 3651, 5061],
        "ln14": [4, 2319, 2408, 2483, 2158, 4415, 4320, 4318, 3947],
        "ln15": [4, 3216, 3209, 3278, 3149, 6153, 5661, 5904, 5963],
        "ln2": [4, 805, 805, 377, 805, 1184, 1414, 705, 1610],
        "ln3": [4, 836, 921, 612, 1157, 1305, 1342, 880, 1695],
        "ln4": [4, 907, 1053, 413, 1067, 1469, 1605, 781, 2133],
        "ln5": [4, 1904, 887, 1380, 1220, 2956, 1613, 1913, 1881],
        "ln6": [4, 1365, 745, 1219, 1534, 2324, 1412, 1891, 2421],
        "ln7": [4, 1394, 1119, 832, 1666, 2076, 1971, 1664, 2386],
        "ln8": [4, 1445, 1318, 1258, 1694, 2694, 2424, 2486, 2560],
        "ln9": [4, 2500, 1461, 1321, 2307, 4069, 2593, 2425, 3699],
        
        "xfpsb1": [4, 1675, 2107, 1569, 2146, 2755, 3979, 2982, 3687],
        "xfpsb2": [4, 2046, 1958, 2634, 2217, 3664, 3641, 4998, 4052],
        "xfpsb3": [4, 2568, 1839, 2636, 2235, 4755, 3491, 4816, 4185],
        "xfpsb4": [4, 2279, 1761, 2291, 2233, 4096, 2983, 3909, 4037],
        "xfpsb5": [4, 2210, 2190, 1943, 2594, 4250, 3931, 3664, 4695],
        "xfpsb6": [4, 2633, 3043, 2800, 2611, 5135, 5491, 5362, 4989],
        "xfpsbf": [4, 2708, 2555, 2583, 2954, 5145, 4797, 4898, 5381],
        
        "7k0dan": [4, 1018, 851, 1023, 1223],
        "7k1dan": [4, 1436, 1814, 1312, 1673],
        "7k10dan": [4, 3081, 2366, 2511, 3438],
        "7k2dan": [4, 1411, 1436, 1784, 2154],
        "7k3dan": [4, 1970, 1906, 1871, 1982],
        "7k4dan": [4, 2189, 1853, 2108, 2264],
        "7k5dan": [4, 2087, 2166, 1975, 2391],
        "7k6dan": [4, 1576, 2818, 2368, 3003],
        "7k7dan": [4, 2689, 2876, 1938, 2847],
        "7k8dan": [4, 2366, 2508, 2825, 2936],
        "7k9dan": [4, 2420, 2672, 2230, 3343],
        "7ka": [4, 3644, 3174, 3260, 4141],
        "7kg": [4, 3085, 2500, 2707, 3711],
        "7ks": [4, 4000, 4502, 3314, 4568],
        "7kz": [4, 3624, 2722, 3258, 4974],
        
        "7kln0": [4, 820, 600, 215, 247, 1122, 898, 430, 424],
        "7kln1": [4, 1068, 682, 537, 428, 1819, 1075, 1074, 707],
        "7kln10": [4, 2151, 2496, 1845, 1708, 4297, 4812, 3690, 3402],
        "7kln2": [4, 1242, 1198, 760, 1221, 1598, 1831, 1520, 2315],
        "7kln3": [4, 1512, 1350, 323, 899, 2358, 2106, 646, 1606],
        "7kln4": [4, 1309, 1518, 543, 736, 2129, 2724, 1086, 1381],
        "7kln5": [4, 1516, 2695, 602, 618, 2687, 4695, 1204, 1059],
        "7kln6": [4, 1635, 1902, 756, 1081, 2829, 3488, 1512, 2060],
        "7kln7": [4, 1796, 2093, 1359, 1391, 3386, 3475, 2718, 2738],
        "7kln8": [4, 2230, 2136, 1465, 1362, 4238, 3638, 2930, 2603],
        "7kln9": [4, 1900, 2159, 1597, 1677, 3601, 4213, 3194, 3341],
        "7klna": [4, 3029, 2472, 2553, 2926, 5867, 4915, 5106, 5849],
        "7klng": [4, 2551, 2326, 2273, 2165, 4962, 4505, 4546, 4306],
        "7klns": [4, 4073, 3454, 3196, 3721, 6954, 6325, 6392, 7391],
        "7klnz": [4, 3240, 3025, 3181, 2904, 6314, 5918, 6362, 5756],
        
        "haku": [4, 2379, 3073, 3561, 962],
        
        "1danv2": [4, 831, 955, 907, 654],
        "10danv2": [4, 2659, 2188, 2194, 2187],
        "2danv2": [4, 1152, 850, 950, 969],
        "3danv2": [4, 1169, 1143, 974, 1347],
        "4danv2": [4, 1400, 1402, 1685, 1599],
        "5danv2": [4, 1953, 2250, 2166, 1667],
        "6danv2": [4, 1487, 1424, 1381, 1587],
        "7danv2": [4, 1909, 1814, 1777, 2681],
        "8danv2": [4, 1962, 1067, 2388, 1772],
        "9danv2": [4, 1799, 2023, 2281, 1787],
        
        "ex1v2": [4, 2164, 1952, 1823, 3249],
        "ex2v2": [4, 2871, 2024, 1871, 2452],
        "ex2v1.5": [4, 2457, 2239, 2024, 2561],
        "ex2v1.75": [4, 1944, 2024, 2561, 3089],
        "ex3v2": [4, 2327, 1593, 2166, 2200],
        "ex4v2": [4, 2731, 2653, 2033, 2796],
        "ex5v2": [4, 3229, 2731, 2561, 2109],
        "ex6v2": [4, 1766, 1861, 3171, 1680],
        "ex6v1.75": [4, 2504, 2027, 2444, 3526],
        "ex7v2": [4, 2339, 2461, 2511, 2177],
        "ex7v1.75": [4, 2725, 2166, 2545, 3691],
        "ex8v2": [4, 1929, 2380, 2710, 4675],
        "ex9v2": [4, 3987, 1874, 4363, 3843],
        "ex9v1.75": [4, 4427, 3660, 4323, 3044],
        "exfv2": [4, 3468, 3335, 3698, 5061],
        
        "spex1": [4, 1952, 2316, 2098, 2048],
        "spex2": [4, 2158, 1953, 2196, 3160],
        "spex3": [4, 2299, 2378, 2677, 2640],
        "spex4": [4, 1738, 1876, 2079, 2008],
        "spex5": [4, 2731, 2109, 2365, 2691],
        "spex6": [4, 1766, 2525, 2167, 3214],
        "spex7": [4, 2339, 2461, 2142, 3167],
        "spex8": [4, 2647, 3253, 3204, 4046],
        "spex9": [4, 2828, 3663, 2865, 2777],
        
        "0danv3": [4, 492, 529, 595, 681],
        "1danv3": [4, 695, 621, 718, 1279],
        "10danv3": [4, 2034, 1740, 2270, 2166],
        "2danv3": [4, 1397, 1090, 805, 1212],
        "3danv3": [4, 1055, 1489, 1288, 1789],
        "4danv3": [4, 1865, 1434, 1284, 1839],
        "5danv3": [4, 1282, 1706, 1473, 1939],
        "6danv3": [4, 1694, 1636, 1803, 2115],
        "7danv3": [4, 1701, 1799, 2132, 1899],
        "8danv3": [4, 2237, 2081, 2280, 2000],
        "9danv3": [4, 2374, 1889, 2142, 1810],
        
        "ex1v3": [4, 1952, 2013, 1953, 2111],
        "ex2v3": [4, 2107, 1953, 2386, 2674],
        "ex3v3": [4, 2518, 2636, 2326, 2511],
        "ex4v3": [4, 2634, 2212, 2336, 2602],
        "ex5v3": [4, 2734, 2417, 3089, 2974],
        "ex6v3": [4, 2483, 2276, 2921, 3194],
        "ex7v3": [4, 2846, 2260, 2333, 3347],
        "ex8v3": [4, 3789, 3663, 2424, 3255],
        "ex9v3": [4, 3888, 3030, 3581, 3700],
        "exfv3": [4, 2828, 3362, 3393, 5100],
        
        "rf1": [4, 878, 696, 954, 1167],
        "rf10": [4, 1906, 1460, 1723, 2392],
        "rf2": [4, 1107, 905, 955, 1487],
        "rf3": [4, 1008, 797, 1047, 1259],
        "rf4": [4, 905, 1499, 1283, 2071],
        "rf5": [4, 1293, 1722, 1632, 1903],
        "rf6": [4, 1487, 1266, 1378, 2186],
        "rf7": [4, 2114, 1777, 1081, 2734],
        "rf8": [4, 2177, 1309, 1608, 1589],
        "rf9": [4, 2114, 2070, 1674, 2272],
        "alpha": [4, 2265, 1528, 2300, 3334],
        "beta": [4, 2274, 2308, 1740, 2301],
        "delta": [4, 2018, 2711, 3268, 2629],
        "epsilon": [4, 2128, 2552, 2194, 2829],
        "gamma": [4, 1973, 1980, 1429, 3979],
        "eta": [4, 3889, 3860, 3863, 3837],
        "zeta": [4, 3447, 3424, 3409, 3291],
        "spz": [4, 2438, 1964, 2925, 3497],
        
        "senpai1": [4, 752, 1004, 940, 1045],
        "senpai10": [4, 1933, 1929, 1734, 1930],
        "senpai2": [4, 978, 791, 1440, 1405],
        "senpai3": [4, 1242, 1297, 1358, 1378],
        "senpai4": [4, 1848, 1592, 1558, 1677],
        "senpai5": [4, 1536, 1877, 1841, 1583],
        "senpai6": [4, 1523, 1705, 1722, 2111],
        "senpai7": [4, 1464, 1509, 2052, 2076],
        "senpai8": [4, 1811, 1771, 2211, 2021],
        "senpai9": [4, 2096, 1955, 2091, 1957],
        "senpaiex1": [4, 2425, 1733, 1978, 2233],
        "senpaiex2": [4, 2428, 2632, 1799, 2668],
        "senpaiex3": [4, 2148, 2932, 2975, 2052],
        "senpaiex4": [4, 2362, 2064, 1996, 2752],
        "senpaiex5": [4, 2715, 2181, 2350, 3748],
        "senpaiex6": [4, 2472, 2179, 2573, 2606],
        "senpaiex7": [4, 2816, 2516, 2867, 3503],
        "senpaiex8": [4, 3131, 2211, 2689, 3552],
        "senpaiex9": [4, 3486, 3175, 3592, 3189],
        "senpaiexf": [4, 4207, 3352, 3080, 3450],
        
        "wds0_1": [4, 2100, 2050, 2344, 2236],
        "wds0_10": [4, 4099, 3284, 3212, 3200],
        "wds0_2": [4, 2148, 3246, 2054, 2125],
        "wds0_3": [4, 2434, 2952, 2735, 2312],
        "wds0_4": [4, 2229, 2585, 2022, 2552],
        "wds0_5": [5, 2597, 3050, 2453, 2361, 2492],
        "wds0_6": [4, 2581, 3165, 2524, 2513],
        "wds0_7": [4, 2824, 3045, 3280, 3073],
        "wds0_8": [4, 3407, 3493, 3195, 2087],
        "wds0_9": [4, 4444, 2602, 2853, 2411],
        "wds0_f": [5, 3699, 2966, 5315, 4643, 8438],
        "wds0_j": [4, 3372, 3940, 2680, 2467],
        "wds0_n": [4, 3134, 2504, 1040, 2398],
    }

# 星数段位匹配数据        
class sr_intervals_data:
    LN_intervals_4K = [
        (4.832, 4.898, "LN 5 mid"),
        (4.898, 4.963, "LN 5 mid/high"),
        (4.963, 5.095, "LN 5 high"),
        (5.095, 5.160, "LN 6 low"),
        (5.160, 5.143, "LN 6 mid/low"),
        (5.143, 5.213, "LN 6 mid"),
        (5.213, 5.264, "LN 6 mid/high"),
        (5.264, 5.314, "LN 6 high"),
        (5.314, 5.446, "LN 7 low"),
        (5.446, 5.521, "LN 7 mid/low"),
        (5.521, 5.577, "LN 7 mid"),
        (5.577, 5.631, "LN 7 mid/high"),
        (5.631, 5.686, "LN 7 high"),
        (5.686, 5.740, "LN 8 low"),
        (5.740, 5.794, "LN 8 mid/low"),
        (5.794, 5.853, "LN 8 mid"),
        (5.853, 5.917, "LN 8 mid/high"),
        (5.917, 5.981, "LN 8 high"),
        (5.981, 6.044, "LN 9 low"),
        (6.044, 6.108, "LN 9 mid/low"),
        (6.108, 6.175, "LN 9 mid"),
        (6.175, 6.246, "LN 9 mid/high"),
        (6.246, 6.318, "LN 9 high"),
        (6.318, 6.389, "LN 10 low"),
        (6.389, 6.461, "LN 10 mid/low"),
        (6.461, 6.534, "LN 10 mid"),
        (6.534, 6.611, "LN 10 mid/high"),
        (6.611, 6.687, "LN 10 high"),
        (6.687, 6.763, "LN 11 low"),
        (6.763, 6.839, "LN 11 mid/low"),
        (6.839, 6.898, "LN 11 mid"),
        (6.898, 6.920, "LN 11 mid/high"),
        (6.920, 6.941, "LN 11 high"),
        (6.941, 7.023, "LN 12 low"),
        (7.023, 7.068, "LN 12 mid/low"),
        (7.068, 7.136, "LN 12 mid"),
        (7.136, 7.225, "LN 12 mid/high"),
        (7.225, 7.313, "LN 12 high"),
        (7.313, 7.401, "LN 13 low"),
        (7.401, 7.490, "LN 13 mid/low"),
        (7.490, 7.578, "LN 13 mid"),
        (7.578, 7.665, "LN 13 mid/high"),
        (7.665, 7.753, "LN 13 high"),
        (7.753, 7.841, "LN 14 low"),
        (7.841, 7.929, "LN 14 mid/low"),
        (7.929, 8.013, "LN 14 mid"),
        (8.013, 8.093, "LN 14 mid/high"),
        (8.093, 8.173, "LN 14 high"),
        (8.173, 8.253, "LN 15 low"),
        (8.253, 8.333, "LN 15 mid/low"),
        (8.333, 8.389, "LN 15 mid"),
        (8.389, 8.428, "LN 15 mid/high"),
        (8.428, 8.470, "LN 15 high"),
        (8.470, 8.509, "Hypersovae LN 16 low"),
        (8.509, 8.548, "Hypersovae LN 16 mid/low"),
        (8.548, 8.586, "Hypersovae LN 16 mid"),
        (8.586, 8.635, "Hypersovae LN 16 mid/high"),
        (8.635, 8.908, "Hypersovae LN 16 high"),
        (8.908, 9.044, "Lnlism LN 17 low"),
        (9.044, 9.180, "Lnlism LN 17 mid/low"),
        (9.180, 9.316, "Lnlism LN 17 mid"),
        (9.316, 9.452, "Lnlism LN 17 mid/high"),
        (9.452, 9.589, "Lnlism LN 17 high"),
    ]
    RC_intervals_4K = [
        (1.502, 1.631, "Intro 1 low"),
        (1.631, 1.760, "Intro 1 mid/low"),
        (1.760, 1.890, "Intro 1 mid"),
        (1.890, 2.019, "Intro 1 mid/high"),
        (2.019, 2.148, "Intro 1 high"),
        (2.148, 2.278, "Intro 2 low"),
        (2.278, 2.407, "Intro 2 mid/low"),
        (2.407, 2.502, "Intro 2 mid"),
        (2.502, 2.560, "Intro 2 mid/high"),
        (2.560, 2.619, "Intro 2 high"),
        (2.619, 2.679, "Intro 3 low"),
        (2.679, 2.737, "Intro 3 mid/low"),
        (2.737, 2.821, "Intro 3 mid"),
        (2.821, 2.929, "Intro 3 mid/high"),
        (2.929, 3.037, "Intro 3 high"),
        (3.037, 3.145, "Reform 1 low"),
        (3.145, 3.253, "Reform 1 mid/low"),
        (3.253, 3.346, "Reform 1 mid"),
        (3.346, 3.424, "Reform 1 mid/high"),
        (3.424, 3.503, "Reform 1 high"),
        (3.503, 3.581, "Reform 2 low"),
        (3.581, 3.659, "Reform 2 mid/low"),
        (3.659, 3.701, "Reform 2 mid"),
        (3.701, 3.708, "Reform 2 mid/high"),
        (3.708, 3.714, "Reform 2 high"),
        (3.714, 3.720, "Reform 3 low"),
        (3.720, 3.727, "Reform 3 mid/low"),
        (3.727, 3.810, "Reform 3 mid"),
        (3.810, 3.970, "Reform 3 mid/high"),
        (3.970, 4.130, "Reform 3 high"),
        (4.130, 4.290, "Reform 4 low"),
        (4.290, 4.450, "Reform 4 mid/low"),
        (4.450, 4.569, "Reform 4 mid"),
        (4.569, 4.648, "Reform 4 mid/high"),
        (4.648, 4.726, "Reform 4 high"),
        (4.726, 4.804, "Reform 5 low"),
        (4.804, 4.883, "Reform 5 mid/low"),
        (4.883, 4.972, "Reform 5 mid"),
        (4.972, 5.072, "Reform 5 mid/high"),
        (5.072, 5.173, "Reform 5 high"),
        (5.173, 5.273, "Reform 6 low"),
        (5.273, 5.373, "Reform 6 mid/low"),
        (5.373, 5.441, "Reform 6 mid"),
        (5.441, 5.476, "Reform 6 mid/high"),
        (5.476, 5.511, "Reform 6 high"),
        (5.511, 5.547, "Reform 7 low"),
        (5.547, 5.582, "Reform 7 mid/low"),
        (5.582, 5.646, "Reform 7 mid"),
        (5.646, 5.738, "Reform 7 mid/high"),
        (5.738, 5.829, "Reform 7 high"),
        (5.829, 5.921, "Reform 8 low"),
        (5.921, 6.013, "Reform 8 mid/low"),
        (6.013, 6.069, "Reform 8 mid"),
        (6.069, 6.090, "Reform 8 mid/high"),
        (6.090, 6.110, "Reform 8 high"),
        (6.110, 6.130, "Reform 9 low"),
        (6.130, 6.151, "Reform 9 mid/low"),
        (6.151, 6.205, "Reform 9 mid"),
        (6.205, 6.294, "Reform 9 mid/high"),
        (6.294, 6.382, "Reform 9 high"),
        (6.382, 6.471, "Reform 10 low"),
        (6.471, 6.560, "Reform 10 mid/low"),
        (6.560, 6.616, "Reform 10 mid"),
        (6.616, 6.641, "Reform 10 mid/high"),
        (6.641, 6.666, "Reform 10 high"),
        (6.666, 6.691, "Alpha low"),
        (6.691, 6.716, "Alpha mid/low"),
        (6.716, 6.773, "Alpha mid"),
        (6.773, 6.860, "Alpha mid/high"),
        (6.860, 6.947, "Alpha high"),
        (6.947, 7.034, "Beta low"),
        (7.034, 7.121, "Beta mid/low"),
        (7.121, 7.214, "Beta mid"),
        (7.214, 7.312, "Beta mid/high"),
        (7.312, 7.410, "Beta high"),
        (7.410, 7.509, "Gamma low"),
        (7.509, 7.607, "Gamma mid/low"),
        (7.607, 7.705, "Gamma mid"),
        (7.705, 7.803, "Gamma mid/high"),
        (7.803, 7.901, "Gamma high"),
        (7.901, 8.000, "Delta low"),
        (8.000, 8.098, "Delta mid/low"),
        (8.098, 8.244, "Delta mid"),
        (8.244, 8.438, "Delta mid/high"),
        (8.438, 8.631, "Delta high"),
        (8.631, 8.825, "Epsilon low"),
        (8.825, 9.019, "Epsilon mid/low"),
        (9.019, 9.172, "Epsilon mid"),
        (9.172, 9.285, "Epsilon mid/high"),
        (9.285, 9.398, "Epsilon high"),
        (9.398, 9.511, "Emik Zeta low"),
        (9.511, 9.624, "Emik Zeta mid/low"),
        (9.624, 9.742, "Emik Zeta mid"),
        (9.742, 9.867, "Emik Zeta mid/high"),
        (9.867, 9.991, "Emik Zeta high"),
        (9.991, 10.116, "Thaumiel Eta low"),
        (10.116, 10.241, "Thaumiel Eta mid/low"),
        (10.241, 10.358, "Thaumiel Eta mid"),
        (10.358, 10.468, "Thaumiel Eta mid/high"),
        (10.468, 10.578, "Thaumiel Eta high"),
        (10.578, 10.689, "CloverWisp Theta low"),
        (10.689, 10.799, "CloverWisp Theta mid/low"),
        (10.799, 10.909, "CloverWisp Theta mid"),
        (10.909, 11.019, "CloverWisp Theta mid/high"),
        (11.019, 11.129, "CloverWisp Theta high"),
    ]
    LN_intervals_6K = [
        (3.530, 3.718, 'LN 0 low'),
        (3.718, 3.906, 'LN 0 mid/low'),
        (3.906, 4.094, 'LN 0 mid'),
        (4.094, 4.282, 'LN 0 mid/high'),
        (4.282, 4.470, 'LN 0 high'),
        (4.470, 4.658, 'LN 1 low'),
        (4.658, 4.846, 'LN 1 mid/low'),
        (4.846, 4.974, 'LN 1 mid'),
        (4.974, 5.042, 'LN 1 mid/high'),
        (5.042, 5.110, 'LN 1 high'),
        (5.110, 5.178, 'LN 2 low'),
        (5.178, 5.246, 'LN 2 mid/low'),
        (5.246, 5.294, 'LN 2 mid'),
        (5.294, 5.322, 'LN 2 mid/high'),
        (5.322, 5.350, 'LN 2 high'),
        (5.350, 5.378, 'LN 3 low'),
        (5.378, 5.406, 'LN 3 mid/low'),
        (5.406, 5.513, 'LN 3 mid'),
        (5.513, 5.699, 'LN 3 mid/high'),
        (5.699, 5.885, 'LN 3 high'),
        (5.885, 6.071, 'LN 4 low'),
        (6.071, 6.257, 'LN 4 mid/low'),
        (6.257, 6.347, 'LN 4 mid'),
        (6.347, 6.341, 'LN 4 mid/high'),
        (6.341, 6.335, 'LN 4 high'),
        (6.335, 6.329, 'LN 5 low'),
        (6.329, 6.323, 'LN 5 mid/low'),
        (6.323, 6.371, 'LN 5 mid'),
        (6.371, 6.473, 'LN 5 mid/high'),
        (6.473, 6.575, 'LN 5 high'),
        (6.575, 6.677, 'LN 6 low'),
        (6.677, 6.779, 'LN 6 mid/low'),
        (6.779, 6.840, 'LN 6 mid'),
        (6.840, 6.860, 'LN 6 mid/high'),
        (6.860, 6.880, 'LN 6 high'),
        (6.880, 6.900, 'LN 7 low'),
        (6.900, 6.920, 'LN 7 mid/low'),
        (6.920, 6.973, 'LN 7 mid'),
        (6.973, 7.059, 'LN 7 mid/high'),
        (7.059, 7.145, 'LN 7 high'),
        (7.145, 7.231, 'LN 8 low'),
        (7.231, 7.317, 'LN 8 mid/low'),
        (7.317, 7.366, 'LN 8 mid'),
        (7.366, 7.378, 'LN 8 mid/high'),
        (7.378, 7.390, 'LN 8 high'),
        (7.390, 7.402, 'LN 9 low'),
        (7.402, 7.414, 'LN 9 mid/low'),
        (7.414, 7.469, 'LN 9 mid'),
        (7.469, 7.567, 'LN 9 mid/high'),
        (7.567, 7.665, 'LN 9 high'),
        (7.665, 7.763, 'LN Terra low'),
        (7.763, 7.861, 'LN Terra mid/low'),
        (7.861, 7.952, 'LN Terra mid'),
        (7.952, 8.036, 'LN Terra mid/high'),
        (8.036, 8.120, 'LN Terra high'),
        (8.120, 8.204, 'LN Celestial low'),
        (8.204, 8.288, 'LN Celestial mid/low'),
        (8.288, 8.367, 'LN Celestial mid'),
        (8.367, 8.441, 'LN Celestial mid/high'),
        (8.441, 8.515, 'LN Celestial high'),
        (8.515, 8.589, 'LN Mystery low'),
        (8.589, 8.663, 'LN Mystery mid/low'),
        (8.663, 8.737, 'LN Mystery mid'),
        (8.737, 8.811, 'LN Mystery mid/high'),
        (8.811, 8.885, 'LN Mystery high'),
        (8.885, 8.959, 'LN Nihility low'),
        (8.959, 9.033, 'LN Nihility mid/low'),
        (9.033, 9.112, 'LN Nihility mid'),
        (9.112, 9.196, 'LN Nihility mid/high'),
        (9.196, 9.280, 'LN Nihility high'),
        (9.280, 9.364, 'LN Finish low'),
        (9.364, 9.448, 'LN Finish mid/low'),
        (9.448, 9.532, 'LN Finish mid'),
        (9.532, 9.616, 'LN Finish mid/high'),
        (9.616, 9.700, 'LN Finish high'),
    ]
    RC_intervals_6K = [
        (3.430, 3.526, 'Regular 0 low'),
        (3.526, 3.622, 'Regular 0 mid/low'),
        (3.622, 3.718, 'Regular 0 mid'),
        (3.718, 3.814, 'Regular 0 mid/high'),
        (3.814, 3.910, 'Regular 0 high'),
        (3.910, 4.006, 'Regular 1 low'),
        (4.006, 4.102, 'Regular 1 mid/low'),
        (4.102, 4.210, 'Regular 1 mid'),
        (4.210, 4.330, 'Regular 1 mid/high'),
        (4.330, 4.450, 'Regular 1 high'),
        (4.450, 4.570, 'Regular 2 low'),
        (4.570, 4.690, 'Regular 2 mid/low'),
        (4.690, 4.831, 'Regular 2 mid'),
        (4.831, 4.993, 'Regular 2 mid/high'),
        (4.993, 5.155, 'Regular 2 high'),
        (5.155, 5.317, 'Regular 3 low'),
        (5.317, 5.479, 'Regular 3 mid/low'),
        (5.479, 5.590, 'Regular 3 mid'),
        (5.590, 5.650, 'Regular 3 mid/high'),
        (5.650, 5.710, 'Regular 3 high'),
        (5.710, 5.770, 'Regular 4 low'),
        (5.770, 5.830, 'Regular 4 mid/low'),
        (5.830, 5.919, 'Regular 4 mid'),
        (5.919, 6.037, 'Regular 4 mid/high'),
        (6.037, 6.155, 'Regular 4 high'),
        (6.155, 6.273, 'Regular 5 low'),
        (6.273, 6.391, 'Regular 5 mid/low'),
        (6.391, 6.490, 'Regular 5 mid'),
        (6.490, 6.570, 'Regular 5 mid/high'),
        (6.570, 6.650, 'Regular 5 high'),
        (6.650, 6.730, 'Regular 6 low'),
        (6.730, 6.810, 'Regular 6 mid/low'),
        (6.810, 6.873, 'Regular 6 mid'),
        (6.873, 6.919, 'Regular 6 mid/high'),
        (6.919, 6.965, 'Regular 6 high'),
        (6.965, 7.011, 'Regular 7 low'),
        (7.011, 7.057, 'Regular 7 mid/low'),
        (7.057, 7.119, 'Regular 7 mid'),
        (7.119, 7.197, 'Regular 7 mid/high'),
        (7.197, 7.275, 'Regular 7 high'),
        (7.275, 7.353, 'Regular 8 low'),
        (7.353, 7.431, 'Regular 8 mid/low'),
        (7.431, 7.503, 'Regular 8 mid'),
        (7.503, 7.569, 'Regular 8 mid/high'),
        (7.569, 7.635, 'Regular 8 high'),
        (7.635, 7.701, 'Regular 9 low'),
        (7.701, 7.767, 'Regular 9 mid/low'),
        (7.767, 7.833, 'Regular 9 mid'),
        (7.833, 7.899, 'Regular 9 mid/high'),
        (7.899, 7.965, 'Regular 9 high'),
    ]
    LN_intervals_7K = [
        (4.836, 4.9704, 'LN 3 low'), 
        (4.9704, 5.1048, 'LN 3 mid/low'), 
        (5.1048, 5.2392, 'LN 3 mid'), 
        (5.2392, 5.3736, 'LN 3 mid/high'), 
        (5.3736, 5.508, 'LN 3 high'), 
        (5.508, 5.5592, 'LN 4 low'), 
        (5.5592, 5.6104, 'LN 4 mid/low'), 
        (5.6104, 5.6616, 'LN 4 mid'), 
        (5.6616, 5.7128, 'LN 4 mid/high'), 
        (5.7128, 5.764, 'LN 4 high'),
        (5.764, 5.8824, 'LN 5 low'), 
        (5.8824, 6.0008, 'LN 5 mid/low'), 
        (6.0008, 6.1192, 'LN 5 mid'), 
        (6.1192, 6.2376, 'LN 5 mid/high'),
        (6.2376, 6.356, 'LN 5 high'), 
        (6.356, 6.4708, 'LN 6 low'), 
        (6.4708, 6.5856, 'LN 6 mid/low'),
        (6.5856, 6.7004, 'LN 6 mid'), 
        (6.7004, 6.8152, 'LN 6 mid/high'), 
        (6.8152, 6.93, 'LN 6 high'), 
        (6.93, 6.9372, 'LN 7 low'), 
        (6.9372, 6.9444, 'LN 7 mid/low'), 
        (6.9444, 6.9516, 'LN 7 mid'), 
        (6.9516, 6.9588, 'LN 7 mid/high'), 
        (6.9588, 7.053, 'LN 7 high'), 
        (7.053, 7.1472, 'LN 8 low'), 
        (7.1472, 7.2414, 'LN 8 mid/low'), 
        (7.2414, 7.3356, 'LN 8 mid'), 
        (7.3356, 7.4298, 'LN 8 mid/high'), 
        (7.4298, 7.4872, 'LN 8 high'), 
        (7.4872, 7.5446, 'LN 9 low'), 
        (7.5446, 7.602, 'LN 9 mid/low'), 
        (7.602, 7.6594, 'LN 9 mid'), 
        (7.6594, 7.7168, 'LN 9 mid/high'), 
        (7.7168, 7.8572, 'LN 9 high'), 
        (7.8572, 7.9976, 'LN 10 low'), 
        (7.9976, 8.138, 'LN 10 mid/low'), 
        (8.138, 8.2784, 'LN 10 mid'), 
        (8.2784, 8.4188, 'LN 10 mid/high'), 
        (8.4188, 8.4938, 'LN 10 high'), 
        (8.4938, 8.5688, 'LN Gamma low'),
        (8.5688, 8.6438, 'LN Gamma mid/low'), 
        (8.6438, 8.7188, 'LN Gamma mid'), 
        (8.7188, 8.7938, 'LN Gamma mid/high'),
        (8.7938, 8.8878, 'LN Gamma high'), 
        (8.8878, 8.9818, 'LN Azimuth low'), 
        (8.9818, 9.0758, 'LN Azimuth mid/low'),
        (9.0758, 9.1698, 'LN Azimuth mid'),
        (9.1698, 9.2638, 'LN Azimuth mid/high'),
        (9.2638, 9.3784, 'LN Azimuth high'), 
        (9.3784, 9.493, 'LN Zenith low'), 
        (9.493, 9.6076, 'LN Zenith mid/low'), 
        (9.6076, 9.7222, 'LN Zenith mid'),
        (9.7222, 9.8368, 'LN Zenith mid/high'),
        (9.8368, 9.975, 'LN Zenith high'), 
        (9.975, 10.1132, 'LN Stellium low'), 
        (10.1132, 10.2514, 'LN Stellium mid/low'),
        (10.2514, 10.3896, 'LN Stellium mid'), 
        (10.3896, 10.5278, 'LN Stellium mid/high'), 
        (10.5278, 10.666, 'LN Stellium high')
        ]
    RC_intervals_7K = [
        (3.5085, 3.6631, 'Regular 0 low'), 
        (3.6631, 3.8177, 'Regular 0 mid/low'), 
        (3.8177, 3.9723, 'Regular 0 mid'), 
        (3.9723, 4.1269, 'Regular 0 mid/high'), 
        (4.1269, 4.2815, 'Regular 0 high'), 
        (4.2815, 4.4361, 'Regular 1 low'), 
        (4.4361, 4.5907, 'Regular 1 mid/low'), 
        (4.5907, 4.7202, 'Regular 1 mid'), 
        (4.7202, 4.8246, 'Regular 1 mid/high'), 
        (4.8246, 4.929, 'Regular 1 high'), 
        (4.929, 5.0334, 'Regular 2 low'), 
        (5.0334, 5.1378, 'Regular 2 mid/low'), 
        (5.1378, 5.2379, 'Regular 2 mid'), 
        (5.2379, 5.3337, 'Regular 2 mid/high'), 
        (5.3337, 5.4295, 'Regular 2 high'), 
        (5.4295, 5.5253, 'Regular 3 low'), 
        (5.5253, 5.6211, 'Regular 3 mid/low'), 
        (5.6211, 5.6927, 'Regular 3 mid'), 
        (5.6927, 5.7401, 'Regular 3 mid/high'), 
        (5.7401, 5.7875, 'Regular 3 high'), 
        (5.7875, 5.8349, 'Regular 4 low'), 
        (5.8349, 5.8823, 'Regular 4 mid/low'), 
        (5.8823, 5.9313, 'Regular 4 mid'), 
        (5.9313, 5.9819, 'Regular 4 mid/high'), 
        (5.9819, 6.0325, 'Regular 4 high'), 
        (6.0325, 6.0831, 'Regular 5 low'), 
        (6.0831, 6.1337, 'Regular 5 mid/low'), 
        (6.1337, 6.2176, 'Regular 5 mid'), 
        (6.2176, 6.3348, 'Regular 5 mid/high'), 
        (6.3348, 6.452, 'Regular 5 high'), 
        (6.452, 6.5692, 'Regular 6 low'), 
        (6.5692, 6.6864, 'Regular 6 mid/low'), 
        (6.6864, 6.7772, 'Regular 6 mid'), 
        (6.7772, 6.8416, 'Regular 6 mid/high'), 
        (6.8416, 6.906, 'Regular 6 high'), 
        (6.906, 6.9704, 'Regular 7 low'), 
        (6.9704, 7.0348, 'Regular 7 mid/low'), 
        (7.0348, 7.1085, 'Regular 7 mid'), 
        (7.1085, 7.1915, 'Regular 7 mid/high'), 
        (7.1915, 7.2745, 'Regular 7 high'), 
        (7.2745, 7.3575, 'Regular 8 low'), 
        (7.3575, 7.4405, 'Regular 8 mid/low'), 
        (7.4405, 7.5096, 'Regular 8 mid'), 
        (7.5096, 7.5648, 'Regular 8 mid/high'), 
        (7.5648, 7.62, 'Regular 8 high'), 
        (7.62, 7.6752, 'Regular 9 low'), 
        (7.6752, 7.7304, 'Regular 9 mid/low'), 
        (7.7304, 7.8134, 'Regular 9 mid'), 
        (7.8134, 7.9242, 'Regular 9 mid/high'), 
        (7.9242, 8.035, 'Regular 9 high'),
        (8.035, 8.1458, 'Regular 10 low'), 
        (8.1458, 8.2566, 'Regular 10 mid/low'), 
        (8.2566, 8.357, 'Regular 10 mid'), 
        (8.357, 8.447, 'Regular 10 mid/high'),
        (8.447, 8.537, 'Regular 10 high'), 
        (8.537, 8.627, 'Regular Gamma low'), 
        (8.627, 8.717, 'Regular Gamma mid/low'),
        (8.717, 8.8079, 'Regular Gamma mid'),
        (8.8079, 8.8997, 'Regular Gamma mid/high'),
        (8.8997, 8.9915, 'Regular Gamma high'), 
        (8.9915, 9.0833, 'Regular Azimuth low'), 
        (9.0833, 9.1751, 'Regular Azimuth mid/low'),
        (9.1751, 9.2921, 'Regular Azimuth mid'), 
        (9.2921, 9.4343, 'Regular Azimuth mid/high'),
        (9.4343, 9.5765, 'Regular Azimuth high'), 
        (9.5765, 9.7187, 'Regular Zenith low'), 
        (9.7187, 9.8609, 'Regular Zenith mid/low'), 
        (9.8609, 9.9728, 'Regular Zenith mid'),
        (9.9728, 10.0544, 'Regular Zenith mid/high'),
        (10.0544, 10.136, 'Regular Zenith high'), 
        (10.136, 10.2176, 'Regular Stellium low'),
        (10.2176, 10.2992, 'Regular Stellium mid/low'), 
        (10.2992, 10.3808, 'Regular Stellium mid'), 
        (10.3808, 10.4624, 'Regular Stellium mid/high'), 
        (10.4624, 10.544, 'Regular Stellium high')
    ]
    

def _refresh_acc_help_page() -> None:
    """使用本地段位数据刷新 /omtk acc 第3页，避免循环导入。"""
    dan_list_text = "全部内置段位列表:\n" + format_dan_list_grouped(sorted(dan_data.dan_notes.keys()))
    for index, item in enumerate(omtk_help_data.help_text):
        cmd, cmd_name, page, total_pages, _ = item
        if cmd == "acc" and page == "3" and total_pages == "3":
            omtk_help_data.help_text[index] = (cmd, cmd_name, page, total_pages, dan_list_text)
            break


_refresh_acc_help_page()
