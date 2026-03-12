"""用户 API"""
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session
from core.database import get_db
from core.security import decode_token
from models.user import User

router = APIRouter()


def get_current_user_id(authorization: str = Header(None)) -> int | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    payload = decode_token(authorization[7:])
    return int(payload["sub"]) if payload and payload.get("sub") else None


class UpdateUserBody(BaseModel):
    nickname: str = None
    avatar: str = None


@router.get("/me")
def get_me(authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    user = db.query(User).filter(User.id == uid).first()
    if not user:
        return {"success": False, "data": None, "message": "用户不存在", "code": 404}
    return {
        "success": True,
        "data": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "nickname": user.nickname,
            "avatar": user.avatar,
        },
        "message": "ok",
        "code": 200,
    }


@router.patch("/me")
def update_me(body: UpdateUserBody, authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    user = db.query(User).filter(User.id == uid).first()
    if not user:
        return {"success": False, "data": None, "message": "用户不存在", "code": 404}
    if body.nickname is not None:
        user.nickname = body.nickname
    if body.avatar is not None:
        user.avatar = body.avatar
    db.commit()
    return {"success": True, "data": None, "message": "更新成功", "code": 200}
