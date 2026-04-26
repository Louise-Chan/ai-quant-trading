"""组合可视化回测与三模型评分报告（本地 PC 可跑；可选 Brinson + 正式风险模型）"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import numpy as np  # pyright: ignore[reportMissingImports]

from services.analytics.brinson import brinson_fachler, brinson_result_to_json
from services.analytics.config import BENCHMARK_DESCRIPTION, default_sector_map
from services.analytics.panel import build_brinson_panel_from_candles
from services.analytics.risk_model import formal_risk_analysis, risk_result_to_json

_BARS_PER_YEAR = {
    "1m": 252 * 24 * 60,
    "15m": 252 * 24 * 4,
    "1h": 252 * 24,
    "4h": 252 * 6,
    "1d": 252,
}


def _downsample_np(arr: np.ndarray, max_points: int = 500) -> list[dict]:
    n = len(arr)
    if n <= max_points:
        return [{"i": int(i), "v": round(float(arr[i]), 6)} for i in range(n)]
    step = max(1, n // max_points)
    out = [{"i": int(i), "v": round(float(arr[i]), 6)} for i in range(0, n, step)]
    if out[-1]["i"] != n - 1:
        out.append({"i": n - 1, "v": round(float(arr[-1]), 6)})
    return out


def run_portfolio_visual_backtest(
    symbols: list[str],
    candles_by_symbol: dict[str, list],
    interval: str = "1h",
    active_factors: list[str] | None = None,
    dynamic_factor_expressions: dict[str, str] | None = None,
    max_opens_per_day: int | None = None,
    avg_daily_mode: str = "trading",
) -> dict:
    from services.strategy_engine.backtest import run_simple_backtest
    from services.strategy_engine.factor_evaluation import evaluate_factors_ic
    from services.strategy_engine.factors import (
        add_factor_columns,
        candles_to_df,
        default_factor_ids,
        resolve_active_factor_cols,
    )
    from services.strategy_engine.weights import icir_weights
    from services.strategy_engine.dynamic_factors_executor import compute_dynamic_factor_series

    bars_py = float(_BARS_PER_YEAR.get(interval, 252 * 24))
    per_symbol: list[dict] = []
    pnl_arrays: list[np.ndarray] = []
    bench_arrays: list[np.ndarray] = []
    ok_syms: list[str] = []
    factor_icir_accum: dict[str, list[float]] = {}
    factor_weight_accum: dict[str, list[float]] = {}
    factor_ic_mean_accum: dict[str, list[float]] = {}

    for sym in symbols:
        sym_u = (sym or "").strip().upper()
        cand = candles_by_symbol.get(sym_u) or candles_by_symbol.get(sym) or []
        df0 = candles_to_df(cand)
        if df0.empty or len(df0) < 80:
            per_symbol.append({"symbol": sym_u, "ok": False, "reason": "K 线不足"})
            continue
        df, factor_cols = add_factor_columns(df0)
        if not factor_cols:
            per_symbol.append({"symbol": sym_u, "ok": False, "reason": "因子计算失败"})
            continue

        # 动态因子：根据 active_factors 与表达式映射，按需计算出 df[dyn_xxx]
        dyn_map = dynamic_factor_expressions or {}
        if dyn_map:
            needed_dyn_cols: list[str] = []
            if active_factors:
                needed_dyn_cols = [x for x in active_factors if x in dyn_map]
            else:
                needed_dyn_cols = list(dyn_map.keys())
            needed_dyn_cols = [str(x) for x in needed_dyn_cols if str(x).strip()]
            for dyn_col in needed_dyn_cols:
                if dyn_col in df.columns:
                    continue
                df[dyn_col] = compute_dynamic_factor_series(df, dyn_map[dyn_col])
            factor_cols = list(factor_cols) + needed_dyn_cols

        use_cols = resolve_active_factor_cols(factor_cols, active_factors)
        ev = evaluate_factors_ic(df, use_cols)
        ic_map = ev.get("factors") or {}
        w = icir_weights(ic_map)
        if not w:
            w = {c: round(1.0 / len(use_cols), 4) for c in use_cols}
        bt = run_simple_backtest(
            df,
            use_cols,
            w,
            bars_per_year=bars_py,
            max_opens_per_day=max_opens_per_day,
            avg_daily_mode=avg_daily_mode,
            include_per_bar=True,
            include_trade_events=True,
        )
        if not bt.get("ok"):
            per_symbol.append(
                {"symbol": sym_u, "ok": False, "reason": bt.get("reason", "回测失败")}
            )
            continue
        pnl = np.array(bt["per_bar_pnl"], dtype=float)
        bench = np.array(bt["per_bar_bench"], dtype=float)
        pnl_arrays.append(pnl)
        bench_arrays.append(bench)
        ok_syms.append(sym_u)
        series_range: dict[str, int] | None = None
        if not df0.empty and "time" in df0.columns:
            try:
                t0 = float(df0.iloc[0]["time"])
                t1 = float(df0.iloc[-1]["time"])
                if t0 > 10_000_000_000:
                    t0 /= 1000.0
                if t1 > 10_000_000_000:
                    t1 /= 1000.0
                a, b = int(t0), int(t1)
                if a > b:
                    a, b = b, a
                series_range = {"from_ts": a, "to_ts": b, "bars": int(len(df0))}
            except (TypeError, ValueError):
                series_range = None
        tev = bt.get("trade_events") if isinstance(bt.get("trade_events"), list) else []
        ps_row: dict[str, Any] = {
            "symbol": sym_u,
            "ok": True,
            "total_return": bt.get("total_return"),
            "benchmark_total_return": bt.get("benchmark_total_return"),
            "alpha_vs_buyhold": bt.get("alpha_vs_buyhold"),
            "sharpe_approx": bt.get("sharpe_approx"),
            "max_drawdown": bt.get("max_drawdown"),
            "win_rate": bt.get("win_rate"),
            "open_count": int(bt.get("open_count") or 0),
            "avg_daily_open_count": float(bt.get("avg_daily_open_count") or 0.0),
            "avg_daily_open_count_trading": float(bt.get("avg_daily_open_count_trading") or 0.0),
            "avg_daily_open_count_natural": float(bt.get("avg_daily_open_count_natural") or 0.0),
            "trade_events": tev,
            "series_range": series_range,
        }
        if bt.get("trade_events_truncated"):
            ps_row["trade_events_truncated"] = True
        per_symbol.append(ps_row)
        for c, icd in ic_map.items():
            icir = float(icd.get("icir") or 0)
            icm = float(icd.get("ic_mean_recent") or 0)
            if not math.isfinite(icir):
                icir = 0.0
            if not math.isfinite(icm):
                icm = 0.0
            factor_icir_accum.setdefault(c, []).append(icir)
            factor_ic_mean_accum.setdefault(c, []).append(icm)
            factor_weight_accum.setdefault(c, []).append(float(w.get(c, 0)))

    portfolio_block: dict[str, Any] = {
        "ok": False,
        "reason": "无足够标的完成组合回测",
    }
    insignificant_symbols: list[dict] = []
    factor_impact: list[dict] = []

    if len(pnl_arrays) >= 1:
        L = min(len(p) for p in pnl_arrays)
        stack = np.vstack([p[-L:] for p in pnl_arrays])
        bench_stack = np.vstack([b[-L:] for b in bench_arrays])
        port_pnl = np.mean(stack, axis=0)
        port_bench = np.mean(bench_stack, axis=0)
        port_eq = np.cumprod(1.0 + port_pnl)
        bench_eq = np.cumprod(1.0 + port_bench)
        vol = float(np.std(port_pnl)) or 1e-12
        sharpe_p = float(np.sqrt(bars_py) * float(np.mean(port_pnl)) / vol)
        total_p = float(port_eq[-1] - 1.0)
        bench_p = float(bench_eq[-1] - 1.0)
        alpha_p = float(total_p - bench_p)
        peak = np.maximum.accumulate(port_eq)
        max_dd_p = float(np.min(port_eq / np.maximum(peak, 1e-12) - 1.0))
        oc_list = [int(x.get("open_count") or 0) for x in per_symbol if x.get("ok") and x.get("symbol")]
        oc_sum = int(sum(oc_list)) if oc_list else 0
        oc_mean = float(np.mean(oc_list)) if oc_list else 0.0
        od_list = [float(x.get("avg_daily_open_count") or 0.0) for x in per_symbol if x.get("ok") and x.get("symbol")]
        od_mean = float(np.mean(od_list)) if od_list else 0.0
        od_t_list = [float(x.get("avg_daily_open_count_trading") or 0.0) for x in per_symbol if x.get("ok") and x.get("symbol")]
        od_n_list = [float(x.get("avg_daily_open_count_natural") or 0.0) for x in per_symbol if x.get("ok") and x.get("symbol")]
        od_t_mean = float(np.mean(od_t_list)) if od_t_list else 0.0
        od_n_mean = float(np.mean(od_n_list)) if od_n_list else 0.0
        dm = "natural" if str(avg_daily_mode or "").strip().lower() == "natural" else "trading"
        portfolio_block = {
            "ok": True,
            "symbols_in_portfolio": ok_syms,
            "bars": L,
            "total_return": round(total_p, 4),
            "benchmark_total_return": round(bench_p, 4),
            "alpha_vs_buyhold": round(alpha_p, 4),
            "sharpe_approx": round(sharpe_p, 4),
            "max_drawdown": round(max_dd_p, 4),
            "open_count_total": oc_sum,
            "open_count_mean": round(oc_mean, 1),
            "avg_daily_open_count": round(od_mean, 4),
            "avg_daily_open_count_trading": round(od_t_mean, 4),
            "avg_daily_open_count_natural": round(od_n_mean, 4),
            "avg_daily_mode": dm,
            "max_opens_per_day": int(max_opens_per_day) if max_opens_per_day else 0,
            "equity_curve": _downsample_np(port_eq),
            "benchmark_curve": _downsample_np(bench_eq),
        }

        sum_abs_port = float(np.sum(np.abs(port_pnl))) + 1e-15
        open_count_by_sym = {
            str(x.get("symbol") or "").strip().upper(): int(x.get("open_count") or 0)
            for x in per_symbol
            if x.get("ok") and x.get("symbol")
        }
        for i, sym in enumerate(ok_syms):
            s = stack[i]
            n = len(s)
            mu = float(np.mean(s))
            sd = float(np.std(s, ddof=1)) if n > 1 else 0.0
            t_stat = mu / (sd / math.sqrt(n) + 1e-15) if sd > 1e-15 else 0.0
            cum_r = float(np.prod(1.0 + s) - 1.0)
            if n > 2 and sd > 1e-15:
                corr = float(np.corrcoef(s, port_pnl)[0, 1])
                if not math.isfinite(corr):
                    corr = 0.0
            else:
                corr = 0.0
            contrib_share = float(np.sum(s) / sum_abs_port)
            # 统计不显著：t 偏小且收益贡献占比低 → 更像噪音/运气
            low_edge = abs(t_stat) < 2.0
            low_contrib = abs(contrib_share) < 0.12 and abs(cum_r) < 0.04
            luck_like = low_edge and (abs(corr) < 0.18 or low_contrib)
            verdict = (
                "对组合净值增长统计不显著，收益更可能来自随机波动"
                if luck_like
                else "对组合有一定边际贡献（仍不代表未来收益）"
            )
            insignificant_symbols.append(
                {
                    "symbol": sym,
                    "t_statistic": round(t_stat, 3),
                    "cumulative_return": round(cum_r, 4),
                    "correlation_with_portfolio": round(corr, 4),
                    "pnl_share_vs_portfolio_abs": round(contrib_share, 4),
                    "open_count": int(open_count_by_sym.get(sym, 0)),
                    "luck_risk": "高" if luck_like else "中" if low_edge else "低",
                    "verdict": verdict,
                    "suggest_remove_from_portfolio": bool(luck_like),
                }
            )

    for fname in sorted(factor_icir_accum.keys()):
        icirs = factor_icir_accum[fname]
        icms = factor_ic_mean_accum.get(fname, [0.0])
        wts = factor_weight_accum.get(fname, [0.0])
        avg_icir = float(np.mean(icirs))
        avg_icm = float(np.mean(icms))
        avg_w = float(np.mean(wts))
        # 0–100 作用评分：ICIR 为主，权重为辅
        raw = 50.0 + 18.0 * math.atan(avg_icir) + 15.0 * min(1.0, avg_w * 8)
        impact_score = int(round(min(100, max(0, raw))))
        weak = avg_icir < 0.25 and abs(avg_icm) < 0.02
        factor_impact.append(
            {
                "factor": fname,
                "avg_icir": round(avg_icir, 4),
                "avg_ic_mean": round(avg_icm, 4),
                "avg_weight": round(avg_w, 4),
                "impact_score": impact_score,
                "suggest_remove_factor": bool(weak and avg_w < 0.08),
                "note": "ICIR 低且权重分散时，该因子在本组合中边际作用有限",
            }
        )

    impact_by_name = {row["factor"]: row for row in factor_impact}
    # 保持前端选中的因子顺序展示；未选的按 impact_score 从高到低追加
    if active_factors:
        selected_order = [str(x).strip() for x in active_factors if str(x).strip()]
    else:
        selected_order = []
    selected_set = set(selected_order)
    factor_sorted_by_score = sorted(factor_impact, key=lambda r: -float(r.get("impact_score") or 0.0))
    factor_impact_ordered: list[dict] = []
    for fid in selected_order:
        row = impact_by_name.get(fid)
        if row:
            factor_impact_ordered.append(row)
    for row in factor_sorted_by_score:
        if str(row.get("factor")) not in selected_set and row.get("factor") in impact_by_name:
            factor_impact_ordered.append(row)

    brinson_json: dict[str, Any] | None = None
    formal_risk_json: dict[str, Any] | None = None
    if len(ok_syms) >= 2:
        panel = build_brinson_panel_from_candles(ok_syms, candles_by_symbol, active_factors=active_factors)
        if panel is not None:
            wp, wb, rd = panel
            br = brinson_fachler(wp, wb, rd, sector_map=default_sector_map())
            brinson_json = brinson_result_to_json(br)
            brinson_json["benchmark_description"] = BENCHMARK_DESCRIPTION
            rk = formal_risk_analysis(rd, wp, wb)
            formal_risk_json = risk_result_to_json(rk)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "interval": interval,
        "active_factors_used": sorted(factor_icir_accum.keys()) if ok_syms else [],
        "per_symbol": per_symbol,
        "portfolio": portfolio_block,
        "insignificant_symbols_analysis": insignificant_symbols,
        "factor_impact_scores": factor_impact_ordered,
        "brinson_attribution": brinson_json,
        "formal_risk_model": formal_risk_json,
        "disclaimer": "本地回测：不含手续费/滑点；Brinson 与风险模型基于对齐面板估计，非投资建议。",
    }


def build_analytics_report(
    packages: list[tuple[str, dict]],
    interval: str,
    candles_by_symbol: dict[str, list] | None = None,
) -> dict:
    """
    packages: [(symbol, analyze_symbol 返回的 dict), ...]
    若传入 candles_by_symbol 且标的数≥2，额外计算 Brinson 与 Σ=BFB'+D 风险指标。
    """
    if not packages:
        return {"ok": False, "error": "无分析数据"}

    pred_rows = []
    risk_rows = []
    attrib_rows = []
    pred_scores: list[float] = []
    risk_scores: list[float] = []
    attrib_scores: list[float] = []

    for sym, pkg in packages:
        if not pkg.get("ok"):
            continue
        ml = pkg.get("machine_learning") or {}
        bt = pkg.get("backtest") or {}
        rm = pkg.get("risk_metrics") or {}
        fe = pkg.get("factor_evaluation") or {}
        weights = pkg.get("dynamic_weights") or {}

        # —— 预测模型（ML）——
        p_up = ml.get("p_up")
        acc = ml.get("holdout_accuracy")
        if ml.get("available"):
            if acc is not None:
                ps = min(100, max(0, 50 + 45 * (float(acc) - 0.5)))
            elif p_up is not None:
                ps = min(100, max(0, 50 + 40 * abs(float(p_up) - 0.5)))
            else:
                ps = 50.0
            pred_scores.append(ps)
            pred_rows.append(
                {
                    "symbol": sym,
                    "model": ml.get("model", "—"),
                    "p_up": p_up,
                    "holdout_accuracy": acc,
                    "train_rows": ml.get("train_rows"),
                    "score": int(round(ps)),
                    "comment": "准确率在 0.5 附近则预测力有限",
                }
            )
        else:
            pred_rows.append(
                {
                    "symbol": sym,
                    "model": "—",
                    "p_up": None,
                    "holdout_accuracy": None,
                    "train_rows": None,
                    "score": None,
                    "comment": ml.get("reason", "模型不可用"),
                }
            )

        # —— 风险模型 ——
        if bt.get("ok"):
            sharpe = float(bt.get("sharpe_approx") or 0)
            mdd = abs(float(bt.get("max_drawdown") or 0))
            vol = float(rm.get("realized_vol_20") or 0)
            rs = min(
                100,
                max(
                    0,
                    35
                    + min(30, sharpe * 8)
                    + max(0, 25 - mdd * 80)
                    + max(0, 10 - vol * 200),
                ),
            )
            risk_scores.append(rs)
            risk_rows.append(
                {
                    "symbol": sym,
                    "sharpe_approx": bt.get("sharpe_approx"),
                    "max_drawdown": bt.get("max_drawdown"),
                    "realized_vol_20": round(vol, 6),
                    "kelly_suggested": rm.get("kelly_suggested"),
                    "score": int(round(rs)),
                    "comment": "回撤深、波动高则风险分偏低",
                }
            )
        else:
            risk_rows.append(
                {
                    "symbol": sym,
                    "score": None,
                    "comment": bt.get("reason", "无回测"),
                }
            )

        # —— 归因（因子层，简化）——
        facs = fe.get("factors") or {}
        if facs and weights:
            icir_w = sum(
                float((facs.get(c) or {}).get("icir") or 0) * float(weights.get(c, 0))
                for c in weights
            )
            ascore = min(100, max(0, 50 + 35 * math.atan(icir_w * 3)))
            attrib_scores.append(ascore)
            top3 = sorted(
                weights.items(), key=lambda x: -x[1]
            )[:3]
            attrib_rows.append(
                {
                    "symbol": sym,
                    "top_factors_by_weight": [f"{k} ({round(v, 3)})" for k, v in top3],
                    "weighted_icir_proxy": round(icir_w, 4),
                    "score": int(round(ascore)),
                    "comment": "权重×ICIR 代理归因强度（非 Brinson 全量分解）",
                }
            )
        else:
            attrib_rows.append(
                {
                    "symbol": sym,
                    "top_factors_by_weight": [],
                    "weighted_icir_proxy": None,
                    "score": None,
                    "comment": "因子评估数据不足",
                }
            )

    def _avg(xs: list[float]) -> int | None:
        return int(round(sum(xs) / len(xs))) if xs else None

    sym_used = [p[0] for p in packages]
    brinson_json: dict[str, Any] | None = None
    formal_risk_json: dict[str, Any] | None = None
    attrib_title = "归因模型（多因子权重 × ICIR 参考）"
    risk_title = "风险模型（单标的回测夏普、回撤、实现波动）"
    note = (
        "运行于本地 PC；单标的行为「启发式」评分。"
        "若返回 brinson_attribution / formal_risk_model，则为组合面板上的 Brinson 与正式风险分解。"
    )

    if candles_by_symbol and len(sym_used) >= 2:
        panel = build_brinson_panel_from_candles(sym_used, candles_by_symbol)
        if panel is not None:
            wp, wb, rd = panel
            br = brinson_fachler(wp, wb, rd, sector_map=default_sector_map())
            brinson_json = brinson_result_to_json(br)
            brinson_json["benchmark_description"] = BENCHMARK_DESCRIPTION
            rk = formal_risk_analysis(rd, wp, wb)
            formal_risk_json = risk_result_to_json(rk)
            attrib_title = "归因模型（Brinson-Fachler 组合层 + 单标的 ICIR 参考）"
            risk_title = "风险模型（单标的表 + 组合 Σ 风险摘要见 formal_risk_model）"
            note = (
                "Brinson 使用行业映射聚合（未覆盖标的归入「其他」）；"
                "风险模型为简化 BFB'+D，单期波动与 VaR 为同一 K 线频率下的近似。"
            )

    return {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "interval": interval,
        "prediction_model": {
            "title": "预测模型（逻辑回归 / 上涨概率）",
            "aggregate_score": _avg(pred_scores),
            "rows": pred_rows,
        },
        "risk_model": {
            "title": risk_title,
            "aggregate_score": _avg(risk_scores),
            "rows": risk_rows,
        },
        "attribution_model": {
            "title": attrib_title,
            "aggregate_score": _avg(attrib_scores),
            "rows": attrib_rows,
        },
        "brinson_attribution": brinson_json,
        "formal_risk_model": formal_risk_json,
        "note": note,
    }
