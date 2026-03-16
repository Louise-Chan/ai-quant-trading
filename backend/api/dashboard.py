"""仪表盘 API - 选币、自选、行情、自选与模拟账户绑定"""
from fastapi import APIRouter, Query, Header, Depends, Body
from pydantic import BaseModel
from sqlalchemy.orm import Session
from core.database import get_db
from core.security import decode_token
from models.watchlist import Watchlist
from utils.gate_client import list_currency_pairs, list_tickers
from services.broker_service import get_broker, get_mode
from services.rule_engine import apply_rules, get_default_rules
from services.gate_account_service import get_positions_with_value, get_spot_accounts

router = APIRouter()


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


@router.get("/watchlist")
def get_watchlist(authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": {"symbols": []}, "message": "请先登录", "code": 401}
    items = db.query(Watchlist).filter(Watchlist.user_id == uid).all()
    symbols = [w.symbol for w in items]
    return {"success": True, "data": {"symbols": symbols}, "message": "ok", "code": 200}


@router.post("/watchlist")
def add_watchlist(symbol: str, authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    if db.query(Watchlist).filter(Watchlist.user_id == uid, Watchlist.symbol == symbol).first():
        return {"success": True, "data": None, "message": "已在自选", "code": 200}
    w = Watchlist(user_id=uid, symbol=symbol)
    db.add(w)
    db.commit()
    return {"success": True, "data": None, "message": "添加成功", "code": 200}


@router.delete("/watchlist/{symbol}")
def remove_watchlist(symbol: str, authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    db.query(Watchlist).filter(Watchlist.user_id == uid, Watchlist.symbol == symbol).delete()
    db.commit()
    return {"success": True, "data": None, "message": "移除成功", "code": 200}


@router.get("/tickers")
def get_tickers(symbols: str = Query(""), mode: str = Query("real")):
    """行情快照。mode=real 用实盘行情，mode=simulated 用模拟盘行情"""
    try:
        tickers = list_tickers(mode)
        ticker_map = {}
        if tickers:
            for t in tickers:
                cp = getattr(t, "currency_pair", None) or (t.get("currency_pair") if isinstance(t, dict) else "")
                last = getattr(t, "last", None) or (t.get("last") if isinstance(t, dict) else "0")
                chg = getattr(t, "change_percentage", "0") if hasattr(t, "change_percentage") else (t.get("change_percentage", "0") if isinstance(t, dict) else "0")
                ticker_map[cp] = {"last": last, "change_pct": chg}
        if symbols:
            wanted = [s.strip() for s in symbols.split(",") if s.strip()]
            ticker_map = {k: v for k, v in ticker_map.items() if k in wanted}
        return {"success": True, "data": ticker_map, "message": "ok", "code": 200}
    except Exception as e:
        return {"success": False, "data": {}, "message": str(e), "code": 500}


@router.get("/watchlist-with-positions")
def get_watchlist_with_positions(authorization: str = Header(None), db: Session = Depends(get_db)):
    """
    自选币 + 模拟/实盘账户持仓绑定。
    返回：symbols 自选列表，positions 持仓（含市值），tickers 行情，balance 总资产
    """
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    items = db.query(Watchlist).filter(Watchlist.user_id == uid).all()
    symbols = [w.symbol for w in items]
    m = get_mode(db, uid)
    broker = get_broker(db, uid, m)
    positions = []
    balance_total = 0.0
    ticker_map = {}
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
            ticker_map[cp] = {"last": last, "change_pct": chg}
    data = {
        "symbols": symbols,
        "positions": positions,
        "tickers": {k: v for k, v in ticker_map.items() if k in symbols or any(k == p.get("symbol") for p in positions)},
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
    top_n: int = 8
    mode: str = "real"


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
    """接入 Agent 选币：AI 分析推荐（暂复用规则引擎，待接入 LLM）"""
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    try:
        mode = (body.mode if body else None) or get_mode(db, uid) or "real"
        tickers = list_tickers(mode)
        if not tickers:
            return {"success": True, "data": {"symbols": [], "summary": "", "source": "ai_agent"}, "message": "ok", "code": 200}
        candidates = apply_rules(tickers, mode)
        top_n = body.top_n if body else 8
        symbols = [{"symbol": c["symbol"], "reason": c.get("reason", "高流动性")} for c in candidates[:top_n]]
        pref = body.preference if body and body.preference else ""
        summary = f"根据当前市场流动性，推荐以上 {len(symbols)} 个币种。" + (f"（偏好：{pref}）" if pref else "") + " Agent 完整分析功能开发中。"
        return {"success": True, "data": {"symbols": symbols, "summary": summary, "source": "ai_agent"}, "message": "ok", "code": 200}
    except Exception as e:
        return {"success": False, "data": None, "message": str(e), "code": 500}


class BatchWatchlistBody(BaseModel):
    symbols: list[str]


@router.post("/watchlist/batch")
def batch_add_watchlist(body: BatchWatchlistBody, authorization: str = Header(None), db: Session = Depends(get_db)):
    """批量加入自选"""
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    symbols = [s.strip() for s in (body.symbols or []) if s and s.strip()]
    if not symbols:
        return {"success": False, "data": None, "message": "symbols 不能为空", "code": 400}
    added = []
    skipped = []
    for sym in symbols[:50]:  # 最多 50 个
        if db.query(Watchlist).filter(Watchlist.user_id == uid, Watchlist.symbol == sym).first():
            skipped.append(sym)
        else:
            db.add(Watchlist(user_id=uid, symbol=sym))
            added.append(sym)
    db.commit()
    return {"success": True, "data": {"added": added, "skipped": skipped}, "message": f"已添加 {len(added)} 个", "code": 200}
