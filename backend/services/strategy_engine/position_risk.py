"""风险评估与仓位：历史波动、简化 Kelly、ATR 止损止盈与盈亏比"""
from __future__ import annotations

import math


def realized_vol(ret, window: int = 20) -> float:
    if ret.dropna().empty:
        return 0.05
    v = float(ret.iloc[-window:].std()) if len(ret) >= 5 else float(ret.std())
    return max(v, 1e-6)


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float, cap: float = 0.2) -> float:
    """简化 Kelly：b = 平均盈利/平均亏损绝对值"""
    if avg_loss == 0 or win_rate <= 0 or win_rate >= 1:
        return min(0.05, cap)
    b = abs(avg_win / avg_loss) if avg_loss != 0 else 1.0
    q = 1.0 - win_rate
    f = (win_rate * b - q) / b if b > 0 else 0.0
    return float(max(0.0, min(f, cap)))


def atr_stops(last_close: float, atr: float | None, side: str = "buy", atr_sl_mult: float = 2.0, rr: float = 1.5):
    """做多：止损价、止盈价（盈亏比 rr）"""
    if atr is None or (isinstance(atr, float) and math.isnan(atr)) or atr <= 0:
        atr = last_close * 0.02
    if side == "buy":
        sl = last_close - atr_sl_mult * atr
        tp = last_close + rr * atr_sl_mult * atr
    else:
        sl = last_close + atr_sl_mult * atr
        tp = last_close - rr * atr_sl_mult * atr
    return round(sl, 8), round(tp, 8)


def suggest_position_usdt(
    total_usdt: float | None,
    last_close: float,
    max_position_pct: float,
    kelly_f: float,
    max_single_order_pct: float | None = None,
) -> dict:
    if not total_usdt or total_usdt <= 0 or last_close <= 0:
        return {"usdt_alloc": None, "amount_base": None, "position_pct_applied": None}
    cap = min(max_position_pct, kelly_f)
    if max_single_order_pct is not None:
        cap = min(cap, max_single_order_pct)
    cap = max(cap, 0.001)
    usdt = total_usdt * cap
    amt = usdt / last_close
    return {
        "usdt_alloc": round(usdt, 4),
        "amount_base": round(amt, 8),
        "position_pct_applied": round(cap, 4),
    }
