"""多因子动态权重：基于 ICIR 的 softmax（负 ICIR 截断为小正值）"""
from __future__ import annotations

import math


def _safe_icir(v) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 1e-6
    if not math.isfinite(x):
        return 1e-6
    return max(x, 1e-6)


def icir_weights(icir_map: dict[str, dict], temperature: float = 2.0) -> dict[str, float]:
    """
    icir_map: factor_name -> {"icir": float, ...}
    """
    names = []
    scores = []
    for name, meta in icir_map.items():
        icir = meta.get("icir")
        if icir is None:
            continue
        v = _safe_icir(icir)  # 负向因子仍给极小正权重，避免 softmax 出现 nan
        names.append(name)
        scores.append(v / temperature)
    if not names:
        return {}
    m = max(scores)
    exps = [math.exp(s - m) for s in scores]
    ssum = sum(exps) or 1.0
    return {names[i]: round(exps[i] / ssum, 4) for i in range(len(names))}
