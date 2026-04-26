"""因子评估：滚动 IC / ICIR（时间序列维度，单标的）"""
from __future__ import annotations

import math

import pandas as pd  # pyright: ignore[reportMissingImports]


def forward_return(close: pd.Series) -> pd.Series:
    return close.pct_change().shift(-1)


def evaluate_factors_ic(
    df: pd.DataFrame,
    factor_cols: list[str],
    ic_window: int = 40,
    icir_window: int = 20,
) -> dict:
    """
    对每个因子计算：近期滚动 IC 均值、IC 波动、ICIR。
    IC 使用 Pearson 相关（因子值 vs 下一根 K 线收益），在滚动窗口内按时间截面等价于序列相关。
    """
    if df.empty or not factor_cols:
        return {"factors": {}, "note": "数据不足"}
    fwd = forward_return(df["close"])
    out = {}
    for col in factor_cols:
        if col not in df.columns:
            continue
        ic_series = df[col].rolling(ic_window, min_periods=max(15, ic_window // 2)).corr(fwd)
        ic_mean = ic_series.rolling(icir_window, min_periods=5).mean().iloc[-1]
        ic_std = ic_series.rolling(icir_window, min_periods=5).std().iloc[-1]
        ic_std_f = float(ic_std) if pd.notna(ic_std) else 0.0
        ic_mean_f = float(ic_mean) if pd.notna(ic_mean) else 0.0
        if ic_std_f > 1e-8:
            icir = ic_mean_f / ic_std_f
        else:
            icir = 0.0
        if not math.isfinite(icir):
            icir = 0.0
        out[col] = {
            "rolling_ic_latest": float(ic_series.iloc[-1]) if pd.notna(ic_series.iloc[-1]) else None,
            "ic_mean_recent": ic_mean_f if pd.notna(ic_mean) else None,
            "ic_std_recent": ic_std_f if ic_std_f > 0 else None,
            "icir": round(icir, 4),
        }
    return {"factors": out, "ic_window": ic_window, "icir_window": icir_window}
