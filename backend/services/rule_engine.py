"""选币规则引擎 - 从 tickers 中筛选优质候选，规则可调"""
from typing import Any


def _get_attr(obj: Any, key: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _to_float(v, default=0.0):
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


# 默认规则（可被前端传入覆盖）
DEFAULT_RULES = {
    "min_quote_volume": 50_000,       # 24h 成交额最低 5 万 USDT
    "max_change_24h": 1.0,            # 24h 涨跌幅不超过 ±100%
    "min_price": 1e-8,                # 最低价格
}


def get_default_rules() -> dict:
    """返回默认规则"""
    return DEFAULT_RULES.copy()


def apply_rules(tickers: list, mode: str = "real", rules_override: dict | None = None) -> list[dict]:
    """
    对 tickers 应用规则，返回通过筛选的候选列表。
    每个候选: {symbol, volume, change_pct, last, reason}
    rules_override: 可覆盖 min_quote_volume, max_change_24h, min_price
    """
    rules = {**DEFAULT_RULES, **(rules_override or {})}
    min_vol = rules.get("min_quote_volume", DEFAULT_RULES["min_quote_volume"])
    max_chg = rules.get("max_change_24h", DEFAULT_RULES["max_change_24h"])
    min_price = rules.get("min_price", DEFAULT_RULES["min_price"])
    candidates = []

    for t in tickers:
        cp = _get_attr(t, "currency_pair")
        if not cp or "_USDT" not in str(cp).upper():
            continue

        quote_vol = _get_attr(t, "quote_volume") or _get_attr(t, "base_volume")
        vol = _to_float(quote_vol)
        last = _to_float(_get_attr(t, "last"))
        chg_raw = _get_attr(t, "change_percentage") or _get_attr(t, "change_pct")
        chg = _to_float(chg_raw, 0)
        if abs(chg) > 1 and abs(chg) <= 100:
            chg = chg / 100  # Gate 可能返回 0-100 比例

        if vol < min_vol and min_vol > 0:
            continue
        if last < min_price:
            continue
        if abs(chg) > max_chg:
            continue

        reason = "高流动性" if vol >= min_vol else "主流币"
        if chg > 0.05:
            reason += "、趋势向上"
        elif chg < -0.05:
            reason += "、短期回调"

        candidates.append({
            "symbol": cp,
            "volume": vol,
            "change_pct": chg,
            "last": last,
            "reason": reason,
        })

    if not candidates:
        for t in tickers:
            cp = _get_attr(t, "currency_pair")
            if not cp or "_USDT" not in str(cp).upper():
                continue
            vol = _to_float(_get_attr(t, "quote_volume") or _get_attr(t, "base_volume"))
            candidates.append({"symbol": cp, "volume": vol, "change_pct": 0, "last": 0, "reason": "高流动性"})

    return sorted(candidates, key=lambda x: (x["volume"], x["symbol"]), reverse=True)
