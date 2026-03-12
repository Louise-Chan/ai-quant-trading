"""交易记录 API - 订单、持仓、成交"""
from fastapi import APIRouter, Query, Header, Depends
from sqlalchemy.orm import Session
from core.database import get_db
from core.security import decode_token
from models.user_preference import UserPreference
from models.watchlist import Watchlist
from services.broker_service import get_broker, get_mode
from services.gate_account_service import (
    get_open_orders,
    get_finished_orders,
    get_my_trades,
    get_positions_with_value,
    cancel_order as gate_cancel_order,
)

router = APIRouter()


def get_current_user_id(authorization: str = Header(None)) -> int | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    payload = decode_token(authorization[7:])
    return int(payload["sub"]) if payload and payload.get("sub") else None


@router.get("/orders")
def get_orders(
    mode: str = Query(None),
    status: str = Query(None),
    symbol: str = Query(None),
    page: int = Query(1),
    size: int = Query(20),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": {"list": [], "total": 0}, "message": "请先登录", "code": 401}
    m = mode or get_mode(db, uid)
    broker = get_broker(db, uid, m)
    if not broker:
        return {"success": True, "data": {"list": [], "total": 0}, "message": "ok", "code": 200}
    try:
        if status == "open" or not status:
            lst = get_open_orders(m, broker.api_key_enc, broker.api_secret_enc, page, size)
        else:
            symbols = [symbol] if symbol else [w.symbol for w in db.query(Watchlist).filter(Watchlist.user_id == uid).limit(20).all()]
            lst = get_finished_orders(m, broker.api_key_enc, broker.api_secret_enc, symbol, symbols, page, size)
        if symbol:
            lst = [o for o in lst if o.get("symbol") == symbol]
        total = len(lst)
        return {"success": True, "data": {"list": lst, "total": total}, "message": "ok", "code": 200}
    except Exception as e:
        return {"success": False, "data": {"list": [], "total": 0}, "message": str(e), "code": 500}


@router.get("/orders/{order_id}")
def get_order_detail(order_id: str, symbol: str = Query(None), authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    return {"success": True, "data": None, "message": "ok", "code": 200}


@router.post("/orders/cancel/{order_id}")
def cancel_order(order_id: str, symbol: str = Query(..., description="交易对如 BTC_USDT"), authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    m = get_mode(db, uid)
    broker = get_broker(db, uid, m)
    if not broker:
        return {"success": False, "data": None, "message": "未绑定交易所", "code": 400}
    try:
        ok = gate_cancel_order(m, broker.api_key_enc, broker.api_secret_enc, order_id, symbol)
        return {"success": ok, "data": None, "message": "撤单成功" if ok else "撤单失败", "code": 200}
    except Exception as e:
        return {"success": False, "data": None, "message": str(e), "code": 500}


@router.get("/positions")
def get_positions(mode: str = Query(None), authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": {"list": []}, "message": "请先登录", "code": 401}
    m = mode or get_mode(db, uid)
    broker = get_broker(db, uid, m)
    if not broker:
        return {"success": True, "data": {"list": []}, "message": "ok", "code": 200}
    try:
        lst = get_positions_with_value(m, broker.api_key_enc, broker.api_secret_enc)
        return {"success": True, "data": {"list": lst}, "message": "ok", "code": 200}
    except Exception as e:
        return {"success": False, "data": {"list": []}, "message": str(e), "code": 500}


@router.get("/trades")
def get_trades(
    mode: str = Query(None),
    symbol: str = Query(None),
    page: int = Query(1),
    size: int = Query(20),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": {"list": [], "total": 0}, "message": "请先登录", "code": 401}
    m = mode or get_mode(db, uid)
    broker = get_broker(db, uid, m)
    if not broker:
        return {"success": True, "data": {"list": [], "total": 0}, "message": "ok", "code": 200}
    try:
        lst = get_my_trades(m, broker.api_key_enc, broker.api_secret_enc, symbol, page, size)
        return {"success": True, "data": {"list": lst, "total": len(lst)}, "message": "ok", "code": 200}
    except Exception as e:
        return {"success": False, "data": {"list": [], "total": 0}, "message": str(e), "code": 500}
