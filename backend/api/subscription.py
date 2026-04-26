"""策略订阅 API"""
from fastapi import APIRouter, Header, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from core.database import get_db
from core.security import decode_token
from models.subscription import Subscription
from models.user_strategy import UserStrategy
from services.strategy_definitions import get_strategy

router = APIRouter()


def get_current_user_id(authorization: str = Header(None)) -> int | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    payload = decode_token(authorization[7:])
    return int(payload["sub"]) if payload and payload.get("sub") else None


class SubscribeBody(BaseModel):
    strategy_id: int = 0
    user_strategy_id: int | None = None
    mode: str  # real | simulated
    params: dict = None


class UpdateParamsBody(BaseModel):
    params: dict


@router.get("/subscriptions")
def get_subscriptions(authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": {"list": []}, "message": "请先登录", "code": 401}
    items = db.query(Subscription).filter(Subscription.user_id == uid).all()
    lst = [
        {
            "id": s.id,
            "strategy_id": s.strategy_id,
            "user_strategy_id": s.user_strategy_id,
            "mode": s.mode,
            "params": s.params_json,
            "status": s.status,
        }
        for s in items
    ]
    return {"success": True, "data": {"list": lst}, "message": "ok", "code": 200}


@router.post("/subscribe")
def subscribe(body: SubscribeBody, authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    import json

    usid = body.user_strategy_id
    sid = int(body.strategy_id or 0)
    if usid:
        u = db.query(UserStrategy).filter(UserStrategy.id == int(usid), UserStrategy.user_id == uid).first()
        if not u or u.status != "active":
            return {"success": False, "data": None, "message": "用户策略不存在或已删除", "code": 404}
        sid = 0
    else:
        if sid <= 0:
            return {"success": False, "data": None, "message": "请指定 user_strategy_id 或有效的 strategy_id", "code": 400}
        if not get_strategy(sid):
            return {"success": False, "data": None, "message": "内置策略不存在", "code": 404}

    sub = Subscription(
        user_id=uid,
        strategy_id=sid,
        user_strategy_id=int(usid) if usid else None,
        mode=body.mode,
        params_json=json.dumps(body.params or {}),
        status="active",
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return {"success": True, "data": {"subscription_id": sub.id}, "message": "订阅成功", "code": 200}


@router.patch("/subscriptions/{sub_id}")
def update_subscription(sub_id: int, body: UpdateParamsBody, authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    sub = db.query(Subscription).filter(Subscription.id == sub_id, Subscription.user_id == uid).first()
    if not sub:
        return {"success": False, "data": None, "message": "订阅不存在", "code": 404}
    import json
    sub.params_json = json.dumps(body.params or {})
    db.commit()
    return {"success": True, "data": None, "message": "更新成功", "code": 200}


@router.delete("/subscriptions/{sub_id}")
def cancel_subscription(sub_id: int, authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    sub = db.query(Subscription).filter(Subscription.id == sub_id, Subscription.user_id == uid).first()
    if not sub:
        return {"success": False, "data": None, "message": "订阅不存在", "code": 404}
    sub.status = "cancelled"
    db.commit()
    return {"success": True, "data": None, "message": "已取消订阅", "code": 200}
