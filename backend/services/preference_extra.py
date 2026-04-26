"""用户偏好 extra_json 读写（DeepSeek API Key 等）"""
import json
from sqlalchemy.orm import Session
from models.user_preference import UserPreference


def get_extra_dict(db: Session, user_id: int) -> dict:
    pref = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
    if not pref or not pref.extra_json:
        return {}
    try:
        return json.loads(pref.extra_json)
    except Exception:
        return {}


def set_extra_key(db: Session, user_id: int, key: str, value: str | None):
    """value 为空字符串或 None 时删除该键"""
    pref = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
    d = get_extra_dict(db, user_id) if pref else {}
    if value is None or (isinstance(value, str) and value.strip() == ""):
        d.pop(key, None)
    else:
        d[key] = value
    raw = json.dumps(d, ensure_ascii=False) if d else None
    if pref:
        pref.extra_json = raw
    else:
        pref = UserPreference(user_id=user_id, current_mode="simulated", extra_json=raw)
        db.add(pref)
    db.commit()


def get_deepseek_api_key(db: Session, user_id: int) -> str | None:
    k = get_extra_dict(db, user_id).get("deepseek_api_key")
    return k if isinstance(k, str) and k.strip() else None


_MISSING = object()


def get_dashboard_trading(db: Session, user_id: int) -> dict:
    dash = get_extra_dict(db, user_id).get("dashboard") or {}
    sid = dash.get("active_subscription_id")
    try:
        sid = int(sid) if sid is not None else None
    except (TypeError, ValueError):
        sid = None
    cap = dash.get("custody_max_opens_per_day")
    try:
        cap = int(cap) if cap is not None else 0
    except (TypeError, ValueError):
        cap = 0
    cap = max(0, min(cap, 9999))
    return {
        "trading_running": bool(dash.get("trading_running")),
        "active_subscription_id": sid,
        "custody_running": bool(dash.get("custody_running")),
        "custody_max_opens_per_day": cap,
    }


def patch_dashboard_trading(
    db: Session,
    user_id: int,
    *,
    trading_running=_MISSING,
    active_subscription_id=_MISSING,
    custody_running=_MISSING,
    custody_max_opens_per_day=_MISSING,
):
    """更新仪表盘「开始/停止交易」状态；未传入的字段保持不变"""
    pref = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
    d = get_extra_dict(db, user_id)
    dash = dict(d.get("dashboard") or {})
    if trading_running is not _MISSING:
        dash["trading_running"] = bool(trading_running)
    if active_subscription_id is not _MISSING:
        if active_subscription_id is None or active_subscription_id == 0:
            dash["active_subscription_id"] = None
        else:
            dash["active_subscription_id"] = int(active_subscription_id)
    if custody_running is not _MISSING:
        dash["custody_running"] = bool(custody_running)
    if custody_max_opens_per_day is not _MISSING:
        try:
            v = int(custody_max_opens_per_day or 0)
        except (TypeError, ValueError):
            v = 0
        dash["custody_max_opens_per_day"] = max(0, min(v, 9999))
    d["dashboard"] = dash
    raw = json.dumps(d, ensure_ascii=False) if d else None
    if pref:
        pref.extra_json = raw
    else:
        pref = UserPreference(user_id=user_id, current_mode="simulated", extra_json=raw)
        db.add(pref)
    db.commit()
