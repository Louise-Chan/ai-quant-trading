"""Gate.io 账户数据服务 - 投资组合、资产、订单、持仓、成交"""
from decimal import Decimal, ROUND_DOWN, ROUND_UP

from gate_api import SpotApi, FuturesApi
from utils.gate_client import get_client, get_spot_ticker_last, list_tickers


def _to_dict(obj):
    """将 Gate API 对象转为 dict"""
    if obj is None:
        return None
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return dict(obj) if isinstance(obj, (dict, list)) else str(obj)


def get_spot_accounts(mode: str, api_key: str, api_secret: str):
    """
    获取现货账户余额列表，直接调用 Gate.io API。
    接口: GET /spot/accounts (查询资产信息)
    文档: https://www.gate.io/docs/developers/apiv4/zh_CN/#%E6%9F%A5%E8%AF%A2%E8%B5%84%E4%BA%A7%E4%BF%A1%E6%81%AF

    地址说明:
    - 实盘: api.gate.com/api/v4（默认，见 utils.gate_client.HOST_REAL）
    - 模拟(Testnet Key): api-testnet.gateapi.io (testnet 创建)
    - 模拟(主站模拟账户 Key): 需设 GATE_SIMULATED_HOST=https://api.gate.com/api/v4
    """
    client = get_client(mode, api_key, api_secret)
    api = SpotApi(client)
    accounts = api.list_spot_accounts()
    return [
        {
            "currency": getattr(a, "currency", "") or (a.get("currency") if isinstance(a, dict) else ""),
            "available": float(getattr(a, "available", "0") or (a.get("available", "0") if isinstance(a, dict) else "0") or 0),
            "locked": float(getattr(a, "locked", "0") or (a.get("locked", "0") if isinstance(a, dict) else "0") or 0),
        }
        for a in (accounts or [])
    ]


def get_open_orders(mode: str, api_key: str, api_secret: str, page: int = 1, limit: int = 100):
    """获取所有未成交订单，直接调用 Gate.io API"""
    client = get_client(mode, api_key, api_secret)
    api = SpotApi(client)
    result = api.list_all_open_orders(page=page, limit=limit)
    orders = []
    for item in (result or []):
        cp = getattr(item, "currency_pair", "") or (item.get("currency_pair", "") if isinstance(item, dict) else "")
        lst = getattr(item, "orders", []) or (item.get("orders", []) if isinstance(item, dict) else [])
        for o in lst:
            d = _to_dict(o) if o else {}
            d["currency_pair"] = cp
            orders.append({
                "id": d.get("id"),
                "symbol": d.get("currency_pair", cp),
                "side": d.get("side", ""),
                "amount": d.get("amount", "0"),
                "price": d.get("price", "0"),
                "status": "open",
                "create_time": d.get("create_time"),
                "left": d.get("left", d.get("amount", "0")),
            })
    return orders


def get_finished_orders(mode: str, api_key: str, api_secret: str, currency_pair: str = None,
                        symbols: list = None, page: int = 1, limit: int = 100):
    """
    获取已成交/已撤单订单。
    currency_pair: 单个交易对；symbols: 多个交易对（会合并结果）
    若都不传则默认查 BTC_USDT
    """
    try:
        client = get_client(mode, api_key, api_secret)
        api = SpotApi(client)
        pairs = []
        if currency_pair:
            pairs = [currency_pair]
        elif symbols:
            pairs = list(symbols)[:20]  # 限制数量
        if not pairs:
            pairs = ["BTC_USDT"]

        all_orders = []
        for cp in pairs:
            try:
                orders = api.list_orders(currency_pair=cp, status="finished", page=page, limit=limit)
                for o in (orders or []):
                    d = _to_dict(o)
                    all_orders.append({
                        "id": d.get("id"),
                        "symbol": d.get("currency_pair", cp),
                        "side": d.get("side", ""),
                        "amount": d.get("amount", "0"),
                        "price": d.get("price", "0"),
                        "status": d.get("status", "finished"),
                        "create_time": d.get("create_time"),
                        "filled_amount": d.get("filled_amount", "0"),
                        "finish_as": d.get("finish_as", ""),
                    })
            except Exception:
                continue
        # 按时间倒序
        all_orders.sort(key=lambda x: x.get("create_time") or "", reverse=True)
        return all_orders[:limit]
    except Exception:
        raise  # 认证/网络错误向上传播


def get_my_trades(mode: str, api_key: str, api_secret: str, currency_pair: str = None,
                  page: int = 1, limit: int = 100):
    """获取成交记录"""
    try:
        client = get_client(mode, api_key, api_secret)
        api = SpotApi(client)
        kwargs = {"page": page, "limit": limit}
        if currency_pair:
            kwargs["currency_pair"] = currency_pair
        trades = api.list_my_trades(**kwargs)
        return [
            {
                "id": _to_dict(t).get("id"),
                "symbol": _to_dict(t).get("currency_pair", ""),
                "side": _to_dict(t).get("side", ""),
                "amount": _to_dict(t).get("amount", "0"),
                "price": _to_dict(t).get("price", "0"),
                "fee": _to_dict(t).get("fee", "0"),
                "create_time": _to_dict(t).get("create_time"),
                "order_id": _to_dict(t).get("order_id"),
            }
            for t in (trades or [])
        ]
    except Exception:
        raise  # 认证/网络错误向上传播


def get_spot_order(mode: str, api_key: str, api_secret: str, order_id: str, currency_pair: str) -> dict | None:
    """查询单个现货订单状态"""
    try:
        client = get_client(mode, api_key, api_secret)
        api = SpotApi(client)
        o = api.get_order(order_id=order_id, currency_pair=currency_pair)
        d = _to_dict(o) or {}
        amt = d.get("amount")
        left = d.get("left")
        try:
            fa = float(amt or 0) - float(left or 0)
        except (TypeError, ValueError):
            fa = 0.0
        return {
            "id": d.get("id"),
            "status": d.get("status"),
            "side": d.get("side"),
            "amount": amt,
            "left": left,
            "price": d.get("price"),
            "filled_base": fa,
            "finish_as": d.get("finish_as"),
            "create_time": d.get("create_time"),
            "avg_deal_price": d.get("avg_deal_price"),
        }
    except Exception:
        return None


def amend_spot_order_price(
    mode: str,
    api_key: str,
    api_secret: str,
    order_id: str,
    currency_pair: str,
    price: str,
) -> None:
    """修改现货限价单价格（用于止损/止盈保护单改价）"""
    from gate_api.models import OrderPatch

    client = get_client(mode, api_key, api_secret)
    api = SpotApi(client)
    patch = OrderPatch(
        currency_pair=currency_pair,
        account="spot",
        price=str(price).strip(),
    )
    api.amend_order(
        order_id=str(order_id),
        order_patch=patch,
        currency_pair=currency_pair,
    )


def cancel_order(mode: str, api_key: str, api_secret: str, order_id: str, currency_pair: str):
    """撤单"""
    try:
        client = get_client(mode, api_key, api_secret)
        api = SpotApi(client)
        api.cancel_order(order_id=order_id, currency_pair=currency_pair)
        return True
    except Exception:
        return False


def cancel_all_spot_open_orders_for_pair(
    mode: str, api_key: str, api_secret: str, currency_pair: str, max_pages: int = 30
) -> tuple[list[str], list[str]]:
    """
    撤销指定交易对下所有当前未成交现货挂单。
    返回 (成功撤单的 order_id 列表, 失败信息列表)
    """
    cp = (currency_pair or "").strip().upper()
    if not cp:
        return [], ["empty symbol"]
    cancelled: list[str] = []
    errors: list[str] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        batch = get_open_orders(mode, api_key, api_secret, page=page, limit=100)
        if not batch:
            break
        for o in batch:
            sym = (o.get("symbol") or "").strip().upper()
            if sym != cp:
                continue
            oid = o.get("id")
            if oid is None:
                continue
            sid = str(oid)
            if sid in seen:
                continue
            seen.add(sid)
            try:
                if cancel_order(mode, api_key, api_secret, sid, cp):
                    cancelled.append(sid)
                else:
                    errors.append(f"撤单失败 order_id={sid}")
            except Exception as ex:
                errors.append(f"撤单异常 order_id={sid}: {ex}")
        if len(batch) < 100:
            break
    return cancelled, errors


def market_sell_all_base_for_pair(
    mode: str, api_key: str, api_secret: str, currency_pair: str
) -> dict:
    """
    将该交易对基础币可用+冻结余额全部市价卖出（用于一键平仓现货多头）。
    返回 { "order_id": str|None, "amount": str|None, "skipped": bool, "error": str|None }
    """
    cp = (currency_pair or "").strip().upper()
    out: dict = {"order_id": None, "amount": None, "skipped": True, "error": None}
    if "_" not in cp:
        out["error"] = "无效交易对"
        return out
    base = cp.split("_")[0]
    accounts = get_spot_accounts(mode, api_key, api_secret)
    amt = 0.0
    for a in accounts or []:
        if (a.get("currency") or "") == base:
            amt = float(a.get("available") or 0) + float(a.get("locked") or 0)
            break
    if amt <= 0:
        return out
    d = Decimal(str(amt))
    s = format(d.normalize(), "f").rstrip("0").rstrip(".")
    if not s or s == "0":
        return out
    out["amount"] = s
    out["skipped"] = False
    try:
        oid, _raw = create_spot_order(mode, api_key, api_secret, cp, "sell", "market", s, None)
        out["order_id"] = str(oid) if oid is not None else None
    except Exception as ex:
        out["error"] = str(ex)
    return out


def close_spot_symbol_flat(
    mode: str, api_key: str, api_secret: str, currency_pair: str
) -> dict:
    """
    一键结束某现货标的：撤销该交易对全部挂单，再市价卖出全部基础币持仓。
    """
    cancelled, cancel_errs = cancel_all_spot_open_orders_for_pair(mode, api_key, api_secret, currency_pair)
    sell_res = market_sell_all_base_for_pair(mode, api_key, api_secret, currency_pair)
    return {
        "symbol": (currency_pair or "").strip().upper(),
        "cancelled_order_ids": cancelled,
        "cancel_errors": cancel_errs,
        "market_sell": sell_res,
    }


def get_futures_usdt_total_balance(mode: str, api_key: str, api_secret: str) -> tuple[float, float, float]:
    """
    U 本位合约账户总资产（USDT 计价）。返回 (available, frozen, total)
    接口: GET /futures/{settle}/accounts
    """
    client = get_client(mode, api_key, api_secret)
    api = FuturesApi(client)
    acc = api.list_futures_accounts("usdt")
    if not acc:
        return 0.0, 0.0, 0.0
    d = _to_dict(acc) or {}
    try:
        total = float(d.get("total") or 0)
        avail = float(d.get("available") or 0)
    except (TypeError, ValueError):
        return 0.0, 0.0, 0.0
    frozen = max(0.0, total - avail)
    return avail, frozen, total


def get_total_balance_usdt(mode: str, api_key: str, api_secret: str) -> tuple[float, float, float]:
    """
    计算总资产（USDT 计价）。返回 (available, frozen, total)
    使用 list_spot_accounts + list_tickers 将各币种折算为 USDT
    """
    accounts = get_spot_accounts(mode, api_key, api_secret)
    if not accounts:
        return 0.0, 0.0, 0.0

    tickers = list_tickers(mode)
    ticker_map = {}
    if tickers:
        for t in tickers:
            cp = getattr(t, "currency_pair", None) or (t.get("currency_pair") if isinstance(t, dict) else "")
            last = float(getattr(t, "last", "0") or (t.get("last", "0") if isinstance(t, dict) else "0") or 0)
            ticker_map[cp] = last

    total_avail = 0.0
    total_locked = 0.0
    for acc in accounts:
        curr = acc["currency"]
        avail = acc["available"]
        locked = acc["locked"]
        if curr == "USDT":
            total_avail += avail
            total_locked += locked
        else:
            cp = f"{curr}_USDT"
            price = ticker_map.get(cp) or 0
            total_avail += avail * price
            total_locked += locked * price
    return total_avail, total_locked, total_avail + total_locked


def get_positions_with_value(mode: str, api_key: str, api_secret: str) -> list:
    """获取持仓列表（非 USDT 且余额>0 的币种），含市值"""
    accounts = get_spot_accounts(mode, api_key, api_secret)
    positions = [a for a in accounts if a["currency"] != "USDT" and (a["available"] + a["locked"]) > 0]
    if not positions:
        return []

    tickers = list_tickers(mode)
    ticker_map = {}
    if tickers:
        for t in tickers:
            cp = getattr(t, "currency_pair", None) or (t.get("currency_pair") if isinstance(t, dict) else "")
            last = float(getattr(t, "last", "0") or (t.get("last", "0") if isinstance(t, dict) else "0") or 0)
            ticker_map[cp] = last

    result = []
    for p in positions:
        curr = p["currency"]
        amount = p["available"] + p["locked"]
        cp = f"{curr}_USDT"
        price = ticker_map.get(cp) or 0
        value_usdt = amount * price
        result.append({
            "symbol": cp,
            "currency": curr,
            "amount": amount,
            "available": p["available"],
            "locked": p["locked"],
            "price": price,
            "value_usdt": value_usdt,
        })
    return result


# Gate 现货常见最小成交额（USDT 计价）；以接口返回为准，略抬高避免舍入踩线
MIN_SPOT_ORDER_QUOTE_USDT = Decimal("3.01")


def _fmt_spot_base_amount(d: Decimal) -> str:
    s = format(d, "f").rstrip("0").rstrip(".")
    return s if s else "0"


def adjust_spot_amount_min_quote_usdt(
    mode: str,
    api_key: str,
    api_secret: str,
    currency_pair: str,
    amount_str: str,
    order_type: str,
    limit_price_str: str | None,
    side: str,
) -> tuple[str, str | None]:
    """
    若 amount * 参考价 低于 Gate 现货最小成交额（约 3 USDT），则提高数量至满足下限。
    限价单用委托价；市价或无有效价时用最新成交价估算。
    返回 (调整后的数量字符串, 若有调整则为说明文案)。
    """
    cp = (currency_pair or "").strip().upper()
    st = (side or "").lower()
    ot = (order_type or "limit").lower()
    try:
        amt = Decimal(str(amount_str).strip().replace(",", ""))
    except Exception:
        return str(amount_str).strip(), None
    if amt <= 0:
        return str(amount_str).strip(), None

    px_f: float | None = None
    if ot == "limit" and limit_price_str and str(limit_price_str).strip():
        try:
            px_f = float(str(limit_price_str).strip().replace(",", ""))
        except ValueError:
            px_f = None
    if px_f is None or px_f <= 0:
        px_f = get_spot_ticker_last(mode, cp)
    if px_f is None or px_f <= 0:
        return _fmt_spot_base_amount(amt), None

    px = Decimal(str(px_f))
    min_q = MIN_SPOT_ORDER_QUOTE_USDT
    notional = amt * px
    if notional >= min_q:
        return _fmt_spot_base_amount(amt), None

    target = (min_q / px) * Decimal("1.006")
    target = target.quantize(Decimal("0.00000001"), rounding=ROUND_UP)

    accounts = get_spot_accounts(mode, api_key, api_secret)
    base_cur = cp.split("_")[0] if "_" in cp else ""

    if st == "sell":
        max_base = Decimal("0")
        for a in accounts or []:
            if (a.get("currency") or "") == base_cur:
                max_base = Decimal(str(a.get("available", 0))) + Decimal(str(a.get("locked", 0)))
                break
        if max_base <= 0:
            raise ValueError(
                "无法执行：该笔卖出折合不足 3 USDT，且账户中无可卖基础币；请提高数量或先买入/划转。"
            )
        if target > max_base:
            target = max_base.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        if target <= 0 or target * px < min_q:
            raise ValueError(
                f"无法执行：当前可卖基础币折合仍不足 Gate 最小成交额 3 USDT（约需再多卖一些或换流动性更好的对）。"
            )
    elif st == "buy":
        usdt_av = Decimal("0")
        for a in accounts or []:
            if (a.get("currency") or "") == "USDT":
                usdt_av = Decimal(str(a.get("available", 0)))
                break
        need = target * px
        if need > usdt_av:
            raise ValueError(
                f"无法执行：为满足最小成交额约 3 USDT，需约 {float(need):.2f} USDT，"
                f"当前可用 USDT 约 {float(usdt_av):.2f}，请充值或减少其它冻结。"
            )

    orig = _fmt_spot_base_amount(amt)
    out = _fmt_spot_base_amount(target)
    note = f"数量已由 {orig} 调整为 {out}，以满足现货单笔最小成交额（约 3 USDT）。"
    return out, note


def create_spot_order(
    mode: str,
    api_key: str,
    api_secret: str,
    currency_pair: str,
    side: str,
    order_type: str,
    amount: str,
    price: str | None = None,
):
    """
    现货下单。side: buy | sell；order_type: limit | market。
    limit 必须提供 price；market 可不填 price（由交易所撮合）。
    返回 (order_id, raw_dict)
    """
    from gate_api.models import Order as GateOrder

    client = get_client(mode, api_key, api_secret)
    api = SpotApi(client)
    tif = "gtc" if (order_type or "").lower() == "limit" else "ioc"
    kwargs = dict(
        currency_pair=currency_pair,
        type=order_type,
        account="spot",
        side=side,
        amount=str(amount),
        time_in_force=tif,
    )
    if price is not None and str(price).strip() != "":
        kwargs["price"] = str(price)
    ord_obj = GateOrder(**kwargs)
    resp = api.create_order(ord_obj)
    d = _to_dict(resp) or {}
    oid = d.get("id")
    return oid, d
