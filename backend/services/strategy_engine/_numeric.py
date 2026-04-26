"""纯标准库数值工具，减少对 numpy 的依赖"""
from __future__ import annotations

import math
from typing import Any


def finite_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def safe_quantile(series, q: float, default: float = 0.0) -> float:
    """pandas Series.quantile 可能为 nan（全为缺失时）"""
    try:
        val = series.quantile(q)
        v = float(val)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def optional_positive_float(x: Any) -> float | None:
    """ATR 等：缺失或非正非有限则返回 None"""
    if x is None:
        return None
    try:
        v = float(x)
        if not math.isfinite(v) or v <= 0:
            return None
        return v
    except (TypeError, ValueError):
        return None
