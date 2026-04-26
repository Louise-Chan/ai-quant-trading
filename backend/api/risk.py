"""风险设置 API"""
from fastapi import APIRouter, Query, Header, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from core.database import get_db
from core.security import decode_token
from services.risk_settings_memory import risk_settings_for_user, set_risk_settings

router = APIRouter()


def get_current_user_id(authorization: str = Header(None)) -> int | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    payload = decode_token(authorization[7:])
    return int(payload["sub"]) if payload and payload.get("sub") else None


def get_mode(db: Session, user_id: int) -> str:
    from models.user_preference import UserPreference
    pref = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
    return pref.current_mode if pref else "simulated"


class RiskSettingsBody(BaseModel):
    max_position_pct: float = None
    stop_loss: float = None


@router.get("/settings")
def get_risk_settings(mode: str = Query(None), authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    m = mode or get_mode(db, uid)
    data = risk_settings_for_user(uid, m)
    return {"success": True, "data": data, "message": "ok", "code": 200}


@router.put("/settings")
def update_risk_settings(body: RiskSettingsBody, mode: str = Query(None),
                        authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    m = mode or get_mode(db, uid)
    patch = {}
    if body.max_position_pct is not None:
        patch["max_position_pct"] = body.max_position_pct
    if body.stop_loss is not None:
        patch["stop_loss"] = body.stop_loss
    set_risk_settings(uid, m, patch)
    return {"success": True, "data": None, "message": "更新成功", "code": 200}
