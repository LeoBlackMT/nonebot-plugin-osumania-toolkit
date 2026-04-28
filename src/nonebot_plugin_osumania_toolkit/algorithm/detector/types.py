from dataclasses import dataclass, field

from ...parser.osr_file_parser import osr_file
from ...parser.osu_file_parser import osu_file


@dataclass(frozen=True)
class Signal:
    """单条规则信号。

    Args:
        rule_id: 规则唯一标识。
        cheat: 是否直接指向作弊。
        sus: 是否标记可疑。
        risk: 风险分增量。
        reason: 人类可读原因描述。

    Returns:
        None.
    """

    rule_id: str
    cheat: bool
    sus: bool
    risk: int = 0
    reason: str = ""


@dataclass(frozen=True)
class AnalysisResult:
    """统一的分析结果对象。

    Args:
        cheat: 是否判定作弊。
        sus: 是否判定可疑。
        reason: 单分析器原因文本。
        signals: 该分析器产生的规则信号。

    Returns:
        None.
    """

    cheat: bool
    sus: bool
    reason: str
    signals: list[Signal] = field(default_factory=list)


@dataclass(frozen=True)
class AnalysisContext:
    """分析上下文。

    Args:
        osr: 回放对象。
        osu: 谱面对象，可为 None。
        data: osr.get_data() 返回数据。

    Returns:
        None.
    """

    osr: osr_file
    osu: osu_file | None
    data: dict
