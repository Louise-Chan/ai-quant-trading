"""Gate API v4 封装，按 mode 切换 host（与 https://www.gate.com/docs/developers/apiv4/ 一致）

- 实盘默认：https://api.gate.com/api/v4（主站 API Key；多数网络下比 api.gateio.ws 更易解析）
- 模拟：https://api-testnet.gateapi.io/api/v4（testnet 创建的 Testnet Key）

注意：Testnet Key 与主站 Key 不同；主站模拟账户 Key 可设 GATE_SIMULATED_HOST 指向实盘根地址。

环境变量 GATE_REAL_API_BASE：覆盖实盘 REST 根地址（完整 URL，须以 /api/v4 结尾或仅域名由本模块补全），例如：
  GATE_REAL_API_BASE=https://api.gateio.ws/api/v4
"""
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv

    _env_path = Path(__file__).resolve().parents[1] / ".env"
    if _env_path.is_file():
        load_dotenv(_env_path, override=False)
except ImportError:
    pass

from gate_api import Configuration, ApiClient, SpotApi, FuturesApi

_HOST_REAL_DEFAULT = "https://api.gate.com/api/v4"
_raw_base = (os.environ.get("GATE_REAL_API_BASE") or "").strip()
HOST_REAL = (_raw_base if _raw_base else _HOST_REAL_DEFAULT).rstrip("/")
if not HOST_REAL.endswith("/api/v4"):
    HOST_REAL = f"{HOST_REAL.rstrip('/')}/api/v4"
# Testnet Key 专用；主站「模拟账户」Key 可设 GATE_SIMULATED_HOST=https://api.gate.com/api/v4
HOST_SIMULATED = os.environ.get("GATE_SIMULATED_HOST", "https://api-testnet.gateapi.io/api/v4")
# 模拟模式下公共行情是否走主站实盘（看盘/回测与主站一致；下单仍走 HOST_SIMULATED）。
# 默认 1：模拟 + 实盘行情 + 模拟交易 API。
SIMULATED_PUBLIC_USE_REAL = os.environ.get("GATE_SIMULATED_PUBLIC_USE_REAL", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)


def get_config(mode: str = "real") -> Configuration:
    """按 mode 返回 Configuration"""
    host = HOST_REAL if mode == "real" else HOST_SIMULATED
    return Configuration(host=host)


def get_public_config(mode: str = "real") -> Configuration:
    """
    公共行情接口使用的 host。
    当 mode=simulated 且开启 SIMULATED_PUBLIC_USE_REAL 时，返回主站行情 host。
    """
    if mode != "real" and SIMULATED_PUBLIC_USE_REAL:
        return Configuration(host=HOST_REAL)
    return get_config(mode)


def get_real_public_config() -> Configuration:
    """公共 K 线等行情固定走主站实盘（与交易模式无关）。"""
    return Configuration(host=HOST_REAL)


def _normalize_api_v4_base(raw: str) -> str:
    if not (raw or "").strip():
        return ""
    h = raw.strip().rstrip("/")
    if not h.endswith("/api/v4"):
        h = f"{h.rstrip('/')}/api/v4"
    return h


# K 线除 HOST_REAL 外再尝试的实盘根（本机无法解析 api.gate.com 时常可解析 api.gateio.ws）
_KLINE_ALT_RAW = (os.environ.get("GATE_KLINE_ALT_REAL_BASE") or "https://api.gateio.ws/api/v4").strip()
KLINE_ALT_REAL_HOST = _normalize_api_v4_base(_KLINE_ALT_RAW)


def _iter_kline_real_hosts() -> list[str]:
    """去重后的实盘 REST 根，优先 HOST_REAL，再试备用域名。"""
    out: list[str] = []
    seen: set[str] = set()
    for h in (HOST_REAL, KLINE_ALT_REAL_HOST):
        hn = h.rstrip("/")
        if not hn or hn in seen:
            continue
        seen.add(hn)
        out.append(hn)
    return out


def _kline_fallback_testnet_enabled() -> bool:
    return os.environ.get("GATE_KLINE_FALLBACK_TESTNET", "1").strip().lower() in ("1", "true", "yes", "on")


def get_client(mode: str, api_key: str, api_secret: str) -> ApiClient:
    """获取带认证的 ApiClient"""
    config = get_config(mode)
    config.key = api_key
    config.secret = api_secret
    return ApiClient(config)


def list_currency_pairs(mode: str = "real") -> list:
    """获取交易对列表"""
    try:
        api = SpotApi(ApiClient(get_public_config(mode)))
        pairs = api.list_currency_pairs()
        return [{"symbol": getattr(p, "id", p) if hasattr(p, "id") else str(p), "base": getattr(p, "base", ""), "quote": getattr(p, "quote", "")} for p in pairs]
    except Exception:
        return []


def list_tickers(mode: str = "real"):
    """获取现货行情"""
    try:
        api = SpotApi(ApiClient(get_public_config(mode)))
        return api.list_tickers()
    except Exception:
        return []


def get_spot_ticker_last(mode: str, currency_pair: str) -> float | None:
    """单个交易对最新成交价（公共行情，无需密钥）"""
    try:
        api = SpotApi(ApiClient(get_public_config(mode)))
        lst = None
        try:
            lst = api.list_tickers(currency_pair=currency_pair)
        except TypeError:
            lst = None
        if not lst:
            all_t = api.list_tickers()
            cp = (currency_pair or "").strip().upper()
            for t in all_t or []:
                tid = getattr(t, "currency_pair", None) or (t.get("currency_pair") if isinstance(t, dict) else None)
                if str(tid or "").upper() == cp:
                    lst = [t]
                    break
        if not lst:
            return None
        t = lst[0]
        if hasattr(t, "last"):
            last = getattr(t, "last", None)
        elif isinstance(t, dict):
            last = t.get("last")
        else:
            last = None
        if last is None or last == "":
            return None
        return float(last)
    except Exception:
        return None


def list_futures_tickers(mode: str = "real", settle: str = "usdt"):
    """获取合约行情（U 本位），settle 如 usdt"""
    try:
        api = FuturesApi(ApiClient(get_public_config(mode)))
        return api.list_futures_tickers(settle)
    except Exception:
        return []


def _parse_spot_candle_row(c) -> dict | None:
    """将单根 K 线转为统一 dict"""
    d = c.to_dict() if hasattr(c, "to_dict") else (c if isinstance(c, dict) else {})
    t = d.get("t") or d.get("time") or (c[0] if isinstance(c, (list, tuple)) else 0)
    o = d.get("o") or d.get("open") or (float(c[5]) if isinstance(c, (list, tuple)) and len(c) >= 6 else 0)
    h = d.get("h") or d.get("high") or (float(c[3]) if isinstance(c, (list, tuple)) and len(c) >= 4 else 0)
    l = d.get("l") or d.get("low") or (float(c[4]) if isinstance(c, (list, tuple)) and len(c) >= 5 else 0)
    cl = d.get("c") or d.get("close") or (float(c[2]) if isinstance(c, (list, tuple)) and len(c) >= 3 else 0)
    v = d.get("v") or d.get("volume")
    if v is None and isinstance(c, (list, tuple)):
        v = float(c[6]) if len(c) >= 7 else (float(c[1]) if len(c) >= 2 else 0)
    v = float(v) if v is not None else 0
    if not t:
        return None
    return {"time": int(t), "open": float(o), "high": float(h), "low": float(l), "close": float(cl), "volume": float(v)}


_BAR_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "8h": 28800,
    "12h": 43200,
    "1d": 86400,
    "7d": 604800,
    "30d": 2592000,
}

# 现货 from+to 单次最多约 1000 根，超出则 400 INVALID（Candlestick range too broad）
_SPOT_MAX_BARS_PER_REQUEST = 999
_FUTURES_MAX_BARS_PER_REQUEST = 999
# Gate 现货 / 合约均有历史窗口上限：_from 不能早于「最近 10000 根」，否则 400
# INVALID_PARAM_VALUE: "Candlestick too long ago. Maximum 10000 points ago are allowed"
# 另外 Gate 服务端计点与我们客户端时钟存在毫秒级差异：预留若干根安全余量，避免边界抖动被拒
_SPOT_MAX_LOOKBACK_BARS = 10000
_SPOT_LOOKBACK_SAFETY_BARS = 30
_FUTURES_MAX_LOOKBACK_BARS = 10000


def _normalize_interval(interval: str | None) -> str:
    return (interval or "1h").strip().lower()


def _bar_seconds(interval: str) -> int:
    return max(1, _BAR_SECONDS.get(_normalize_interval(interval), 3600))


def candle_time_sec(c: dict) -> int:
    """K 线 time 字段统一为秒（Gate 多为秒；若为毫秒则折算）"""
    t = int(c.get("time") or 0)
    return t // 1000 if t > 10_000_000_000 else t


def list_candlesticks_range(
    symbol: str,
    interval: str,
    from_ts: int,
    to_ts: int,
    mode: str = "real",
    max_bars: int = 15000,
) -> list:
    """
    按 [from_ts, to_ts] Unix 秒区间拉取 K 线，去重后按时间升序。
    Gate 要求单次 from~to 对应 K 线数量 ≤1000，否则会 400；故按时间窗分块请求。
    另：
    - 现货 _from 若大于当前时刻会 400「invalid time range」（与 to 无关）；推进游标时遇未收盘周期会落在未来，需在此结束拉取。
    - 现货 / 合约 _from 不能早于「最近 10000 根」，否则 400「Candlestick too long ago」；自动夹断为最近允许的时刻。
    """
    iv = _normalize_interval(interval)
    from_ts = int(from_ts)
    to_ts = int(to_ts)
    if from_ts > to_ts:
        return []
    bar_sec = _bar_seconds(iv)
    now_sec_init = int(time.time())
    # 留 _SPOT_LOOKBACK_SAFETY_BARS 根安全余量，抵消网络/服务端时钟漂移造成的 "Candlestick too long ago"
    min_allowed_from = now_sec_init - (_SPOT_MAX_LOOKBACK_BARS - _SPOT_LOOKBACK_SAFETY_BARS) * bar_sec
    if from_ts < min_allowed_from:
        logger.info(
            "K线现货 from 超过 Gate 最近 %d 根上限（interval=%s symbol=%s），自动夹断为允许的最早时刻",
            _SPOT_MAX_LOOKBACK_BARS,
            iv,
            symbol,
        )
        from_ts = min_allowed_from
        if from_ts > to_ts:
            return []
    max_chunk_sec = bar_sec * _SPOT_MAX_BARS_PER_REQUEST
    out: list[dict] = []
    seen: set[int] = set()
    cursor = from_ts
    stall = 0
    while cursor <= to_ts and len(out) < max_bars and stall < 8:
        now_sec = int(time.time())
        # Gate：_from 晚于「当前时刻」会 400「invalid time range」（常见于 chunk_max_ts+bar 落到未收盘 K 线起点）
        if cursor > now_sec:
            break
        chunk_end = min(cursor + max_chunk_sec, to_ts)
        # Gate：from 必须严格小于 to，相等会 400 INVALID「invalid time range」
        if cursor >= chunk_end:
            break
        batch = _list_candlesticks_spot_single(symbol, iv, cursor, chunk_end, None, mode)
        parsed: list[dict] = []
        for c in batch or []:
            row = _parse_spot_candle_row(c)
            if row:
                parsed.append(row)
        if not parsed:
            stall += 1
            cursor = chunk_end + bar_sec
            continue
        stall = 0
        chunk_max_ts = max(candle_time_sec(r) for r in parsed)
        for row in parsed:
            ts = candle_time_sec(row)
            if ts < from_ts or ts > to_ts:
                continue
            key = int(row.get("time") or ts)
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
        nxt = chunk_max_ts + bar_sec
        if nxt <= cursor:
            nxt = cursor + bar_sec
        cursor = nxt
        if chunk_end >= to_ts and chunk_max_ts >= to_ts - bar_sec:
            break
    out.sort(key=lambda x: int(x.get("time") or 0))
    return out


def _spot_candlesticks_raw(
    api: SpotApi,
    symbol: str,
    iv: str,
    from_ts: int | None,
    to_ts: int | None,
    limit: int | None,
):
    """单次 HTTP；limit 与 from/to 互斥。"""
    if from_ts is not None or to_ts is not None:
        fs = int(from_ts) if from_ts is not None else None
        te = int(to_ts) if to_ts is not None else None
        if fs is not None and te is not None and fs >= te:
            return []
        kwargs: dict = {"currency_pair": symbol, "interval": iv}
        if fs is not None:
            kwargs["_from"] = fs
        if te is not None:
            kwargs["to"] = te
        return api.list_candlesticks(**kwargs)
    return api.list_candlesticks(currency_pair=symbol, interval=iv, limit=limit or 300)


def _list_candlesticks_spot_single(
    symbol: str,
    interval: str,
    from_ts: int | None,
    to_ts: int | None,
    limit: int | None,
    mode: str,
):
    """单次 HTTP；优先主站实盘，失败则换备用实盘域名；仍失败且为模拟模式时可回退 Testnet（非主站价，仅保底出图）。"""
    iv = _normalize_interval(interval)
    last_err: Exception | None = None
    for host in _iter_kline_real_hosts():
        try:
            api = SpotApi(ApiClient(Configuration(host=host)))
            return _spot_candlesticks_raw(api, symbol, iv, from_ts, to_ts, limit)
        except Exception as e:
            last_err = e
            logger.info("K线现货请求失败 host=%s: %s", host, e)
    if _kline_fallback_testnet_enabled() and mode == "simulated":
        logger.warning(
            "K线主站实盘均不可用，回退 Testnet 公共接口（价格与主站不一致，仅保底）: %s",
            last_err,
        )
        try:
            api = SpotApi(ApiClient(Configuration(host=HOST_SIMULATED)))
            return _spot_candlesticks_raw(api, symbol, iv, from_ts, to_ts, limit)
        except Exception as e2:
            last_err = e2
    if last_err:
        logger.warning("K线现货拉取失败: %s", last_err)
    raise last_err if last_err else RuntimeError("K线现货无可用 host")


def list_candlesticks(symbol: str, interval: str, from_ts: int = None, to_ts: int = None, limit: int = 300, mode: str = "real"):
    """获取现货 K 线，返回 [{time, open, high, low, close, volume}, ...]
    Gate.io 格式: [t, 成交额(quote), c, h, l, o, 成交量(base), w]，成交量在索引 6

    公共 K 线优先主站实盘（HOST_REAL），并自动尝试备用实盘域名；仍失败时模拟模式下可回退 Testnet。
    注意：官方 API 规定 **limit 与 from/to 互斥**；from+to 跨度超过约 1000 根 K 时会 400，将自动分块拉取。
    """
    try:
        iv = _normalize_interval(interval)
        if from_ts is not None and to_ts is not None:
            fs, te = int(from_ts), int(to_ts)
            if fs >= te:
                return []
            bar_sec = _bar_seconds(iv)
            now_sec = int(time.time())
            min_allowed_from = now_sec - (_SPOT_MAX_LOOKBACK_BARS - _SPOT_LOOKBACK_SAFETY_BARS) * bar_sec
            if fs < min_allowed_from:
                fs = min_allowed_from
                if fs >= te:
                    return []
                from_ts = fs
            span = te - fs
            if span > _SPOT_MAX_BARS_PER_REQUEST * bar_sec:
                return list_candlesticks_range(symbol, iv, fs, te, mode=mode)
        candles = _list_candlesticks_spot_single(symbol, iv, from_ts, to_ts, limit if from_ts is None and to_ts is None else None, mode)
        result = []
        for c in candles or []:
            row = _parse_spot_candle_row(c)
            if row:
                result.append(row)
        return result
    except Exception:
        return []


def _futures_candlesticks_raw(
    api: FuturesApi,
    contract: str,
    interval: str,
    from_ts: int | None,
    to_ts: int | None,
    limit: int,
    settle: str,
) -> list:
    """合约 K 线单次逻辑（单 ApiClient host）。"""
    iv = _normalize_interval(interval)
    bar_sec = _bar_seconds(iv)
    now_sec = int(time.time())

    min_allowed_from = now_sec - _FUTURES_MAX_LOOKBACK_BARS * bar_sec
    fs = int(from_ts) if from_ts is not None else None
    te = int(to_ts) if to_ts is not None else None
    if te is not None and te > now_sec:
        te = now_sec
    if fs is not None:
        fs = max(fs, min_allowed_from)
    if fs is not None and te is not None and fs >= te:
        return []

    if fs is None and te is None:
        candles = api.list_futures_candlesticks(settle, contract, interval=iv, limit=limit)
    else:
        out: list[dict] = []
        seen: set[int] = set()
        cursor = fs if fs is not None else max(min_allowed_from, (te or now_sec) - _FUTURES_MAX_BARS_PER_REQUEST * bar_sec)
        end_ts = te if te is not None else now_sec
        max_chunk_sec = _FUTURES_MAX_BARS_PER_REQUEST * bar_sec
        stall = 0
        while cursor <= end_ts and stall < 8:
            chunk_end = min(cursor + max_chunk_sec, end_ts)
            if cursor >= chunk_end:
                break
            kwargs: dict = {"interval": iv, "_from": int(cursor), "to": int(chunk_end)}
            rows = api.list_futures_candlesticks(settle, contract, **kwargs)
            parsed: list[dict] = []
            for c in rows or []:
                row = _parse_spot_candle_row(c)
                if row:
                    parsed.append(row)
            if not parsed:
                stall += 1
                cursor = chunk_end + bar_sec
                continue
            stall = 0
            chunk_max_ts = max(candle_time_sec(r) for r in parsed)
            for row in parsed:
                ts = candle_time_sec(row)
                if fs is not None and ts < fs:
                    continue
                if te is not None and ts > te:
                    continue
                key = int(row.get("time") or ts)
                if key in seen:
                    continue
                seen.add(key)
                out.append(row)
            nxt = chunk_max_ts + bar_sec
            if nxt <= cursor:
                nxt = cursor + bar_sec
            cursor = nxt
            if chunk_end >= end_ts and chunk_max_ts >= end_ts - bar_sec:
                break
        out.sort(key=lambda x: int(x.get("time") or 0))
        candles = out
    result = []
    for c in candles or []:
        row = c if isinstance(c, dict) and {"time", "open", "high", "low", "close", "volume"}.issubset(set(c.keys())) else _parse_spot_candle_row(c)
        if row:
            result.append(row)
    return result


def list_futures_candlesticks(
    contract: str,
    interval: str,
    from_ts: int = None,
    to_ts: int = None,
    limit: int = 300,
    mode: str = "real",
    settle: str = "usdt",
):
    """获取合约 K 线（与现货相同字段结构，便于前端共用图表）
    limit 与 from/to 互斥；与现货一致优先实盘多域名，模拟模式可 Testnet 保底。"""
    try:
        last_err: Exception | None = None
        for host in _iter_kline_real_hosts():
            try:
                api = FuturesApi(ApiClient(Configuration(host=host)))
                return _futures_candlesticks_raw(api, contract, interval, from_ts, to_ts, limit, settle)
            except Exception as e:
                last_err = e
                logger.info("K线合约请求失败 host=%s: %s", host, e)
        if _kline_fallback_testnet_enabled() and mode == "simulated":
            logger.warning(
                "合约K线主站实盘均不可用，回退 Testnet 公共接口（价格与主站不一致，仅保底）: %s",
                last_err,
            )
            try:
                api = FuturesApi(ApiClient(Configuration(host=HOST_SIMULATED)))
                return _futures_candlesticks_raw(api, contract, interval, from_ts, to_ts, limit, settle)
            except Exception as e2:
                last_err = e2
        if last_err:
            logger.warning("K线合约拉取失败: %s", last_err)
        return []
    except Exception:
        return []
