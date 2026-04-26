"""策略中心 API：列表与详情来自用户保存策略（回测页）"""
from fastapi import APIRouter, Query, Header, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from core.database import get_db
from core.security import decode_token
from models.subscription import Subscription
from models.user_strategy import UserStrategy
from services.strategy_definitions import get_strategy
from services.strategy_risk_store import get_risk_settings, update_risk_settings
from services.preference_extra import get_deepseek_api_key
from services.deepseek_risk_presets import run_risk_presets
from services.broker_service import get_broker, get_mode
from services.gate_account_service import get_total_balance_usdt
from services.preference_extra import get_dashboard_trading

router = APIRouter()

_USER_STRATEGY_CAPS = {
    "max_position_pct": 0.30,
    "max_single_order_pct": 0.10,
    "max_stop_loss_magnitude": 0.10,
}


def get_current_user_id(authorization: str = Header(None)) -> int | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    payload = decode_token(authorization[7:])
    return int(payload["sub"]) if payload and payload.get("sub") else None


@router.get("")
def list_strategies(
    page: int = Query(1),
    size: int = Query(20),
    category: str = Query(None),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": {"list": [], "total": 0}, "message": "请先登录", "code": 401}
    q = db.query(UserStrategy).filter(UserStrategy.user_id == uid, UserStrategy.status == "active")
    total = q.count()
    rows = q.order_by(UserStrategy.id.desc()).offset((page - 1) * size).limit(size).all()
    caps = _USER_STRATEGY_CAPS
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
        lst.append(
            {
                "id": r.id,
                "name": r.name,
                "category": "自定义",
                "risk_level": "—",
                "description": r.description or "回测页保存的策略",
                "max_position_pct_cap": caps.get("max_position_pct"),
                "max_single_order_pct_cap": caps.get("max_single_order_pct"),
                "user_strategy_id": r.id,
                "in_use": bool(in_use_usid and in_use_usid == r.id),
            }
        )
    return {"success": True, "data": {"list": lst, "total": total}, "message": "ok", "code": 200}


class SubscriptionRiskBody(BaseModel):
    max_position_pct: float | None = None
    stop_loss: float | None = None
    max_single_order_pct: float | None = None


@router.get("/subscriptions/{subscription_id}/risk")
def get_subscription_risk(
    subscription_id: int,
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    sub = (
        db.query(Subscription)
        .filter(Subscription.id == subscription_id, Subscription.user_id == uid)
        .first()
    )
    if not sub or sub.status == "cancelled":
        return {"success": False, "data": None, "message": "订阅不存在", "code": 404}
    strat = None
    caps = {}
    name = ""
    if sub.user_strategy_id:
        us = db.query(UserStrategy).filter(UserStrategy.id == sub.user_strategy_id, UserStrategy.user_id == uid).first()
        if not us:
            return {"success": False, "data": None, "message": "策略不存在", "code": 404}
        name = us.name
        caps = dict(_USER_STRATEGY_CAPS)
    else:
        strat = get_strategy(sub.strategy_id)
        if not strat:
            return {"success": False, "data": None, "message": "策略不存在", "code": 404}
        name = strat["name"]
        caps = strat.get("risk_caps") or {}
    settings = get_risk_settings(uid, sub.mode, subscription_id, caps)
    return {
        "success": True,
        "data": {
            "subscription_id": subscription_id,
            "strategy_id": sub.strategy_id,
            "user_strategy_id": sub.user_strategy_id,
            "strategy_name": name,
            "mode": sub.mode,
            "risk_caps": caps,
            "settings": settings,
        },
        "message": "ok",
        "code": 200,
    }


@router.put("/subscriptions/{subscription_id}/risk")
def put_subscription_risk(
    subscription_id: int,
    body: SubscriptionRiskBody,
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    sub = (
        db.query(Subscription)
        .filter(Subscription.id == subscription_id, Subscription.user_id == uid)
        .first()
    )
    if not sub or sub.status == "cancelled":
        return {"success": False, "data": None, "message": "订阅不存在", "code": 404}
    strat = None
    caps = {}
    if sub.user_strategy_id:
        us = db.query(UserStrategy).filter(UserStrategy.id == sub.user_strategy_id, UserStrategy.user_id == uid).first()
        if not us:
            return {"success": False, "data": None, "message": "策略不存在", "code": 404}
        caps = dict(_USER_STRATEGY_CAPS)
    else:
        strat = get_strategy(sub.strategy_id)
        if not strat:
            return {"success": False, "data": None, "message": "策略不存在", "code": 404}
        caps = strat.get("risk_caps") or {}
    patch = {
        "max_position_pct": body.max_position_pct,
        "stop_loss": body.stop_loss,
        "max_single_order_pct": body.max_single_order_pct,
    }
    settings = update_risk_settings(uid, sub.mode, subscription_id, caps, patch)
    return {"success": True, "data": {"settings": settings, "risk_caps": caps}, "message": "已更新", "code": 200}


@router.post("/subscriptions/{subscription_id}/risk/presets/deepseek")
def post_subscription_risk_presets_deepseek(
    subscription_id: int,
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
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
    sub = (
        db.query(Subscription)
        .filter(Subscription.id == subscription_id, Subscription.user_id == uid)
        .first()
    )
    if not sub or sub.status == "cancelled":
        return {"success": False, "data": None, "message": "订阅不存在", "code": 404}
    strat = None
    caps = {}
    strat_name = ""
    if sub.user_strategy_id:
        us = db.query(UserStrategy).filter(UserStrategy.id == sub.user_strategy_id, UserStrategy.user_id == uid).first()
        if not us:
            return {"success": False, "data": None, "message": "策略不存在", "code": 404}
        caps = dict(_USER_STRATEGY_CAPS)
        strat_name = us.name
        desc = us.description or ""
    else:
        strat = get_strategy(sub.strategy_id)
        if not strat:
            return {"success": False, "data": None, "message": "策略不存在", "code": 404}
        caps = strat.get("risk_caps") or {}
        strat_name = strat["name"]
        desc = strat.get("description") or ""
    hint = ""
    broker = get_broker(db, uid, sub.mode)
    if broker:
        try:
            _, _, total = get_total_balance_usdt(sub.mode, broker.api_key_enc, broker.api_secret_enc)
            hint = f"当前账户总资产约 {round(float(total), 2)} USDT（{sub.mode}）。"
        except Exception:
            hint = "暂无法拉取账户资产，请按中性假设给出预设。"

    try:
        data, _raw = run_risk_presets(api_key, strat_name, desc, caps, hint)
    except Exception as e:
        return {"success": False, "data": None, "message": str(e), "code": 500}

    return {"success": True, "data": data, "message": "ok", "code": 200}


@router.get("/{strategy_id}")
def get_strategy_detail(strategy_id: int, authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    r = db.query(UserStrategy).filter(UserStrategy.id == strategy_id, UserStrategy.user_id == uid).first()
    if not r:
        return {"success": False, "data": None, "message": "策略不存在", "code": 404}
    caps = dict(_USER_STRATEGY_CAPS)
    return {
        "success": True,
        "data": {
            "id": r.id,
            "name": r.name,
            "category": "自定义",
            "risk_level": "—",
            "description": r.description or "",
            "risk_caps": caps,
            "user_strategy_id": r.id,
        },
        "message": "ok",
        "code": 200,
    }
