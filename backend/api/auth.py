"""认证 API"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from core.database import get_db
from services.auth_service import authenticate_user, create_user, create_token_for_user
from models.user import User

router = APIRouter()


@router.get("/check")
def check_availability(username: str = Query(None), email: str = Query(None), db: Session = Depends(get_db)):
    """检查用户名/邮箱是否已被注册，用于注册页实时校验"""
    result = {"username_exists": False, "email_exists": False}
    if username and username.strip():
        result["username_exists"] = db.query(User).filter(User.username == username.strip()).first() is not None
    if email and email.strip():
        result["email_exists"] = db.query(User).filter(User.email == email.strip()).first() is not None
    return {"success": True, "data": result}


class RegisterBody(BaseModel):
    username: str
    password: str
    email: str = None


class LoginBody(BaseModel):
    username: str
    password: str


@router.post("/register")
def register(body: RegisterBody, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == body.username).first():
        return {"success": False, "data": None, "message": "用户名已存在", "code": 400}
    email_val = (body.email or "").strip() or None
    if email_val:
        if db.query(User).filter(User.email == email_val).first():
            return {"success": False, "data": None, "message": "该邮箱已被注册过", "code": 400}
    user = create_user(db, body.username, body.password, email_val or None)
    token = create_token_for_user(user)
    return {
        "success": True,
        "data": {"user": {"id": user.id, "username": user.username, "email": user.email}, "token": token},
        "message": "注册成功",
        "code": 200,
    }


@router.post("/login")
def login(body: LoginBody, db: Session = Depends(get_db)):
    user = authenticate_user(db, body.username, body.password)
    if not user:
        return {"success": False, "data": None, "message": "用户名或密码错误", "code": 401}
    token = create_token_for_user(user)
    return {
        "success": True,
        "data": {"user": {"id": user.id, "username": user.username, "email": user.email}, "token": token},
        "message": "登录成功",
        "code": 200,
    }


@router.post("/logout")
def logout():
    return {"success": True, "data": None, "message": "已登出", "code": 200}


@router.post("/refresh")
def refresh_token():
    return {"success": False, "data": None, "message": "请重新登录", "code": 400}
