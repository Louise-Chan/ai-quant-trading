"""仪表盘 API - 选币、自选、行情、自选与模拟账户绑定"""
from fastapi import APIRouter, Query, Header, Depends, Body
from pydantic import BaseModel
from sqlalchemy.orm import Session
from core.database import get_db
from core.security import decode_token
from models.watchlist import Watchlist
from utils.gate_client import list_currency_pairs, list_tickers, list_futures_tickers
from services.broker_service import get_broker, get_mode
from services.rule_engine import apply_rules, get_default_rules
from services.gate_account_service import get_positions_with_value, get_spot_accounts
from services.preference_extra import get_deepseek_api_key, get_dashboard_trading, patch_dashboard_trading
from services.deepseek_coin_agent import run_agent_coin_pick, build_candidate_lines
from models.subscription import Subscription
from models.user_strategy import UserStrategy
from services.strategy_definitions import get_strategy

router = APIRouter()


def _ticker_attr(t, key: str, default=None):
    if t is None:
        return default
    if isinstance(t, dict):
        return t.get(key, default)
    return getattr(t, key, default)


def get_current_user_id(authorization: str = Header(None)) -> int | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    payload = decode_token(authorization[7:])
    return int(payload["sub"]) if payload and payload.get("sub") else None


@router.get("/coins")
def get_coins(keyword: str = Query(""), page: int = Query(1), size: int = Query(50)):
    try:
        pairs = list_currency_pairs("real")
        if isinstance(pairs, list) and pairs and keyword:
            pairs = [p for p in pairs if keyword.upper() in (p.get("symbol") or "").upper()]
        start = (page - 1) * size
        total = len(pairs) if isinstance(pairs, list) else 0
        lst = pairs[start:start + size] if isinstance(pairs, list) else []
        return {"success": True, "data": {"list": lst, "total": total}, "message": "ok", "code": 200}
    except Exception as e:
        return {"success": False, "data": {"list": [], "total": 0}, "message": str(e), "code": 500}


def _normalize_quote_market(raw: str | None) -> str:
    s = (raw or "spot").strip().lower()
    if s in ("futures", "futures_usdt", "contract", "合约"):
        return "futures"
    return "spot"


@router.get("/watchlist")
def get_watchlist(authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": {"symbols": [], "items": []}, "message": "请先登录", "code": 401}
    rows = db.query(Watchlist).filter(Watchlist.user_id == uid).order_by(Watchlist.id.asc()).all()
    items = [{"symbol": w.symbol, "quote_market": w.quote_market or "spot"} for w in rows]
    symbols = [w.symbol for w in rows]
    return {"success": True, "data": {"symbols": symbols, "items": items}, "message": "ok", "code": 200}


@router.post("/watchlist")
def add_watchlist(
    symbol: str,
    quote_market: str = Query("spot", description="spot 或 futures"),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    qm = _normalize_quote_market(quote_market)
    if db.query(Watchlist).filter(Watchlist.user_id == uid, Watchlist.symbol == symbol, Watchlist.quote_market == qm).first():
        return {"success": True, "data": None, "message": "已在自选", "code": 200}
    w = Watchlist(user_id=uid, symbol=symbol, quote_market=qm)
    db.add(w)
    db.commit()
    return {"success": True, "data": None, "message": "添加成功", "code": 200}


@router.delete("/watchlist/{symbol}")
def remove_watchlist(
    symbol: str,
    quote_market: str = Query("spot"),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    qm = _normalize_quote_market(quote_market)
    db.query(Watchlist).filter(Watchlist.user_id == uid, Watchlist.symbol == symbol, Watchlist.quote_market == qm).delete()
    db.commit()
    return {"success": True, "data": None, "message": "移除成功", "code": 200}


@router.get("/tickers")
def get_tickers(symbols: str = Query(""), mode: str = Query("real"), market: str = Query("spot")):
    """行情快照。market=spot 现货；market=futures 合约 U 本位。mode=real/simulated 对应 Gate host"""
    try:
        ticker_map = {}
        if market in ("futures", "futures_usdt", "contract"):
            tickers = list_futures_tickers(mode, "usdt")
            if tickers:
                for t in tickers:
                    contract = _ticker_attr(t, "contract") or ""
                    if not contract:
                        continue
                    last = _ticker_attr(t, "last", "0")
                    chg = _ticker_attr(t, "change_percentage", "0")
                    ticker_map[contract] = {"last": last, "change_pct": chg}
        else:
            tickers = list_tickers(mode)
            if tickers:
                for t in tickers:
                    cp = _ticker_attr(t, "currency_pair") or ""
                    if not cp:
                        continue
                    last = _ticker_attr(t, "last", "0")
                    chg = _ticker_attr(t, "change_percentage", "0")
                    ticker_map[cp] = {"last": last, "change_pct": chg}
        if symbols:
            wanted = [s.strip() for s in symbols.split(",") if s.strip()]
            ticker_map = {k: v for k, v in ticker_map.items() if k in wanted}
        return {"success": True, "data": ticker_map, "message": "ok", "code": 200}
    except Exception as e:
        return {"success": False, "data": {}, "message": str(e), "code": 500}


@router.get("/market-quotes")
def get_market_quotes(
    market: str = Query("spot", description="spot 或 futures"),
    keyword: str = Query(""),
    mode: str = Query("real"),
    limit: int = Query(800, le=3000),
):
    """
    行情列表（现货 / 合约），用于仪表盘左侧行情表。
    按 24h 成交额降序，支持关键词过滤交易对/合约名。
    """
    try:
        kw = (keyword or "").strip().upper()
        rows: list[dict] = []

        def _float(v, default=0.0):
            try:
                return float(v) if v is not None else default
            except (TypeError, ValueError):
                return default

        if market in ("futures", "futures_usdt", "contract"):
            tickers = list_futures_tickers(mode, "usdt") or []
            for t in tickers:
                sym = _ticker_attr(t, "contract") or ""
                if not sym or (kw and kw not in sym.upper()):
                    continue
                last = _ticker_attr(t, "last", "0")
                chg = _ticker_attr(t, "change_percentage", "0")
                vol = _ticker_attr(t, "volume_24h_quote")
                if vol is None:
                    vol = _ticker_attr(t, "volume_24h_settle")
                if vol is None:
                    vol = _ticker_attr(t, "volume_24h")
                rows.append(
                    {
                        "symbol": sym,
                        "last": str(last) if last is not None else "0",
                        "change_pct": str(chg) if chg is not None else "0",
                        "quote_volume": _float(vol, 0),
                    }
                )
        else:
            tickers = list_tickers(mode) or []
            for t in tickers:
                sym = _ticker_attr(t, "currency_pair") or ""
                if not sym or "_USDT" not in sym.upper():
                    continue
                if kw and kw not in sym.upper():
                    continue
                last = _ticker_attr(t, "last", "0")
                chg = _ticker_attr(t, "change_percentage", "0")
                qv = _ticker_attr(t, "quote_volume")
                if qv is None:
                    qv = _ticker_attr(t, "base_volume")
                rows.append(
                    {
                        "symbol": sym,
                        "last": str(last) if last is not None else "0",
                        "change_pct": str(chg) if chg is not None else "0",
                        "quote_volume": _float(qv, 0),
                    }
                )

        rows.sort(key=lambda x: (x.get("quote_volume") or 0, x.get("symbol") or ""), reverse=True)
        return {"success": True, "data": {"market": market, "list": rows[:limit]}, "message": "ok", "code": 200}
    except Exception as e:
        return {"success": False, "data": {"market": market, "list": []}, "message": str(e), "code": 500}


@router.get("/watchlist-with-positions")
def get_watchlist_with_positions(authorization: str = Header(None), db: Session = Depends(get_db)):
    """
    自选币 + 模拟/实盘账户持仓绑定。
    返回：symbols、items（含 quote_market），positions 现货持仓，tickers 行情（按标的+市场）
    """
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    rows = db.query(Watchlist).filter(Watchlist.user_id == uid).order_by(Watchlist.id.asc()).all()
    items = [{"symbol": w.symbol, "quote_market": w.quote_market or "spot"} for w in rows]
    symbols = [w.symbol for w in rows]
    m = get_mode(db, uid)
    broker = get_broker(db, uid, m)
    positions = []
    balance_total = 0.0
    ticker_map_spot: dict = {}
    ticker_map_fut: dict = {}
    if broker:
        try:
            positions = get_positions_with_value(m, broker.api_key_enc, broker.api_secret_enc)
            accounts = get_spot_accounts(m, broker.api_key_enc, broker.api_secret_enc)
            usdt_acc = next((a for a in accounts if a["currency"] == "USDT"), None)
            balance_total = sum(p["value_usdt"] for p in positions) + (usdt_acc["available"] + usdt_acc["locked"] if usdt_acc else 0)
        except Exception:
            pass
    tickers = list_tickers(m)
    if tickers:
        for t in tickers:
            cp = getattr(t, "currency_pair", None) or (t.get("currency_pair") if isinstance(t, dict) else "")
            last = getattr(t, "last", None) or (t.get("last") if isinstance(t, dict) else "0")
            chg = getattr(t, "change_percentage", "0") if hasattr(t, "change_percentage") else (t.get("change_percentage", "0") if isinstance(t, dict) else "0")
            ticker_map_spot[cp] = {"last": last, "change_pct": chg}
    ft = list_futures_tickers(m, "usdt")
    if ft:
        for t in ft:
            contract = _ticker_attr(t, "contract") or ""
            if not contract:
                continue
            last = _ticker_attr(t, "last", "0")
            chg = _ticker_attr(t, "change_percentage", "0")
            ticker_map_fut[contract] = {"last": last, "change_pct": chg}
    tickers_out = {}
    for it in items:
        sym = it["symbol"]
        qm = it["quote_market"]
        key = f"{sym}@{qm}"
        if qm == "futures":
            tickers_out[key] = ticker_map_fut.get(sym) or {}
        else:
            tickers_out[key] = ticker_map_spot.get(sym) or {}
    data = {
        "symbols": symbols,
        "items": items,
        "positions": positions,
        "tickers": {k: v for k, v in tickers_out.items() if v},
        "balance_total": round(balance_total, 4),
        "mode": m,
    }
    return {"success": True, "data": data, "message": "ok", "code": 200}


@router.get("/smart-select-rules")
def get_smart_select_rules():
    """获取选币规则默认值，用于调节页面"""
    return {"success": True, "data": get_default_rules(), "message": "ok", "code": 200}


class SmartSelectBody(BaseModel):
    top_n: int = 10
    mode: str = "real"
    min_quote_volume: int | None = None   # 24h 成交额最低（USDT）
    max_change_24h: float | None = None   # 24h 涨跌幅上限（0.5=50%）
    min_price: float | None = None        # 最低价格


class AgentSelectBody(BaseModel):
    preference: str | None = None
    top_n: int = 10
    mode: str = "real"


class TradingStateBody(BaseModel):
    """开始交易时建议同时传 active_subscription_id；仅停止时可只传 trading_running=false"""
    trading_running: bool | None = None
    active_subscription_id: int | None = None


@router.post("/smart-select")
def smart_select(body: SmartSelectBody | None = Body(default=None), authorization: str = Header(None), db: Session = Depends(get_db)):
    """一键选币：规则引擎筛选优质币种"""
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    try:
        mode = (body.mode if body else None) or get_mode(db, uid) or "real"
        tickers = list_tickers(mode)
        if not tickers:
            return {"success": True, "data": {"symbols": [], "source": "rule_engine"}, "message": "ok", "code": 200}
        rules_override = {}
        if body:
            if body.min_quote_volume is not None:
                rules_override["min_quote_volume"] = body.min_quote_volume
            if body.max_change_24h is not None:
                rules_override["max_change_24h"] = body.max_change_24h
            if body.min_price is not None:
                rules_override["min_price"] = body.min_price
        candidates = apply_rules(tickers, mode, rules_override if rules_override else None)
        top_n = body.top_n if body else 10
        symbols = [{"symbol": c["symbol"], "reason": c.get("reason", "高流动性"), "score": round(c.get("volume", 0) / 1e6, 2)} for c in candidates[:top_n]]
        return {"success": True, "data": {"symbols": symbols, "source": "rule_engine"}, "message": "ok", "code": 200}
    except Exception as e:
        return {"success": False, "data": None, "message": str(e), "code": 500}


@router.post("/agent-select")
def agent_select(body: AgentSelectBody | None = Body(default=None), authorization: str = Header(None), db: Session = Depends(get_db)):
    """Agent 选币：已绑定 DeepSeek 时由模型在规则候选池内选出最优标的（默认 10 个）"""
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    api_key = get_deepseek_api_key(db, uid)
    if not api_key:
        return {
            "success": False,
            "data": {"needs_deepseek": True},
            "message": "请先绑定 DeepSeek API Key",
            "code": 400,
        }
    try:
        mode = (body.mode if body else None) or get_mode(db, uid) or "real"
        tickers = list_tickers(mode)
        if not tickers:
            return {"success": True, "data": {"symbols": [], "summary": "", "source": "deepseek_agent"}, "message": "ok", "code": 200}
        candidates = apply_rules(tickers, mode)[:55]
        if not candidates:
            return {"success": True, "data": {"symbols": [], "summary": "暂无符合规则的候选", "source": "deepseek_agent"}, "message": "ok", "code": 200}
        top_n = (body.top_n if body and body.top_n else 10) or 10
        top_n = max(3, min(15, int(top_n)))
        allowed = [c["symbol"] for c in candidates]
        rows = build_candidate_lines(
            [
                {
                    "symbol": c["symbol"],
                    "last": c.get("last"),
                    "change_pct": c.get("change_pct"),
                    "quote_volume": c.get("volume"),
                }
                for c in candidates
            ]
        )
        pref = body.preference if body and body.preference else None
        symbols, summary, _raw = run_agent_coin_pick(api_key, rows, allowed, pref, top_n=top_n)
        return {
            "success": True,
            "data": {"symbols": symbols, "summary": summary or "DeepSeek 选币完成。", "source": "deepseek_agent"},
            "message": "ok",
            "code": 200,
        }
    except Exception as e:
        return {"success": False, "data": None, "message": str(e), "code": 500}


@router.get("/trading-state")
def get_trading_state(authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    st = get_dashboard_trading(db, uid)
    active_name = None
    sub_mode = None
    sid = st.get("active_subscription_id")
    if sid:
        sub = db.query(Subscription).filter(Subscription.id == sid, Subscription.user_id == uid).first()
        if sub and sub.status != "cancelled":
            if sub.user_strategy_id:
                us = db.query(UserStrategy).filter(UserStrategy.id == sub.user_strategy_id).first()
                active_name = us.name if us else None
            else:
                strat = get_strategy(sub.strategy_id)
                active_name = strat["name"] if strat else None
            sub_mode = sub.mode
        else:
            st = {**st, "active_subscription_id": None}
    cur_mode = get_mode(db, uid)
    mode_mismatch = bool(st.get("trading_running") and sid and sub_mode and sub_mode != cur_mode)
    return {
        "success": True,
        "data": {
            **st,
            "active_strategy_name": active_name,
            "current_mode": cur_mode,
            "mode_mismatch": mode_mismatch,
        },
        "message": "ok",
        "code": 200,
    }


@router.put("/trading-state")
def put_trading_state(body: TradingStateBody, authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    cur = get_dashboard_trading(db, uid)
    m = get_mode(db, uid)

    if body.trading_running is True:
        sid = body.active_subscription_id if body.active_subscription_id is not None else cur.get("active_subscription_id")
        if not sid:
            return {
                "success": False,
                "data": None,
                "message": "请先在策略中心选择要运行的订阅策略",
                "code": 400,
            }
        sub = (
            db.query(Subscription)
            .filter(Subscription.id == int(sid), Subscription.user_id == uid)
            .first()
        )
        if not sub or sub.status != "active":
            return {"success": False, "data": None, "message": "订阅无效或未激活", "code": 400}
        if sub.mode != m:
            return {
                "success": False,
                "data": None,
                "message": f"该订阅属于「{sub.mode}」模式，与当前交易模式「{m}」不一致，请在策略中心切换或绑定对应模式",
                "code": 400,
            }
        patch_dashboard_trading(db, uid, trading_running=True, active_subscription_id=int(sid))
    elif body.trading_running is False:
        patch_dashboard_trading(db, uid, trading_running=False)
    else:
        if body.active_subscription_id is not None:
            sub = (
                db.query(Subscription)
                .filter(Subscription.id == int(body.active_subscription_id), Subscription.user_id == uid)
                .first()
            )
            if not sub or sub.status == "cancelled":
                return {"success": False, "data": None, "message": "订阅不存在", "code": 404}
            patch_dashboard_trading(db, uid, active_subscription_id=int(body.active_subscription_id))

    st = get_dashboard_trading(db, uid)
    active_name = None
    if st.get("active_subscription_id"):
        sub = db.query(Subscription).filter(Subscription.id == st["active_subscription_id"], Subscription.user_id == uid).first()
        if sub:
            if sub.user_strategy_id:
                us = db.query(UserStrategy).filter(UserStrategy.id == sub.user_strategy_id).first()
                active_name = us.name if us else None
            else:
                strat = get_strategy(sub.strategy_id)
                active_name = strat["name"] if strat else None
    return {
        "success": True,
        "data": {**st, "active_strategy_name": active_name, "current_mode": m},
        "message": "ok",
        "code": 200,
    }


class BatchWatchlistBody(BaseModel):
    symbols: list[str] | None = None
    # 可选：带市场的自选项；若提供则优先于 symbols（每项为 {symbol, quote_market?}）
    items: list[dict] | None = None


@router.post("/watchlist/batch")
def batch_add_watchlist(body: BatchWatchlistBody, authorization: str = Header(None), db: Session = Depends(get_db)):
    """批量加入自选"""
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    pairs: list[tuple[str, str]] = []
    if body.items:
        for it in (body.items or [])[:50]:
            if not isinstance(it, dict):
                continue
            sym = (it.get("symbol") or "").strip()
            if not sym:
                continue
            qm = _normalize_quote_market(it.get("quote_market"))
            pairs.append((sym, qm))
    else:
        for s in (body.symbols or [])[:50]:
            sym = (s or "").strip()
            if sym:
                pairs.append((sym, "spot"))
    if not pairs:
        return {"success": False, "data": None, "message": "symbols 不能为空", "code": 400}
    added = []
    skipped = []
    for sym, qm in pairs:
        if db.query(Watchlist).filter(Watchlist.user_id == uid, Watchlist.symbol == sym, Watchlist.quote_market == qm).first():
            skipped.append(f"{sym}:{qm}")
        else:
            db.add(Watchlist(user_id=uid, symbol=sym, quote_market=qm))
            added.append(f"{sym}:{qm}")
    db.commit()
    return {"success": True, "data": {"added": added, "skipped": skipped}, "message": f"已添加 {len(added)} 个", "code": 200}
