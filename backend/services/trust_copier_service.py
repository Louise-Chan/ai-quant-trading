"""托管跟单：按用户订阅的 UserStrategy 配置拉 K 线、跑 analyze_symbol，不经审核直接下单"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from core.database import SessionLocal
from models.custody_trade_log import CustodyTradeLog
from models.dynamic_factor import DynamicFactor
from models.subscription import Subscription
from models.user_preference import UserPreference
from models.user_strategy import UserStrategy
from services.broker_service import get_broker, get_mode
from services.gate_account_service import adjust_spot_amount_min_quote_usdt, create_spot_order, get_total_balance_usdt
from services.preference_extra import get_extra_dict, get_dashboard_trading
from services.risk_settings_memory import risk_settings_for_user
from services.strategy_engine.runner import analyze_symbol
from utils.gate_client import list_candlesticks
from gate_api.exceptions import ApiException, GateApiException

_DYN_RE = re.compile(r"^dyn_(\d+)$", re.IGNORECASE)
_LAST_ORDER_TS: dict[tuple[int, str], float] = {}
_MIN_COOLDOWN_S = 60.0


def _parse_config(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _parse_weights(raw: str | None) -> dict[str, float]:
    if not raw:
        return {}
    try:
        d = json.loads(raw)
        out: dict[str, float] = {}
        for k, v in d.items():
            try:
                out[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
        return out
    except Exception:
        return {}


def _symbols_from_config(cfg: dict[str, Any]) -> list[str]:
    syms = cfg.get("symbols")
    if isinstance(syms, list):
        return [str(x).strip().upper() for x in syms if str(x).strip()]
    if isinstance(syms, str) and syms.strip():
        return [x.strip().upper() for x in syms.split(",") if x.strip()]
    return []


def _dynamic_expressions_for_user(db: Session, uid: int, active: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for fid in active:
        m = _DYN_RE.match(str(fid).strip())
        if not m:
            continue
        did = int(m.group(1))
        row = (
            db.query(DynamicFactor)
            .filter(DynamicFactor.id == did, DynamicFactor.user_id == uid, DynamicFactor.active == True)  # noqa: E712
            .first()
        )
        if row and row.expression_dsl:
            out[row.factor_key()] = row.expression_dsl
    return out


def _iter_custody_user_ids(db: Session) -> list[int]:
    """从 user_preferences.extra_json 读取 dashboard.custody_running"""
    out: list[int] = []
    for p in db.query(UserPreference).all():
        d = get_extra_dict(db, p.user_id)
        dash = d.get("dashboard") or {}
        if dash.get("custody_running"):
            out.append(p.user_id)
    return out


def _custody_tick_user(db: Session, uid: int) -> None:
    d = get_extra_dict(db, uid)
    dash = d.get("dashboard") or {}
    if not dash.get("custody_running"):
        return
    sid = dash.get("active_subscription_id")
    try:
        sid = int(sid) if sid is not None else None
    except (TypeError, ValueError):
        sid = None
    if not sid:
        return

    sub = db.query(Subscription).filter(Subscription.id == sid, Subscription.user_id == uid).first()
    if not sub or sub.status != "active" or not sub.user_strategy_id:
        return

    us = db.query(UserStrategy).filter(UserStrategy.id == sub.user_strategy_id, UserStrategy.user_id == uid).first()
    if not us or us.status != "active":
        return

    dash_prefs = get_dashboard_trading(db, uid)
    cap_g = int(dash_prefs.get("custody_max_opens_per_day") or 0)
    if cap_g > 0:
        start_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        n_today = (
            db.query(CustodyTradeLog)
            .filter(
                CustodyTradeLog.user_id == uid,
                CustodyTradeLog.status == "executed",
                CustodyTradeLog.created_at >= start_day,
            )
            .count()
        )
        if n_today >= cap_g:
            return

    cfg = _parse_config(us.config_json)
    weights = _parse_weights(us.weights_json)
    symbols = _symbols_from_config(cfg)
    if not symbols:
        return

    interval = str(cfg.get("interval") or "1h").strip() or "1h"
    max_raw = cfg.get("max_opens_per_day")
    try:
        max_opens = int(max_raw) if max_raw is not None else 0
    except (TypeError, ValueError):
        max_opens = 0
    max_opens = max_opens if max_opens > 0 else None
    avg_mode = str(cfg.get("avg_daily_mode") or "trading").strip().lower()
    if avg_mode not in ("natural", "trading"):
        avg_mode = "trading"

    af = cfg.get("active_factors")
    if isinstance(af, list):
        active_factors = [str(x).strip() for x in af if str(x).strip()]
    elif isinstance(af, str) and af.strip():
        active_factors = [x.strip() for x in af.split(",") if x.strip()]
    else:
        active_factors = None

    dyn_expr = _dynamic_expressions_for_user(db, uid, active_factors or [])

    m = get_mode(db, uid)
    if sub.mode != m:
        return
    broker = get_broker(db, uid, m)
    if not broker:
        return

    total_usdt = None
    try:
        _, _, total_usdt = get_total_balance_usdt(m, broker.api_key_enc, broker.api_secret_enc)
    except Exception:
        pass
    risk = risk_settings_for_user(uid, m)

    # 轮询：每次只处理一个标的，降低 API 压力
    idx = int((time.time() / 30)) % len(symbols)
    symbol = symbols[idx]

    key = (uid, symbol)
    now = time.time()
    if now - _LAST_ORDER_TS.get(key, 0) < _MIN_COOLDOWN_S:
        return

    candles = list_candlesticks(symbol, interval, limit=320, mode=m)
    pkg = analyze_symbol(
        symbol,
        candles,
        risk,
        interval=interval,
        total_usdt=total_usdt,
        active_factors=active_factors,
        weights_override=weights if weights else None,
        max_opens_per_day=max_opens,
        avg_daily_mode=avg_mode,
        dynamic_factor_expressions=dyn_expr if dyn_expr else None,
    )
    if not pkg.get("ok"):
        log = CustodyTradeLog(
            user_id=uid,
            mode=m,
            user_strategy_id=us.id,
            symbol=symbol,
            status="skipped",
            message=(pkg.get("error") or "引擎失败")[:2000],
            details_json=json.dumps({"engine": pkg}, ensure_ascii=False)[:8000],
        )
        db.add(log)
        db.commit()
        return

    sug = pkg.get("suggested_order") or {}
    side = str(sug.get("side") or "").lower()
    ord_type = str(sug.get("order_type") or "limit").lower()
    price = sug.get("price")
    amount = sug.get("amount")
    sig_dir = str(pkg.get("signal_direction") or "").lower()

    if side not in ("buy", "sell") or sig_dir == "hold":
        return

    p = str(price).strip() if price is not None else None
    if ord_type == "market":
        p = None if not p else p
    amt_raw = str(amount).strip() if amount is not None else ""
    if not amt_raw:
        return

    try:
        amt_exec, adj_note = adjust_spot_amount_min_quote_usdt(
            m,
            broker.api_key_enc,
            broker.api_secret_enc,
            symbol,
            amt_raw,
            ord_type,
            p,
            side,
        )
    except ValueError as ve:
        log = CustodyTradeLog(
            user_id=uid,
            mode=m,
            user_strategy_id=us.id,
            symbol=symbol,
            status="failed",
            message=str(ve)[:2000],
            details_json=None,
        )
        db.add(log)
        db.commit()
        return

    try:
        oid, raw = create_spot_order(
            m,
            broker.api_key_enc,
            broker.api_secret_enc,
            symbol,
            side,
            ord_type,
            amt_exec,
            p,
        )
        _LAST_ORDER_TS[key] = time.time()
        log = CustodyTradeLog(
            user_id=uid,
            mode=m,
            user_strategy_id=us.id,
            symbol=symbol,
            signal_side=sig_dir,
            order_type=ord_type,
            price=p,
            amount=amt_exec,
            status="executed",
            message=adj_note or "ok",
            details_json=json.dumps({"gate": raw}, ensure_ascii=False)[:8000] if raw else None,
            exchange_order_id=str(oid) if oid is not None else None,
        )
        db.add(log)
        db.commit()
    except (ApiException, GateApiException) as e:
        log = CustodyTradeLog(
            user_id=uid,
            mode=m,
            user_strategy_id=us.id,
            symbol=symbol,
            status="failed",
            message=str(e)[:2000],
            details_json=None,
        )
        db.add(log)
        db.commit()
    except Exception as e:
        log = CustodyTradeLog(
            user_id=uid,
            mode=m,
            user_strategy_id=us.id,
            symbol=symbol,
            status="failed",
            message=str(e)[:2000],
            details_json=None,
        )
        db.add(log)
        db.commit()


def _loop(interval_s: float) -> None:
    while True:
        try:
            db = SessionLocal()
            try:
                uids = _iter_custody_user_ids(db)
                for uid in uids:
                    try:
                        _custody_tick_user(db, uid)
                    except Exception as e:
                        print(f"[custody] uid={uid} tick {e}")
            finally:
                db.close()
        except Exception as e:
            print(f"[custody] loop {e}")
        time.sleep(interval_s)


def start_trust_copier_worker(interval_s: float = 25.0) -> None:
    t = threading.Thread(target=_loop, args=(interval_s,), daemon=True, name="trust_copier")
    t.start()
