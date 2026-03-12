"""Gate.io 账户数据服务 - 投资组合、资产、订单、持仓、成交"""
from gate_api import SpotApi
from utils.gate_client import get_client, list_tickers


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
    - 实盘: api.gateio.ws
    - 模拟(Testnet Key): api-testnet.gateapi.io (testnet.gate.io 创建)
    - 模拟(主站模拟账户 Key): 需设 GATE_SIMULATED_HOST=https://api.gateio.ws/api/v4
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


def cancel_order(mode: str, api_key: str, api_secret: str, order_id: str, currency_pair: str):
    """撤单"""
    try:
        client = get_client(mode, api_key, api_secret)
        api = SpotApi(client)
        api.cancel_order(order_id=order_id, currency_pair=currency_pair)
        return True
    except Exception:
        return False


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
