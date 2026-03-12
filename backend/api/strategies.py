"""策略中心 API"""
from fastapi import APIRouter, Query, Header, Depends
from sqlalchemy.orm import Session
from core.database import get_db
from core.security import decode_token

router = APIRouter()


def get_current_user_id(authorization: str = Header(None)) -> int | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    payload = decode_token(authorization[7:])
    return int(payload["sub"]) if payload and payload.get("sub") else None


# Mock 策略列表
MOCK_STRATEGIES = [
    {"id": 1, "name": "稳健增长", "category": "稳健", "risk_level": "低", "description": "适合稳健型投资者"},
    {"id": 2, "name": "积极进取", "category": "积极", "risk_level": "中", "description": "适合积极型投资者"},
]


@router.get("")
def list_strategies(page: int = Query(1), size: int = Query(20), category: str = Query(None)):
    lst = MOCK_STRATEGIES
    if category:
        lst = [s for s in lst if s.get("category") == category]
    start = (page - 1) * size
    return {"success": True, "data": {"list": lst[start:start + size], "total": len(lst)}, "message": "ok", "code": 200}


@router.get("/{strategy_id}")
def get_strategy_detail(strategy_id: int):
    s = next((x for x in MOCK_STRATEGIES if x["id"] == strategy_id), None)
    if not s:
        return {"success": False, "data": None, "message": "策略不存在", "code": 404}
    return {"success": True, "data": s, "message": "ok", "code": 200}
