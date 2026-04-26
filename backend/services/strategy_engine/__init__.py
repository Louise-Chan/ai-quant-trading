"""多因子 + 评估 + 动态权重 + ML + 回测 + 仓位风险（对齐 strategy.md）

避免在包初始化时导入 runner，防止与「直接执行 runner.py」时的循环导入。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from services.strategy_engine.runner import analyze_symbol as analyze_symbol

__all__ = ["analyze_symbol"]


def __getattr__(name: str) -> Any:
    if name == "analyze_symbol":
        from services.strategy_engine.runner import analyze_symbol

        return analyze_symbol
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
