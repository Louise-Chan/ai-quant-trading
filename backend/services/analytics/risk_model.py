"""
简化多因子风险模型：Σ = B F B' + D
因子：截面市场收益、截面波动、滞后市场收益（动量代理）。
对每个资产做时序 OLS 得暴露 B_i；F 为因子样本协方差；D 为特异方差对角。
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd  # pyright: ignore[reportMissingImports]

from services.analytics.utils import align_three


def build_factor_returns(returns_df: pd.DataFrame) -> pd.DataFrame:
    """每期截面因子（与资产收益对齐的 index）"""
    mkt = returns_df.mean(axis=1)
    vol_cs = returns_df.std(axis=1, ddof=1).replace(0, np.nan).fillna(0.0)
    mom_lag = mkt.shift(1)
    fac = pd.DataFrame(
        {
            "f_mkt": mkt,
            "f_vol_cs": vol_cs,
            "f_mom_lag": mom_lag,
        },
        index=returns_df.index,
    )
    return fac.dropna()


def formal_risk_analysis(
    asset_returns: pd.DataFrame,
    weights_portfolio: pd.DataFrame,
    weights_benchmark: pd.DataFrame,
    ridge: float = 1e-6,
) -> dict[str, Any]:
    w_p, w_b, r = align_three(weights_portfolio, weights_benchmark, asset_returns)
    if w_p.empty or r.empty:
        return {"ok": False, "reason": "收益或权重矩阵为空"}

    r = r.fillna(0.0)
    fac = build_factor_returns(r)
    idx = r.index.intersection(fac.index)
    if len(idx) < 20:
        return {"ok": False, "reason": "因子/收益对齐后样本过短"}
    R = r.loc[idx]
    Fdf = fac.loc[idx]
    T, n_assets = R.shape
    K = Fdf.shape[1]
    X = Fdf.values.astype(float)
    F_cov = np.cov(X, rowvar=False) + np.eye(K) * ridge

    B_rows: list[np.ndarray] = []
    resid_vars: list[float] = []
    cols = list(R.columns)

    for j, col in enumerate(cols):
        y = R[col].values.astype(float)
        mask = np.isfinite(y) & np.all(np.isfinite(X), axis=1)
        n_ok = int(mask.sum())
        if n_ok < max(K + 3, 20):
            B_rows.append(np.zeros(K))
            resid_vars.append(max(float(np.var(y[mask])) if n_ok > 1 else 1e-6, 1e-10))
            continue
        X_ = X[mask]
        y_ = y[mask]
        try:
            XtX = X_.T @ X_ + np.eye(K) * ridge
            Xty = X_.T @ y_
            beta = np.linalg.solve(XtX, Xty)
            pred = X_ @ beta
            e = y_ - pred
            rv = float(np.var(e, ddof=1)) if len(e) > 2 else float(np.var(e))
            B_rows.append(beta)
            resid_vars.append(max(rv, 1e-10))
        except Exception:
            B_rows.append(np.zeros(K))
            resid_vars.append(1e-6)

    B = np.vstack(B_rows)
    D = np.diag(resid_vars)
    Sigma = B @ F_cov @ B.T + D
    Sigma = (Sigma + Sigma.T) / 2

    w_last = w_p.iloc[-1].reindex(cols).fillna(0.0).values.astype(float)
    wb_last = w_b.iloc[-1].reindex(cols).fillna(0.0).values.astype(float)
    s = w_last.sum()
    if s > 1e-12:
        w_last = w_last / s
    sb = wb_last.sum()
    if sb > 1e-12:
        wb_last = wb_last / sb

    port_var = float(w_last @ Sigma @ w_last)
    port_vol = float(np.sqrt(max(port_var, 0.0)))
    active = w_last - wb_last
    te_var = float(active @ Sigma @ active)
    tracking_error = float(np.sqrt(max(te_var, 0.0)))

    sigw = Sigma @ w_last
    denom = float(w_last @ sigw)
    if abs(denom) < 1e-18:
        mrc_pct = {c: 0.0 for c in cols}
    else:
        mrc_pct = {cols[i]: float(sigw[i] * w_last[i]) / denom for i in range(len(cols))}

    var_95 = float(1.645 * port_vol)
    top_mrc = sorted(mrc_pct.items(), key=lambda x: -abs(x[1]))[:8]

    return {
        "ok": True,
        "portfolio_vol_1bar": round(port_vol, 8),
        "tracking_error_1bar": round(tracking_error, 8),
        "var_95_normal_1bar": round(var_95, 8),
        "factor_names": list(Fdf.columns),
        "factor_cov_summary": {
            "f_mkt_var": round(float(F_cov[0, 0]), 10) if K > 0 else None,
        },
        "marginal_risk_contrib_pct": {k: round(v, 4) for k, v in mrc_pct.items()},
        "top_risk_contributors": [{"asset": a, "contrib_pct": round(p, 4)} for a, p in top_mrc],
        "n_obs": int(T),
        "n_assets": int(n_assets),
    }


def risk_result_to_json(res: dict[str, Any]) -> dict[str, Any]:
    if not res.get("ok"):
        return {"ok": False, "reason": res.get("reason", "")}
    out = {k: v for k, v in res.items() if k != "marginal_risk_contrib_pct"}
    # 完整 MRC 可能较长，保留 top 已在 top_risk_contributors
    return out
