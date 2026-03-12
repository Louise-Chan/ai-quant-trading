"""资产净值 API"""
from fastapi import APIRouter, Query, Header, Depends
from sqlalchemy.orm import Session
from core.database import get_db
from core.security import decode_token
from models.user_preference import UserPreference
from services.broker_service import get_broker, get_mode, _parse_gate_error
from services.gate_account_service import get_total_balance_usdt

router = APIRouter()


def get_current_user_id(authorization: str = Header(None)) -> int | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    payload = decode_token(authorization[7:])
    return int(payload["sub"]) if payload and payload.get("sub") else None


@router.get("/balance")
def get_balance(mode: str = Query(None), authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    m = mode or get_mode(db, uid)
    broker = get_broker(db, uid, m)
    if broker:
        try:
            avail, frozen, total = get_total_balance_usdt(m, broker.api_key_enc, broker.api_secret_enc)
            data = {
                "available": round(avail, 4),
                "frozen": round(frozen, 4),
                "total": round(total, 4),
                "today_pnl": None,  # 暂无收益时显示 --
                "data_source": "gate",
            }
            return {"success": True, "data": data, "message": "ok", "code": 200}
        except Exception as e:
            return {"success": False, "data": None, "message": _parse_gate_error(e), "code": 500}
    # 未绑定交易所时返回 null，前端用 -- 展示
    data = {"available": None, "frozen": None, "total": None, "today_pnl": None}
    return {"success": True, "data": data, "message": "未绑定交易所，请先绑定 Gate.io 模拟 API", "code": 200}
