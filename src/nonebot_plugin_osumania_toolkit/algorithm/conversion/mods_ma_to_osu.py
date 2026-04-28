from nonebot.log import logger

def malody_mods_to_osu_mods(malody_flags: int) -> tuple:
    """
    将 Malody 的 mods_flags 转换为 osu! 的 mod 整数值和mod列表。
    
    映射规则：
    - bit 1: Fair -> 忽略
    - bit 2: Luck -> Random (2097152)
    - bit 3: Flip -> Mirror (1073741824)
    - bit 4: Const -> 忽略
    - bit 5: Dash -> 忽略
    - bit 6: Rush -> DoubleTime (64)
    - bit 7: Hide -> Hidden (8)
    - bit 9: Slow -> 忽略
    - bit 10: Death -> 忽略
    """
    osu_mod = 0
    osu_mods = []
    
    if malody_flags & (1 << 1):   # Luck (bit 2)
        osu_mod |= 2097152
        osu_mods.append("Random")
    
    if malody_flags & (1 << 2):   # Flip（第 3 位）
        osu_mod |= 1073741824
        osu_mods.append("Mirror")
    
    if malody_flags & (1 << 5):   # Rush（第 6 位）
        osu_mod |= 64
        osu_mods.append("DoubleTime")
    
    if malody_flags & (1 << 6):   # Hide（第 7 位）
        osu_mod |= 8
        osu_mods.append("Hidden")

    
    # 不参与转换的 mods
    ignored_mods = []
    if malody_flags & (1 << 0):   # Fair（第 1 位）
        ignored_mods.append("Fair")
    if malody_flags & (1 << 3):   # Const（第 4 位）
        ignored_mods.append("Const")
    if malody_flags & (1 << 4):   # Dash（第 5 位）
        ignored_mods.append("Dash")
    if malody_flags & (1 << 8):   # Slow（第 9 位）
        ignored_mods.append("Slow")
    if malody_flags & (1 << 9):   # Death（第 10 位）
        ignored_mods.append("Death")
    
    if ignored_mods:
        logger.debug(f"忽略的 Malody mods: {', '.join(ignored_mods)}")
    
    if not osu_mods:
        osu_mods.append("NoMod")
        
    return osu_mod, osu_mods