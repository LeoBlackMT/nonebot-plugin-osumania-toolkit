from __future__ import annotations

from .calc import OfficialRunnerError

__all__ = [
    "OfficialRunnerError",
    "ETTNotManiaError",
    "ETTParseError",
    "ETTUnsupportedKeyError",
    "analyze_ett_chart",
    "analyze_ett_zip",
]


def __getattr__(name: str):
    if name in {"ETTNotManiaError", "ETTParseError", "ETTUnsupportedKeyError", "analyze_ett_chart", "analyze_ett_zip"}:
        from .ett import (  # imported lazily to keep estimator imports lightweight
            ETTNotManiaError,
            ETTParseError,
            ETTUnsupportedKeyError,
            analyze_ett_chart,
            analyze_ett_zip,
        )

        globals().update(
            {
                "ETTNotManiaError": ETTNotManiaError,
                "ETTParseError": ETTParseError,
                "ETTUnsupportedKeyError": ETTUnsupportedKeyError,
                "analyze_ett_chart": analyze_ett_chart,
                "analyze_ett_zip": analyze_ett_zip,
            }
        )
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
