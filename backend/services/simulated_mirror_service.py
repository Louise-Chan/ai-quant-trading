"""
模拟账户镜像：把一条回测记录（backtest_runs）映射为账户概览展示数据

用法：
  simulated_mirror_service.get_mirror_config(db, uid) → {"enabled", "backtest_run_id", "current_nav", "account_scope"}
  simulated_mirror_service.set_mirror(db, uid, run_id, current_nav, account_scope="spot")
  simulated_mirror_service.clear_mirror(db, uid)
  simulated_mirror_service.build_snapshot(db, uid, scope="spot") → 完整派生数据
  simulated_mirror_service.is_mirror_enabled(db, uid, mode, scope) → bool

核心派生逻辑：
  * initial_capital = current_nav / (1 + total_return)
  * NAV(t) = initial_capital * equity_curve(t) / equity_curve[-1]
            （等价于 current_nav * equity_curve(t) / equity_curve[-1]，两者恒等）
  * 交易流水：按 trade_events 配对 open/close，每一对按 open 时的 NAV 决定下单金额
  * Beta/Alpha：用组合 equity_curve 与 benchmark_curve 估计（日化后线性回归）
"""
from __future__ import annotations

import json
import math
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from models.backtest_run import BacktestRun
from services.preference_extra import get_extra_dict
from models.user_preference import UserPreference


# ————— 存储在 user_preferences.extra_json["simulated_mirror"] —————
_PREF_KEY = "simulated_mirror"


# ————— 进程内快照缓存 —————
# 回测记录本身不可变，快照派生只依赖 (run_id, current_nav, scope) + 该记录的 JSON。
# 因此命中缓存时完全跳过 JSON 解析、曲线重建、交易重组等重活。
# 配置变更（set_mirror / clear_mirror）时显式失效。
_SNAP_CACHE: "OrderedDict[tuple, dict]" = OrderedDict()
_SNAP_CACHE_MAX = 16
_SNAP_LOCK = threading.Lock()

# 针对"一次请求触发 6 次接口查询 is_mirror_enabled"的场景做的极短 TTL 配置缓存，
# 避免同一秒内重复打到 user_preferences 表。仅保留最近几位用户即可。
_CFG_CACHE: "OrderedDict[int, tuple[float, dict]]" = OrderedDict()
_CFG_CACHE_TTL = 1.5  # 秒
_CFG_CACHE_MAX = 32
_CFG_LOCK = threading.Lock()

# per-key 构建锁：防止同一把 cache_key 被多个并发请求同时重算大 JSON
_BUILD_LOCKS: dict[tuple, threading.Lock] = {}
_BUILD_LOCK_GUARD = threading.Lock()


def _build_lock_for(key: tuple) -> threading.Lock:
    with _BUILD_LOCK_GUARD:
        lk = _BUILD_LOCKS.get(key)
        if lk is None:
            lk = threading.Lock()
            _BUILD_LOCKS[key] = lk
        return lk


def _cache_key(user_id: int, run_id: int, current_nav: float, scope: str) -> tuple:
    # NAV 取 4 位避免浮点噪声影响命中
    return (int(user_id), int(run_id), round(float(current_nav), 4), str(scope))


def _cache_get(key: tuple) -> dict | None:
    with _SNAP_LOCK:
        snap = _SNAP_CACHE.get(key)
        if snap is not None:
            _SNAP_CACHE.move_to_end(key)
        return snap


def _cache_put(key: tuple, snap: dict) -> None:
    with _SNAP_LOCK:
        _SNAP_CACHE[key] = snap
        _SNAP_CACHE.move_to_end(key)
        while len(_SNAP_CACHE) > _SNAP_CACHE_MAX:
            _SNAP_CACHE.popitem(last=False)


def _cache_invalidate_user(user_id: int) -> None:
    with _SNAP_LOCK:
        victim = [k for k in _SNAP_CACHE.keys() if k and k[0] == int(user_id)]
        for k in victim:
            _SNAP_CACHE.pop(k, None)
    with _BUILD_LOCK_GUARD:
        for k in [k for k in _BUILD_LOCKS.keys() if k and k[0] == int(user_id)]:
            _BUILD_LOCKS.pop(k, None)
    with _CFG_LOCK:
        _CFG_CACHE.pop(int(user_id), None)


def _cfg_get_cached(user_id: int) -> dict | None:
    now = time.monotonic()
    with _CFG_LOCK:
        hit = _CFG_CACHE.get(int(user_id))
        if hit and (now - hit[0]) < _CFG_CACHE_TTL:
            _CFG_CACHE.move_to_end(int(user_id))
            return hit[1]
    return None


def _cfg_put_cached(user_id: int, cfg: dict) -> None:
    with _CFG_LOCK:
        _CFG_CACHE[int(user_id)] = (time.monotonic(), cfg)
        _CFG_CACHE.move_to_end(int(user_id))
        while len(_CFG_CACHE) > _CFG_CACHE_MAX:
            _CFG_CACHE.popitem(last=False)


def get_mirror_config(db: Session, user_id: int) -> dict:
    cached = _cfg_get_cached(user_id)
    if cached is not None:
        return cached
    d = get_extra_dict(db, user_id).get(_PREF_KEY) or {}
    if not isinstance(d, dict):
        out = {"enabled": False, "backtest_run_id": None, "current_nav": None, "account_scope": "spot"}
    else:
        out = {
            "enabled": bool(d.get("enabled", False)),
            "backtest_run_id": int(d.get("backtest_run_id") or 0) or None,
            "current_nav": float(d.get("current_nav")) if d.get("current_nav") not in (None, "") else None,
            "account_scope": str(d.get("account_scope") or "spot").lower(),
        }
    _cfg_put_cached(user_id, out)
    return out


def _write_mirror(db: Session, user_id: int, cfg: dict | None) -> None:
    pref = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
    extras = get_extra_dict(db, user_id)
    if cfg is None:
        extras.pop(_PREF_KEY, None)
    else:
        extras[_PREF_KEY] = cfg
    raw = json.dumps(extras, ensure_ascii=False) if extras else None
    if pref:
        pref.extra_json = raw
    else:
        pref = UserPreference(user_id=user_id, current_mode="simulated", extra_json=raw)
        db.add(pref)
    db.commit()


def set_mirror(
    db: Session,
    user_id: int,
    backtest_run_id: int,
    current_nav: float,
    account_scope: str = "spot",
) -> dict:
    scope = "futures" if str(account_scope).lower() == "futures" else "spot"
    cfg = {
        "enabled": True,
        "backtest_run_id": int(backtest_run_id),
        "current_nav": float(current_nav),
        "account_scope": scope,
    }
    _write_mirror(db, user_id, cfg)
    _cache_invalidate_user(user_id)
    return cfg


def clear_mirror(db: Session, user_id: int) -> None:
    _write_mirror(db, user_id, None)
    _cache_invalidate_user(user_id)


def is_mirror_enabled(db: Session, user_id: int, mode: str | None, account_scope: str | None) -> bool:
    """
    启用后，无论当前交易模式如何，账户概览/资产/交易接口都会走镜像派生数据。
    这是用户显式开启的"展示覆盖"，并不影响任何真实下单、真实 API 调用。
    account_scope 仍需匹配：只有配置里的 scope（spot/futures）会被覆盖，另一个保持真实。
    mode 参数保留用于未来可能的细化路由，此处不再作为开关。
    """
    _ = mode  # 保留以免破坏调用处
    cfg = get_mirror_config(db, user_id)
    if not cfg.get("enabled") or not cfg.get("backtest_run_id") or not cfg.get("current_nav"):
        return False
    want = "futures" if str(account_scope or "spot").lower() == "futures" else "spot"
    return cfg.get("account_scope") == want


def _load_run(db: Session, user_id: int, run_id: int) -> BacktestRun | None:
    if not run_id:
        return None
    return (
        db.query(BacktestRun)
        .filter(BacktestRun.id == int(run_id), BacktestRun.user_id == user_id)
        .first()
    )


def _safe_json_loads(s: str | None) -> Any:
    if not s:
        return None
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return None


def _interval_to_seconds(interval: str | None) -> int:
    s = str(interval or "").strip().lower()
    if not s:
        return 3600
    table = {
        "1m": 60, "3m": 180, "5m": 300, "10m": 600, "15m": 900, "30m": 1800,
        "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "8h": 28800, "12h": 43200,
        "1d": 86400, "3d": 259200, "7d": 604800, "1w": 604800,
    }
    if s in table:
        return table[s]
    try:
        if s.endswith("m"):
            return max(60, int(float(s[:-1])) * 60)
        if s.endswith("h"):
            return max(60, int(float(s[:-1])) * 3600)
        if s.endswith("d"):
            return max(60, int(float(s[:-1])) * 86400)
        return int(float(s))
    except (TypeError, ValueError):
        return 3600


def _equity_points(curve: list[dict]) -> list[tuple[int, float]]:
    out: list[tuple[int, float]] = []
    if not isinstance(curve, list):
        return out
    for r in curve:
        if not isinstance(r, dict):
            continue
        try:
            i = int(r.get("i"))
            v = float(r.get("v"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(v):
            out.append((i, v))
    out.sort(key=lambda x: x[0])
    return out


def _beta_alpha_from_curves(
    port_curve: list[tuple[int, float]],
    bench_curve: list[tuple[int, float]],
    total_return: float | None,
    benchmark_total_return: float | None,
) -> tuple[float | None, float | None]:
    """从等长对齐的组合/基准权益曲线估计 Beta 与 Alpha(年化对齐粒度=整段)"""
    if len(port_curve) < 5 or len(bench_curve) < 5:
        return None, None
    # 按 i 对齐（两者都是同一份 downsample，通常 i 完全一致）
    pb = {i: v for i, v in bench_curve}
    port_r: list[float] = []
    bench_r: list[float] = []
    prev_p: float | None = None
    prev_b: float | None = None
    for i, vp in port_curve:
        vb = pb.get(i)
        if vb is None:
            continue
        if prev_p is not None and prev_b is not None and prev_p > 0 and prev_b > 0:
            rp = (vp - prev_p) / prev_p
            rb = (vb - prev_b) / prev_b
            if math.isfinite(rp) and math.isfinite(rb):
                port_r.append(rp)
                bench_r.append(rb)
        prev_p, prev_b = vp, vb
    n = len(port_r)
    if n < 5:
        return None, None
    mean_p = sum(port_r) / n
    mean_b = sum(bench_r) / n
    var_b = sum((x - mean_b) ** 2 for x in bench_r) / max(1, n - 1)
    cov_pb = sum((port_r[k] - mean_p) * (bench_r[k] - mean_b) for k in range(n)) / max(1, n - 1)
    if var_b <= 1e-18:
        beta = None
    else:
        beta = cov_pb / var_b
    # Alpha 用累积口径对齐 backtest 的 alpha_vs_buyhold：
    # α = total_return - β * benchmark_total_return（若有 β），否则退化为差值
    if total_return is None or benchmark_total_return is None:
        alpha = None
    elif beta is None:
        alpha = float(total_return) - float(benchmark_total_return)
    else:
        alpha = float(total_return) - float(beta) * float(benchmark_total_return)
    return (round(float(beta), 4) if beta is not None else None,
            round(float(alpha), 4) if alpha is not None else None)


def _derive_nav_curve(
    port_curve: list[tuple[int, float]],
    start_ts: int | None,
    end_ts: int | None,
    total_bars: int | None,
    interval_sec: int,
    current_nav: float,
) -> list[dict]:
    if not port_curve:
        return []
    v_last = float(port_curve[-1][1]) or 1.0
    # 推断每点的时间：优先使用 start_ts + i * bar_sec；缺失则反推
    if start_ts and total_bars and total_bars > 1:
        bar_sec = max(1, (int(end_ts) - int(start_ts)) // max(1, (int(total_bars) - 1))) if end_ts else interval_sec
    else:
        bar_sec = interval_sec
    base_ts = int(start_ts) if start_ts else 0
    out: list[dict] = []
    for i, v in port_curve:
        nav = float(current_nav) * float(v) / v_last
        ts = base_ts + int(i) * int(bar_sec) if base_ts else int(i) * int(bar_sec)
        out.append({"t": int(ts), "nav": round(float(nav), 4)})
    return out


def _symbol_trade_events(result: dict, prefer_symbol: str | None) -> tuple[str, list[dict]]:
    """挑选一个标的的 trade_events（优先 prefer_symbol，否则第一个 ok 标的）"""
    per_sym = result.get("per_symbol") if isinstance(result, dict) else None
    if not isinstance(per_sym, list):
        return "", []
    target: dict | None = None
    if prefer_symbol:
        prefer_u = str(prefer_symbol).strip().upper()
        for r in per_sym:
            if r.get("ok") and str(r.get("symbol") or "").upper() == prefer_u:
                target = r
                break
    if target is None:
        for r in per_sym:
            if r.get("ok") and isinstance(r.get("trade_events"), list) and r["trade_events"]:
                target = r
                break
    if not target:
        return "", []
    sym = str(target.get("symbol") or "").upper()
    evs = [e for e in (target.get("trade_events") or []) if isinstance(e, dict)]
    return sym, evs


def _build_trades_and_orders(
    symbol: str,
    events: list[dict],
    nav_curve: list[dict],
    initial_capital: float,
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    将 open/close 事件配对为 Buy/Sell 现货交易；金额按开仓时 NAV 分配。
    返回 (trades[], orders[], positions[])
    """
    trades: list[dict] = []
    orders: list[dict] = []

    def _nav_at(ts: int) -> float:
        if not nav_curve:
            return float(initial_capital)
        # 找 ts 所在区间的 NAV（前一点）
        prev_nav = nav_curve[0]["nav"]
        for p in nav_curve:
            if int(p["t"]) > int(ts):
                break
            prev_nav = p["nav"]
        return float(prev_nav)

    pending_open: dict | None = None
    trade_seq = 0
    for ev in events:
        kind = str(ev.get("kind") or "").lower()
        try:
            ts = int(ev.get("time") or 0)
            px = float(ev.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if ts <= 0 or px <= 0:
            continue
        if kind == "open":
            nav_at_open = _nav_at(ts)
            amount_base = round(nav_at_open / px, 8) if px > 0 else 0.0
            if amount_base <= 0:
                continue
            pending_open = {
                "time": ts,
                "price": px,
                "amount": amount_base,
                "nav_at_open": nav_at_open,
            }
            trade_seq += 1
            tid = f"mirror-{trade_seq}-b"
            trades.append({
                "id": tid,
                "trade_id": tid,
                "symbol": symbol,
                "side": "buy",
                "price": f"{px:.8f}".rstrip("0").rstrip(".") or "0",
                "amount": f"{amount_base:.8f}".rstrip("0").rstrip(".") or "0",
                "filled_amount": f"{amount_base:.8f}".rstrip("0").rstrip(".") or "0",
                "quote_amount": f"{nav_at_open:.4f}",
                "fee": "0",
                "status": "finished",
                "role": "taker",
                "source": "simulated_mirror",
                "create_time": _fmt_utc(ts),
                "create_time_ms": ts * 1000,
                "note": "回测镜像·开仓",
            })
            orders.append({
                "id": tid,
                "symbol": symbol,
                "side": "buy",
                "type": "market",
                "amount": f"{amount_base:.8f}".rstrip("0").rstrip(".") or "0",
                "filled_amount": f"{amount_base:.8f}".rstrip("0").rstrip(".") or "0",
                "price": f"{px:.8f}".rstrip("0").rstrip(".") or "0",
                "status": "closed",
                "status_text": "已成交",
                "create_time": _fmt_utc(ts),
                "source": "simulated_mirror",
            })
        elif kind == "close" and pending_open:
            amount_base = float(pending_open["amount"])
            if amount_base <= 0:
                pending_open = None
                continue
            quote_out = amount_base * px
            pnl = quote_out - float(pending_open["nav_at_open"])
            trade_seq += 1
            tid = f"mirror-{trade_seq}-s"
            trades.append({
                "id": tid,
                "trade_id": tid,
                "symbol": symbol,
                "side": "sell",
                "price": f"{px:.8f}".rstrip("0").rstrip(".") or "0",
                "amount": f"{amount_base:.8f}".rstrip("0").rstrip(".") or "0",
                "filled_amount": f"{amount_base:.8f}".rstrip("0").rstrip(".") or "0",
                "quote_amount": f"{quote_out:.4f}",
                "fee": "0",
                "status": "finished",
                "role": "taker",
                "source": "simulated_mirror",
                "create_time": _fmt_utc(ts),
                "create_time_ms": ts * 1000,
                "pnl_usdt": round(pnl, 4),
                "note": "回测镜像·平仓",
            })
            orders.append({
                "id": tid,
                "symbol": symbol,
                "side": "sell",
                "type": "market",
                "amount": f"{amount_base:.8f}".rstrip("0").rstrip(".") or "0",
                "filled_amount": f"{amount_base:.8f}".rstrip("0").rstrip(".") or "0",
                "price": f"{px:.8f}".rstrip("0").rstrip(".") or "0",
                "status": "closed",
                "status_text": "已成交",
                "create_time": _fmt_utc(ts),
                "source": "simulated_mirror",
                "pnl_usdt": round(pnl, 4),
            })
            pending_open = None
        elif kind == "close" and pending_open is None:
            # 无挂起开仓的 close（异常），跳过
            continue

    positions: list[dict] = []
    if pending_open:
        # 仍持仓未平：展示为一笔"未平仓"持仓（基础币）
        positions.append({
            "symbol": symbol,
            "amount": pending_open["amount"],
            "avg_price": pending_open["price"],
            "value_usdt": round(pending_open["amount"] * pending_open["price"], 4),
            "source": "simulated_mirror",
        })

    # 最近的交易放前面，匹配前端常规展示
    orders.sort(key=lambda o: o.get("create_time_ms") or 0, reverse=True)
    trades.sort(key=lambda o: o.get("create_time_ms") or 0, reverse=True)
    return trades, orders, positions


def _fmt_utc(ts: int) -> str:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return ""


def build_snapshot(db: Session, user_id: int, account_scope: str = "spot") -> dict | None:
    """
    构造完整镜像快照。未配置或记录缺失时返回 None。
    结果会按 (user_id, run_id, current_nav, scope) 缓存在进程内存；
    由于 BacktestRun 记录不可变，缓存命中时直接 O(1) 返回。
    set_mirror / clear_mirror 会主动清缓存。
    """
    cfg = get_mirror_config(db, user_id)
    if not cfg.get("enabled") or not cfg.get("backtest_run_id") or not cfg.get("current_nav"):
        return None
    scope = "futures" if str(account_scope).lower() == "futures" else "spot"
    if cfg.get("account_scope") != scope:
        return None

    cache_key = _cache_key(user_id, int(cfg["backtest_run_id"]), float(cfg["current_nav"]), scope)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # 防惊群：同一 key 只允许一个线程真正构建，其余等它完成后直接读缓存
    build_lock = _build_lock_for(cache_key)
    with build_lock:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
        return _build_snapshot_locked(db, user_id, cfg, scope, cache_key)


def _build_snapshot_locked(
    db: Session,
    user_id: int,
    cfg: dict,
    scope: str,
    cache_key: tuple,
) -> dict | None:
    run = _load_run(db, user_id, int(cfg["backtest_run_id"]))
    if not run:
        return None
    result = _safe_json_loads(run.result_json) or {}
    summary = _safe_json_loads(run.summary_json) or {}
    range_meta = _safe_json_loads(run.range_json) or {}
    symbols = _safe_json_loads(run.symbols_json) or []

    portfolio = result.get("portfolio") or {}
    if not portfolio.get("ok"):
        return None

    # 指标：优先取 portfolio 内的数值，缺失时回退 summary
    total_return = portfolio.get("total_return")
    benchmark_total_return = portfolio.get("benchmark_total_return")
    alpha_vs_buyhold = portfolio.get("alpha_vs_buyhold")
    sharpe = portfolio.get("sharpe_approx")
    max_dd = portfolio.get("max_drawdown")
    total_return = total_return if total_return is not None else summary.get("total_return")
    benchmark_total_return = benchmark_total_return if benchmark_total_return is not None else summary.get("benchmark_total_return")
    alpha_vs_buyhold = alpha_vs_buyhold if alpha_vs_buyhold is not None else summary.get("alpha_vs_buyhold")
    sharpe = sharpe if sharpe is not None else summary.get("sharpe_approx")
    max_dd = max_dd if max_dd is not None else summary.get("max_drawdown")

    try:
        total_return_f = float(total_return) if total_return is not None else 0.0
    except (TypeError, ValueError):
        total_return_f = 0.0

    current_nav = float(cfg["current_nav"])
    initial_capital = current_nav / (1.0 + total_return_f) if (1.0 + total_return_f) > 1e-12 else current_nav

    # 区间 & 年化
    start_ts = range_meta.get("from_ts")
    end_ts = range_meta.get("to_ts")
    try:
        start_ts = int(start_ts) if start_ts not in (None, "") else None
    except (TypeError, ValueError):
        start_ts = None
    try:
        end_ts = int(end_ts) if end_ts not in (None, "") else None
    except (TypeError, ValueError):
        end_ts = None
    annual_return: float | None = None
    if start_ts and end_ts and end_ts > start_ts and total_return is not None:
        days = (int(end_ts) - int(start_ts)) / 86400.0
        if days > 0:
            try:
                annual_return = (1.0 + float(total_return)) ** (365.0 / days) - 1.0
                annual_return = round(float(annual_return), 4)
            except (ValueError, OverflowError):
                annual_return = None

    # 权益曲线 & Beta/Alpha
    eq_curve_raw = _equity_points(portfolio.get("equity_curve") or [])
    bench_curve_raw = _equity_points(portfolio.get("benchmark_curve") or [])
    beta, alpha_ret = _beta_alpha_from_curves(
        eq_curve_raw, bench_curve_raw, total_return, benchmark_total_return
    )
    # 使用用户要求口径：Alpha = alpha_vs_buyhold（回测页所示）
    if alpha_vs_buyhold is not None:
        try:
            alpha_ret = round(float(alpha_vs_buyhold), 4)
        except (TypeError, ValueError):
            pass

    interval_sec = _interval_to_seconds(run.interval)
    total_bars = int(portfolio.get("bars") or 0) or None
    nav_history = _derive_nav_curve(eq_curve_raw, start_ts, end_ts, total_bars, interval_sec, current_nav)

    prefer_symbol = None
    if symbols and isinstance(symbols, list) and symbols:
        prefer_symbol = str(symbols[0])
    sym, events = _symbol_trade_events(result, prefer_symbol)
    trades, orders, positions = _build_trades_and_orders(sym or (prefer_symbol or ""), events, nav_history, initial_capital)

    summary_block = {
        "initial_capital": round(float(initial_capital), 4),
        "current_nav": round(float(current_nav), 4),
        "total_return": round(float(total_return), 4) if total_return is not None else None,
        "annual_return": annual_return,
        "max_drawdown": round(float(max_dd), 4) if max_dd is not None else None,
        "sharpe": round(float(sharpe), 4) if sharpe is not None else None,
        "beta": beta,
        "alpha": alpha_ret,
        "benchmark_total_return": round(float(benchmark_total_return), 4) if benchmark_total_return is not None else None,
        "data_source": "simulated_mirror",
        "account_scope": scope,
    }

    run_meta = {
        "id": int(run.id),
        "name": run.name or "",
        "interval": run.interval or "",
        "symbols": list(symbols) if isinstance(symbols, list) else [],
        "factors": _safe_json_loads(run.factors_json) or [],
        "range": range_meta,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }

    snapshot = {
        "active": True,
        "config": cfg,
        "run": run_meta,
        "summary": summary_block,
        "nav_history": nav_history,
        "trades": trades,
        "orders": orders,
        "positions": positions,
    }
    _cache_put(cache_key, snapshot)
    return snapshot
