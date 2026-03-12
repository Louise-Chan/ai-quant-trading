"""交易所绑定 API"""
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session
from core.database import get_db
from core.security import decode_token
from services.broker_service import bind_broker, get_broker_status, set_mode, unbind_broker, get_broker, get_mode
from utils.gate_client import HOST_REAL, HOST_SIMULATED

router = APIRouter()


def get_current_user_id(authorization: str = Header(None)) -> int | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    payload = decode_token(authorization[7:])
    return int(payload["sub"]) if payload and payload.get("sub") else None


class BindBody(BaseModel):
    mode: str  # real | simulated
    api_key: str
    api_secret: str


class ModeBody(BaseModel):
    mode: str


@router.post("/bind")
def bind(body: BindBody, authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    if body.mode not in ("real", "simulated"):
        return {"success": False, "data": None, "message": "mode 必须为 real 或 simulated", "code": 400}
    try:
        broker = bind_broker(db, uid, body.mode, body.api_key, body.api_secret)
        return {"success": True, "data": {"broker_id": broker.id}, "message": "绑定成功", "code": 200}
    except ValueError as e:
        return {"success": False, "data": None, "message": str(e), "code": 400}


@router.get("/status")
def status(authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    data = get_broker_status(db, uid)
    m = get_mode(db, uid)
    broker = get_broker(db, uid, m)
    data = {
        **data,
        "user_id": uid,
        "broker_found": broker is not None,
        "broker_mode": broker.mode if broker else None,
        "gate_host": HOST_SIMULATED if m == "simulated" else HOST_REAL,
    }
    return {"success": True, "data": data, "message": "ok", "code": 200}


@router.put("/mode")
def switch_mode(body: ModeBody, authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    if body.mode not in ("real", "simulated"):
        return {"success": False, "data": None, "message": "mode 必须为 real 或 simulated", "code": 400}
    set_mode(db, uid, body.mode)
    return {"success": True, "data": None, "message": "切换成功", "code": 200}


@router.delete("/unbind")
def unbind(mode: str = None, authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    unbind_broker(db, uid, mode)
    return {"success": True, "data": None, "message": "解绑成功", "code": 200}


