"""串联因子 → 评估 → 权重 → ML → 回测 → 风险与建议订单字段

生产接入（勿依赖本文件「直接运行」）：
- ``api/order_audit.py``：``use_strategy_engine=True`` 时用 ``list_candlesticks`` 拉 Gate K 线，再 ``analyze_symbol``，结果写入审核上下文。
- ``api/strategy_engine_api.py``：``GET /strategy-engine/analyze`` 同上，供调试/前端展示。

``candles`` 须为 Gate 风格 ``list[dict]``，键含 ``open/high/low/close/volume``，可选 ``time``（见 ``factors.candles_to_df``）。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 直接 `python runner.py` 时包根不在 sys.path；从 backend 以 `python -m services.strategy_engine.runner` 运行则不需要
if __name__ == "__main__" and not __package__:
    _backend_root = Path(__file__).resolve().parents[2]
    _p = str(_backend_root)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from services.strategy_engine._numeric import finite_float, optional_positive_float, safe_quantile
from services.strategy_engine.backtest import composite_score_series, run_simple_backtest
from services.strategy_engine.factor_evaluation import evaluate_factors_ic
from services.strategy_engine.factors import add_factor_columns, candles_to_df, latest_factor_snapshot, resolve_active_factor_cols
from services.strategy_engine.ml_model import train_predict_ml
from services.strategy_engine.position_risk import atr_stops, kelly_fraction, realized_vol, suggest_position_usdt
from services.strategy_engine.weights import icir_weights
from services.strategy_engine.dynamic_factors_executor import compute_dynamic_factor_series

# 不同 interval 近似年化换算
_BARS_PER_YEAR = {
    "1m": 252 * 24 * 60,
    "5m": 252 * 24 * 12,
    "15m": 252 * 24 * 4,
    "1h": 252 * 24,
    "4h": 252 * 6,
    "1d": 252,
}


def _normalize_weights_override(weights_override: dict[str, float] | None, cols: list[str]) -> dict[str, float] | None:
    if not weights_override or not cols:
        return None
    raw = {c: float(weights_override.get(c, 0) or 0) for c in cols}
    s = sum(max(0.0, v) for v in raw.values())
    if s < 1e-12:
        return None
    return {c: max(0.0, raw[c]) / s for c in cols}


def analyze_symbol(
    symbol: str,
    candles: list[dict],
    risk_settings: dict | None = None,
    interval: str = "1h",
    total_usdt: float | None = None,
    *,
    active_factors: list[str] | None = None,
    weights_override: dict[str, float] | None = None,
    max_opens_per_day: int | None = None,
    avg_daily_mode: str = "trading",
    dynamic_factor_expressions: dict[str, str] | None = None,
) -> dict:
    """
    返回供 DeepSeek 审核与前端展示的完整策略包（对齐 strategy.md 能力栈的可实现子集）。

    调用方式：在业务代码中 ``from services.strategy_engine.runner import analyze_symbol``，
    传入从 Gate 拉取的真实 ``candles``（或由 ``utils.gate_client.list_candlesticks`` 返回的列表）。

    自测请用：``cd backend`` 后 ``python -m services.strategy_engine.runner``（合成数据冒烟），
    与实盘/审核链路无关。
    """
    risk_settings = risk_settings or {}
    max_pos = float(risk_settings.get("max_position_pct", 0.2) or 0.2)
    max_single = float(risk_settings.get("max_single_order_pct", max_pos) or max_pos)
    stop_loss_setting = float(risk_settings.get("stop_loss", -0.05) or -0.05)

    df0 = candles_to_df(candles)
    if df0.empty or len(df0) < 40:
        return {
            "ok": False,
            "symbol": symbol,
            "error": "K 线数据不足，无法运行策略引擎",
        }

    df, factor_cols = add_factor_columns(df0)
    if not factor_cols:
        return {"ok": False, "symbol": symbol, "error": "因子计算失败"}

    dyn_map = dynamic_factor_expressions or {}
    if dyn_map:
        needed_dyn_cols: list[str] = []
        if active_factors:
            needed_dyn_cols = [str(x) for x in active_factors if str(x).strip() and str(x) in dyn_map]
        else:
            needed_dyn_cols = [str(k) for k in dyn_map.keys()]
        for dyn_col in needed_dyn_cols:
            if dyn_col in df.columns:
                continue
            expr = dyn_map.get(dyn_col)
            if not expr:
                continue
            try:
                df[dyn_col] = compute_dynamic_factor_series(df, expr)
            except Exception:
                return {"ok": False, "symbol": symbol, "error": f"动态因子计算失败: {dyn_col}"}
        factor_cols = list(factor_cols) + [c for c in needed_dyn_cols if c in df.columns and c not in factor_cols]

    use_cols = resolve_active_factor_cols(factor_cols, active_factors)
    if not use_cols:
        return {"ok": False, "symbol": symbol, "error": "无有效因子列"}

    eval_res = evaluate_factors_ic(df, use_cols)
    ic_map = eval_res.get("factors") or {}
    w_override = _normalize_weights_override(weights_override, use_cols)
    if w_override:
        weights = w_override
    else:
        weights = icir_weights(ic_map)
        if not weights:
            weights = {c: round(1.0 / len(use_cols), 4) for c in use_cols}

    ml = train_predict_ml(df, use_cols)
    bt = run_simple_backtest(
        df,
        use_cols,
        weights,
        bars_per_year=_BARS_PER_YEAR.get(interval, 252 * 24),
        max_opens_per_day=max_opens_per_day,
        avg_daily_mode=avg_daily_mode,
    )

    score_series = composite_score_series(df, use_cols, weights)
    last_score = finite_float(score_series.iloc[-1] if len(score_series) else 0.0, 0.0)

    tail = score_series.iloc[-80:] if len(score_series) >= 40 else score_series
    q_hi = safe_quantile(tail, 0.55, 0.0)
    q_lo = safe_quantile(tail, 0.45, 0.0)

    direction = "buy" if last_score > q_hi else "sell" if last_score < q_lo else "hold"
    if direction == "hold" and last_score > 0:
        direction = "buy"
    if direction == "hold" and last_score < 0:
        direction = "sell"

    last = df.iloc[-1]
    close = finite_float(last["close"], 0.0)
    if close <= 0:
        return {"ok": False, "symbol": symbol, "error": "收盘价无效"}

    atr = optional_positive_float(last.get("atr_14"))

    side = "buy" if direction in ("buy", "hold") else "sell"
    if direction == "hold":
        side = "buy"
    sl_price, tp_price = atr_stops(close, atr, side=side, atr_sl_mult=2.0, rr=1.5)

    ret = df["close"].pct_change()
    vol = realized_vol(ret, 20)

    win_rate = float(bt.get("win_rate") or 0.5) if bt.get("ok") else 0.5
    avg_win = float(bt.get("avg_win") or 0.01) if bt.get("ok") else 0.01
    avg_loss = float(bt.get("avg_loss") or -0.01) if bt.get("ok") else -0.01
    kf = kelly_fraction(win_rate, avg_win, avg_loss, cap=0.2)
    kf = min(kf, max_pos)

    pos_info = suggest_position_usdt(total_usdt, close, max_pos, kf, max_single)

    factors_now = latest_factor_snapshot(df, use_cols)

    package = {
        "ok": True,
        "symbol": symbol,
        "interval": interval,
        "strategy_doc_ref": "backend/strategy.md — 因子挖掘/评估、ML、动态权重、回测、风险仓位",
        "latest_close": close,
        "composite_score": round(last_score, 6),
        "signal_direction": direction,
        "factors_latest": factors_now,
        "factor_evaluation": eval_res,
        "dynamic_weights": weights,
        "active_factors_resolved": use_cols,
        "machine_learning": ml,
        "backtest": bt,
        "risk_metrics": {
            "realized_vol_20": round(vol, 6),
            "atr_14": round(atr, 8) if atr is not None else None,
            "kelly_suggested": round(kf, 4),
            "stop_loss_pct_setting": stop_loss_setting,
        },
        "suggested_order": {
            "side": side,
            "order_type": "limit",
            "price": str(round(close, 8)),
            "amount": str(pos_info.get("amount_base") or ""),
            "stop_loss_price": str(sl_price),
            "take_profit_price": str(tp_price),
            "rationale": "多因子加权得分 + 滚动 IC 动态权重；ML 概率与回测统计用于辅助；止损止盈基于 ATR 与盈亏比。",
        },
        "position_sizing": pos_info,
    }

    if not pos_info.get("amount_base") and total_usdt is None:
        package["suggested_order"]["note"] = "未绑定账户或总资产未知，amount 为空，审核时可由 DeepSeek 或用户补全。"

    return package


if __name__ == "__main__":
    import json
    import random

    # 冒烟：合成 K 线，不访问交易所
    random.seed(42)
    base = 100.0
    candles: list[dict] = []
    for _ in range(160):
        base *= 1 + random.uniform(-0.02, 0.022)
        o, h, low, c = base * 0.999, base * 1.002, base * 0.998, base
        candles.append({"open": o, "high": h, "low": low, "close": c, "volume": 1e6})

    out = analyze_symbol("DEMO_USDT", candles, interval="1h", total_usdt=1000.0)
    preview = {
        "ok": out.get("ok"),
        "symbol": out.get("symbol"),
        "signal_direction": out.get("signal_direction"),
        "composite_score": out.get("composite_score"),
        "ml_available": (out.get("machine_learning") or {}).get("available"),
        "backtest_ok": (out.get("backtest") or {}).get("ok"),
        "error": out.get("error"),
    }
    print("strategy_engine.runner 冒烟测试（合成 K 线）：")
    print(json.dumps(preview, ensure_ascii=False, indent=2))
    print("\n业务代码请: from services.strategy_engine.runner import analyze_symbol")
