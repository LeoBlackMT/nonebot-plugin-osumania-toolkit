import asyncio
import traceback
from typing import Callable

from ...parser.osr_file_parser import osr_file
from ...parser.osu_file_parser import osu_file
from .delta import analyze_delta_t
from .spectrum import analyze_pulse_spectrum
from .time import analyze_time_domain
from .types import AnalysisContext

Analyzer = Callable[[AnalysisContext], dict]


def _time_adapter(ctx: AnalysisContext) -> dict:
    """适配时域分析器。

    Args:
        ctx: 分析上下文。

    Returns:
        分析结果字典。
    """

    return analyze_time_domain(ctx.data)


def _spectrum_adapter(ctx: AnalysisContext) -> dict:
    """适配频谱分析器。

    Args:
        ctx: 分析上下文。

    Returns:
        分析结果字典。
    """

    return analyze_pulse_spectrum(ctx.data)


def _delta_adapter(ctx: AnalysisContext) -> dict:
    """适配 delta 分析器。

    Args:
        ctx: 分析上下文。

    Returns:
        分析结果字典；无谱面时返回跳过结果。
    """

    if ctx.osu is None:
        return {"cheat": False, "sus": False, "reason": "未分析delta_t。", "signals": []}
    return analyze_delta_t(ctx.osr, ctx.osu)


def _run_pipeline(ctx: AnalysisContext, analyzers: list[Analyzer]) -> list[dict]:
    """按顺序执行分析流水线。

    Args:
        ctx: 分析上下文。
        analyzers: 分析器列表。

    Returns:
        各分析器结果列表。
    """

    return [analyzer(ctx) for analyzer in analyzers]


def analyze_cheating(osr: osr_file, osu: osu_file | None = None) -> dict:
    """综合入口：执行全部分析并聚合结论。

    Args:
        osr: 回放对象。
        osu: 谱面对象，可为空。

    Returns:
        综合结果字典，包含 cheat/sus/reasons/signals。

    Raises:
        下游分析器异常会向上传递。
    """

    ctx = AnalysisContext(osr=osr, osu=osu, data=osr.get_data())
    analyzers = [_time_adapter, _spectrum_adapter, _delta_adapter]
    result_list = _run_pipeline(ctx, analyzers)

    cheat = any(r.get("cheat", False) for r in result_list)
    sus = any(r.get("sus", False) for r in result_list)
    reasons = [r.get("reason", "") for r in result_list]

    signals = []
    for r in result_list:
        signals.extend(r.get("signals", []))

    return {
        "cheat": cheat,
        "sus": sus,
        "reasons": reasons,
        "signals": signals,
    }


async def run_analyze_cheating(osr_obj: osr_file, osu_obj: osu_file | None = None) -> dict:
    """异步入口：在线程池执行综合分析。

    Args:
        osr_obj: 回放对象。
        osu_obj: 谱面对象，可为空。

    Returns:
        综合结果字典。

    Raises:
        Exception: 分析阶段异常原样抛出。
    """

    loop = asyncio.get_running_loop()

    def wrapped() -> dict:
        """线程池包装函数。

        Args:
            无。

        Returns:
            综合分析结果。

        Raises:
            Exception: analyze_cheating 抛出的任意异常。
        """

        try:
            return analyze_cheating(osr_obj, osu_obj)
        except Exception:
            traceback.print_exc()
            raise

    return await loop.run_in_executor(None, wrapped)
