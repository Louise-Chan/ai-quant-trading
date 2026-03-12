"""仪表盘 API - 选币、自选、行情、自选与模拟账户绑定"""
from fastapi import APIRouter, Query, Header, Depends
from sqlalchemy.orm import Session
from core.database import get_db
from core.security import decode_token
from models.watchlist import Watchlist
from utils.gate_client import list_currency_pairs, list_tickers
from services.broker_service import get_broker, get_mode
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
