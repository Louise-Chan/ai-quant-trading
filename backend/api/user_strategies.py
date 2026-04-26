"""用户保存策略（回测页持久化）"""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.database import get_db
from core.security import decode_token
from models.subscription import Subscription
from models.user_strategy import UserStrategy
from services.preference_extra import get_dashboard_trading

router = APIRouter()


def get_current_user_id(authorization: str = Header(None)) -> int | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    payload = decode_token(authorization[7:])
    return int(payload["sub"]) if payload and payload.get("sub") else None


class UserStrategyBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = None
    config_json: dict | None = None
    weights_json: dict | None = None
    backtest_summary_json: dict | None = None


class UserStrategyRenameBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


def _dump(d: dict | None) -> str | None:
    if not d:
        return None
    return json.dumps(d, ensure_ascii=False)


@router.get("")
def list_user_strategies(authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": {"list": []}, "message": "请先登录", "code": 401}
    rows = (
        db.query(UserStrategy)
        .filter(UserStrategy.user_id == uid, UserStrategy.status == "active")
        .order_by(UserStrategy.id.desc())
        .all()
    )
    st = get_dashboard_trading(db, uid)
    active_sid = st.get("active_subscription_id")
    in_use_usid = None
    if active_sid:
        sub_run = (
            db.query(Subscription)
            .filter(Subscription.id == int(active_sid), Subscription.user_id == uid)
            .first()
        )
        if sub_run and sub_run.user_strategy_id:
            in_use_usid = int(sub_run.user_strategy_id)
    lst = []
    for r in rows:
        summary = None
        if r.backtest_summary_json:
            try:
                summary = json.loads(r.backtest_summary_json)
            except Exception:
                summary = None
        lst.append(
            {
                "id": r.id,
                "name": r.name,
                "description": r.description or "",
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                "last_backtest_at": r.last_backtest_at.isoformat() if r.last_backtest_at else None,
                "backtest_summary": summary,
                "in_use": bool(in_use_usid and in_use_usid == r.id),
            }
        )
    return {"success": True, "data": {"list": lst}, "message": "ok", "code": 200}


@router.get("/{sid}")
def get_user_strategy(sid: int, authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    r = db.query(UserStrategy).filter(UserStrategy.id == sid, UserStrategy.user_id == uid).first()
    if not r:
        return {"success": False, "data": None, "message": "策略不存在", "code": 404}
    cfg = {}
    w = {}
    summ = None
    try:
        cfg = json.loads(r.config_json or "{}") if r.config_json else {}
    except Exception:
        pass
    try:
        w = json.loads(r.weights_json or "{}") if r.weights_json else {}
    except Exception:
        pass
    try:
        summ = json.loads(r.backtest_summary_json) if r.backtest_summary_json else None
    except Exception:
        summ = None
    return {
        "success": True,
        "data": {
            "id": r.id,
            "name": r.name,
            "description": r.description or "",
            "config": cfg,
            "weights": w,
            "backtest_summary": summ,
            "last_backtest_at": r.last_backtest_at.isoformat() if r.last_backtest_at else None,
        },
        "message": "ok",
        "code": 200,
    }


@router.post("")
def create_user_strategy(body: UserStrategyBody, authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    now = datetime.now(timezone.utc)
    r = UserStrategy(
        user_id=uid,
        name=body.name.strip(),
        description=(body.description or "").strip() or None,
        status="active",
        config_json=_dump(body.config_json or {}),
        weights_json=_dump(body.weights_json or {}),
        backtest_summary_json=_dump(body.backtest_summary_json),
        last_backtest_at=now if body.backtest_summary_json else None,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return {"success": True, "data": {"id": r.id}, "message": "已保存", "code": 200}


@router.patch("/{sid}/name")
def patch_user_strategy_name(
    sid: int, body: UserStrategyRenameBody, authorization: str = Header(None), db: Session = Depends(get_db)
):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    r = db.query(UserStrategy).filter(UserStrategy.id == sid, UserStrategy.user_id == uid).first()
    if not r:
        return {"success": False, "data": None, "message": "策略不存在", "code": 404}
    r.name = body.name.strip()
    db.commit()
    return {"success": True, "data": {"id": r.id, "name": r.name}, "message": "已更新名称", "code": 200}


@router.put("/{sid}")
def update_user_strategy(sid: int, body: UserStrategyBody, authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    r = db.query(UserStrategy).filter(UserStrategy.id == sid, UserStrategy.user_id == uid).first()
    if not r:
        return {"success": False, "data": None, "message": "策略不存在", "code": 404}
    r.name = body.name.strip()
    r.description = (body.description or "").strip() or None
    r.config_json = _dump(body.config_json or {})
    r.weights_json = _dump(body.weights_json or {})
    if body.backtest_summary_json is not None:
        r.backtest_summary_json = _dump(body.backtest_summary_json)
        r.last_backtest_at = datetime.now(timezone.utc)
    db.commit()
    return {"success": True, "data": {"id": r.id}, "message": "已更新", "code": 200}


@router.delete("/{sid}")
def delete_user_strategy(sid: int, authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    r = db.query(UserStrategy).filter(UserStrategy.id == sid, UserStrategy.user_id == uid).first()
    if not r:
        return {"success": False, "data": None, "message": "策略不存在", "code": 404}
    r.status = "deleted"
    db.commit()
    return {"success": True, "data": None, "message": "已删除", "code": 200}
