"""从 K 线构建 Brinson 所需：组合权重（多因子信号）、等权基准、资产前向收益矩阵"""
from __future__ import annotations

import numpy as np
import pandas as pd  # pyright: ignore[reportMissingImports]

from services.strategy_engine.backtest import composite_score_series
from services.strategy_engine.factor_evaluation import evaluate_factors_ic
from services.strategy_engine.factors import (
    add_factor_columns,
    candles_to_df,
    resolve_active_factor_cols,
)
from services.strategy_engine.weights import icir_weights


def build_brinson_panel_from_candles(
    symbols: list[str],
    candles_by_symbol: dict[str, list],
    active_factors: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame] | None:
    """
    返回 (weights_portfolio, weights_benchmark, asset_returns)，index 为 0..L-1，columns 为标的。
    组合权重：每期在参与回测的标的间，按多因子信号（>滚动分位）归一化；全 0 时等权。
    基准：每期等权 1/N。
    收益：下一根 K 线收益率（与策略引擎回测一致）。
    """
    sig_list: list[np.ndarray] = []
    ret_list: list[np.ndarray] = []
    ok_cols: list[str] = []

    for sym in symbols:
        su = (sym or "").strip().upper()
        cand = candles_by_symbol.get(su) or candles_by_symbol.get(sym) or []
        df0 = candles_to_df(cand)
        if df0.empty or len(df0) < 80:
            continue
        df, factor_cols = add_factor_columns(df0)
        if not factor_cols:
            continue
        use_cols = resolve_active_factor_cols(factor_cols, active_factors)
        ev = evaluate_factors_ic(df, use_cols)
        ic_map = ev.get("factors") or {}
        wfac = icir_weights(ic_map)
        if not wfac:
            wfac = {c: 1.0 / len(use_cols) for c in use_cols}
        score = composite_score_series(df, use_cols, wfac)
        q = score.rolling(80, min_periods=40).quantile(0.55)
        signal = (score > q).astype(float)
        next_ret = df["close"].astype(float).pct_change().shift(-1)
        sub_sig = signal.iloc[:-1]
        sub_ret = next_ret.iloc[:-1]
        mask = sub_sig.notna() & sub_ret.notna()
        sig_v = sub_sig[mask].values.astype(float)
        ret_v = sub_ret[mask].values.astype(float)
        if len(sig_v) < 20:
            continue
        sig_list.append(sig_v)
        ret_list.append(ret_v)
        ok_cols.append(su)

    if len(ok_cols) < 2:
        return None

    L = min(len(a) for a in sig_list)
    n = len(ok_cols)
    sig_mat = np.zeros((L, n))
    ret_mat = np.zeros((L, n))
    for j, su in enumerate(ok_cols):
        sig_mat[:, j] = sig_list[j][-L:]
        ret_mat[:, j] = ret_list[j][-L:]

    idx = pd.RangeIndex(stop=L)
    w_p = pd.DataFrame(index=idx, columns=ok_cols, dtype=float)
    for t in range(L):
        row = sig_mat[t] + 1e-15
        s = row.sum()
        if s < 1e-12:
            w_p.iloc[t] = 1.0 / n
        else:
            w_p.iloc[t] = row / s

    w_b = pd.DataFrame(1.0 / n, index=idx, columns=ok_cols, dtype=float)
    r_df = pd.DataFrame(ret_mat, index=idx, columns=ok_cols, dtype=float)
    return w_p, w_b, r_df
