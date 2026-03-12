"""Gate.io API 封装，按 mode 切换 host

- 实盘：https://api.gateio.ws/api/v4（Gate.io 主站 API Key）
- 模拟：https://api-testnet.gateapi.io/api/v4（testnet.gate.io 创建的 Testnet API Key）

注意：Testnet Key 与主站 Key 不同，Testnet Key 需在 testnet.gate.io 创建，仅限 api-testnet 使用。
"""
import os
import gate_api
from gate_api import Configuration, ApiClient, SpotApi

HOST_REAL = "https://api.gateio.ws/api/v4"
# Testnet Key 专用地址；若用主站「模拟账户」Key 可设 GATE_SIMULATED_HOST=https://api.gateio.ws/api/v4
HOST_SIMULATED = os.environ.get("GATE_SIMULATED_HOST", "https://api-testnet.gateapi.io/api/v4")


def get_config(mode: str = "real") -> Configuration:
    """按 mode 返回 Configuration"""
    host = HOST_REAL if mode == "real" else HOST_SIMULATED
    return Configuration(host=host)


def get_client(mode: str, api_key: str, api_secret: str) -> ApiClient:
    """获取带认证的 ApiClient"""
    config = get_config(mode)
    config.key = api_key
    config.secret = api_secret
    return ApiClient(config)


def list_currency_pairs(mode: str = "real") -> list:
    """获取交易对列表"""
    try:
        api = SpotApi(ApiClient(get_config(mode)))
        pairs = api.list_currency_pairs()
        return [{"symbol": getattr(p, "id", p) if hasattr(p, "id") else str(p), "base": getattr(p, "base", ""), "quote": getattr(p, "quote", "")} for p in pairs]
    except Exception:
        return []


def list_tickers(mode: str = "real"):
    """获取行情"""
    try:
        api = SpotApi(ApiClient(get_config(mode)))
        return api.list_tickers()
    except Exception:
        return []


def list_candlesticks(symbol: str, interval: str, from_ts: int = None, to_ts: int = None, limit: int = 300, mode: str = "real"):
    """获取 K 线数据，返回 [{time, open, high, low, close, volume}, ...]
    Gate.io 格式: [t, 成交额(quote), c, h, l, o, 成交量(base), w]，成交量在索引 6"""
    try:
        api = SpotApi(ApiClient(get_config(mode)))
        candles = api.list_candlesticks(currency_pair=symbol, interval=interval, _from=from_ts, to=to_ts, limit=limit)
        result = []
        for c in candles:
            d = c.to_dict() if hasattr(c, "to_dict") else (c if isinstance(c, dict) else {})
            t = d.get("t") or d.get("time") or (c[0] if isinstance(c, (list, tuple)) else 0)
            o = d.get("o") or d.get("open") or (float(c[5]) if isinstance(c, (list, tuple)) and len(c) >= 6 else 0)
            h = d.get("h") or d.get("high") or (float(c[3]) if isinstance(c, (list, tuple)) and len(c) >= 4 else 0)
            l = d.get("l") or d.get("low") or (float(c[4]) if isinstance(c, (list, tuple)) and len(c) >= 5 else 0)
            cl = d.get("c") or d.get("close") or (float(c[2]) if isinstance(c, (list, tuple)) and len(c) >= 3 else 0)
            # 成交量：索引 6=base 货币数量，索引 1=quote 货币成交额，优先用 base 成交量
            v = d.get("v") or d.get("volume")
            if v is None and isinstance(c, (list, tuple)):
                v = float(c[6]) if len(c) >= 7 else (float(c[1]) if len(c) >= 2 else 0)
            v = float(v) if v is not None else 0
            result.append({"time": int(t), "open": float(o), "high": float(h), "low": float(l), "close": float(cl), "volume": float(v)})
        return result
    except Exception:
        return []
