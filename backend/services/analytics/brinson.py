"""
Brinson-Fachler 多期归因（按行业聚合时含配置/选股/交互；单层按币种时选股+交互为 0）。
公式（每期、每个板块 s）：
  R_b = Σ_i w_b_i r_i ，R_p = Σ_i w_p_i r_i
  allocation_s = (W_p_s - W_b_s) * (r_b_s - R_b)
  selection_s = W_b_s * (r_p_s - r_b_s)
  interaction_s = (W_p_s - W_b_s) * (r_p_s - r_b_s)
其中 W 为板块内权重之和，r_b_s、r_p_s 为板块内按对应权重加权的收益。
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd  # pyright: ignore[reportMissingImports]

from services.analytics.utils import align_three


def _aggregate_to_sectors(
    w_p: pd.DataFrame,
    w_b: pd.DataFrame,
    r: pd.DataFrame,
    sector_map: dict[str, str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    cols = list(w_p.columns)
    sector_to_assets: dict[str, list[str]] = {}
    for c in cols:
        sec = sector_map.get(str(c).upper(), sector_map.get(str(c), "其他"))
        sector_to_assets.setdefault(sec, []).append(c)
    sectors = sorted(sector_to_assets.keys())
    idx = w_p.index
    w_p_s = pd.DataFrame(0.0, index=idx, columns=sectors)
    w_b_s = pd.DataFrame(0.0, index=idx, columns=sectors)
    r_b_s = pd.DataFrame(np.nan, index=idx, columns=sectors)
    r_p_s = pd.DataFrame(np.nan, index=idx, columns=sectors)

    for sec in sectors:
        assets = sector_to_assets[sec]
        w_p_s[sec] = w_p[assets].sum(axis=1)
        w_b_s[sec] = w_b[assets].sum(axis=1)
        # 板块基准收益：按基准权重加权
        num_b = (w_b[assets] * r[assets]).sum(axis=1)
        den_b = w_b[assets].sum(axis=1).replace(0, np.nan)
        r_b_s[sec] = num_b / den_b
        num_p = (w_p[assets] * r[assets]).sum(axis=1)
        den_p = w_p[assets].sum(axis=1).replace(0, np.nan)
        r_p_s[sec] = num_p / den_p
        # 若组合或基准在板块无仓位，用简单平均收益填充以避免 NaN 破坏求和
        m = r_b_s[sec].isna()
        if m.any():
            r_b_s.loc[m, sec] = r[assets].loc[m].mean(axis=1)
        m2 = r_p_s[sec].isna()
        if m2.any():
            r_p_s.loc[m2, sec] = r[assets].loc[m2].mean(axis=1)
        r_b_s[sec] = r_b_s[sec].fillna(0.0)
        r_p_s[sec] = r_p_s[sec].fillna(0.0)

    return w_p_s, w_b_s, r_b_s, r_p_s  # type: ignore[return-value]


def brinson_fachler(
    weights_portfolio: pd.DataFrame,
    weights_benchmark: pd.DataFrame,
    asset_returns: pd.DataFrame,
    sector_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    w_p, w_b, r = align_three(weights_portfolio, weights_benchmark, asset_returns)
    if w_p.empty:
        return {
            "allocation_effect": pd.Series(dtype=float),
            "selection_effect": pd.Series(dtype=float),
            "interaction_effect": pd.Series(dtype=float),
            "total_active_return": pd.Series(dtype=float),
            "portfolio_return": pd.Series(dtype=float),
            "benchmark_return": pd.Series(dtype=float),
            "by_segment_cumulative": {},
            "ok": False,
            "reason": "输入矩阵对齐后为空",
        }

    use_sectors = bool(sector_map) and len(w_p.columns) > 1
    if use_sectors:
        w_p_s, w_b_s, r_b_sec, r_p_sec = _aggregate_to_sectors(w_p, w_b, r, sector_map)  # type: ignore[misc]
        segments = list(w_p_s.columns)
        R_b = (w_b * r).sum(axis=1)
        R_p = (w_p * r).sum(axis=1)
        alloc = pd.Series(0.0, index=w_p.index)
        sel = pd.Series(0.0, index=w_p.index)
        inter = pd.Series(0.0, index=w_p.index)
        by_seg_alloc: dict[str, pd.Series] = {}
        by_seg_sel: dict[str, pd.Series] = {}
        by_seg_inter: dict[str, pd.Series] = {}
        for s in segments:
            Wp = w_p_s[s]
            Wb = w_b_s[s]
            rbs = r_b_sec[s]
            rps = r_p_sec[s]
            a = (Wp - Wb) * (rbs - R_b)
            se = Wb * (rps - rbs)
            it = (Wp - Wb) * (rps - rbs)
            alloc = alloc + a
            sel = sel + se
            inter = inter + it
            by_seg_alloc[s] = a
            by_seg_sel[s] = se
            by_seg_inter[s] = it
    else:
        # 单层：每列即一个 segment，r_p = r_b = r
        segments = list(w_p.columns)
        R_b = (w_b * r).sum(axis=1)
        R_p = (w_p * r).sum(axis=1)
        alloc = pd.Series(0.0, index=w_p.index)
        sel = pd.Series(0.0, index=w_p.index)
        inter = pd.Series(0.0, index=w_p.index)
        by_seg_alloc = {}
        by_seg_sel = {}
        by_seg_inter = {}
        for col in segments:
            wi_p = w_p[col]
            wi_b = w_b[col]
            ri = r[col]
            a = (wi_p - wi_b) * (ri - R_b)
            se = wi_b * (ri - ri)
            it = (wi_p - wi_b) * (ri - ri)
            alloc = alloc + a
            sel = sel + se
            inter = inter + it
            by_seg_alloc[str(col)] = a
            by_seg_sel[str(col)] = se
            by_seg_inter[str(col)] = it

    total_active = R_p - R_b
    return {
        "allocation_effect": alloc,
        "selection_effect": sel,
        "interaction_effect": inter,
        "total_active_return": total_active,
        "portfolio_return": R_p,
        "benchmark_return": R_b,
        "by_segment_allocation": by_seg_alloc,
        "by_segment_selection": by_seg_sel,
        "by_segment_interaction": by_seg_inter,
        "segments": segments,
        "ok": True,
    }


def brinson_result_to_json(res: dict[str, Any], max_series_points: int = 200) -> dict[str, Any]:
    if not res.get("ok"):
        return {"ok": False, "reason": res.get("reason", "未知错误")}

    def _sum_series(s: pd.Series) -> float:
        return float(s.sum()) if isinstance(s, pd.Series) and len(s) else 0.0

    def _downsample(s: pd.Series) -> list[dict]:
        if not isinstance(s, pd.Series) or s.empty:
            return []
        v = s.astype(float).fillna(0.0).values
        n = len(v)
        if n <= max_series_points:
            return [{"i": i, "v": round(float(v[i]), 8)} for i in range(n)]
        step = max(1, n // max_series_points)
        out = [{"i": i, "v": round(float(v[i]), 8)} for i in range(0, n, step)]
        if out[-1]["i"] != n - 1:
            out.append({"i": n - 1, "v": round(float(v[-1]), 8)})
        return out

    cum_alloc = _sum_series(res["allocation_effect"])
    cum_sel = _sum_series(res["selection_effect"])
    cum_inter = _sum_series(res["interaction_effect"])
    cum_active = _sum_series(res["total_active_return"])

    by_seg = {}
    for name, sdict in [
        ("allocation", res.get("by_segment_allocation") or {}),
        ("selection", res.get("by_segment_selection") or {}),
        ("interaction", res.get("by_segment_interaction") or {}),
    ]:
        by_seg[name] = {k: round(float(v.sum()), 6) for k, v in sdict.items() if isinstance(v, pd.Series)}

    return {
        "ok": True,
        "cumulative": {
            "allocation_effect": round(cum_alloc, 6),
            "selection_effect": round(cum_sel, 6),
            "interaction_effect": round(cum_inter, 6),
            "active_return": round(cum_active, 6),
            "check_sum": round(cum_alloc + cum_sel + cum_inter, 6),
        },
        "by_segment_cumulative": by_seg,
        "series": {
            "allocation": _downsample(res["allocation_effect"]),
            "selection": _downsample(res["selection_effect"]),
            "interaction": _downsample(res["interaction_effect"]),
            "active": _downsample(res["total_active_return"]),
            "portfolio_return": _downsample(res["portfolio_return"]),
            "benchmark_return": _downsample(res["benchmark_return"]),
        },
    }
