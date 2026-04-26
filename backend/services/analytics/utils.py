"""DataFrame 对齐工具"""
from __future__ import annotations

import pandas as pd


def align_three(
    weights_portfolio: pd.DataFrame,
    weights_benchmark: pd.DataFrame,
    asset_returns: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    idx = weights_portfolio.index.intersection(weights_benchmark.index).intersection(
        asset_returns.index
    )
    cols = weights_portfolio.columns.intersection(weights_benchmark.columns).intersection(
        asset_returns.columns
    )
    if len(idx) == 0 or len(cols) == 0:
        return (
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
        )
    return (
        weights_portfolio.loc[idx, cols].astype(float).fillna(0.0),
        weights_benchmark.loc[idx, cols].astype(float).fillna(0.0),
        asset_returns.loc[idx, cols].astype(float),
    )
