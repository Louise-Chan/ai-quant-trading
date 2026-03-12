"""认证服务"""
from sqlalchemy.orm import Session
from models.user import User
from core.security import verify_password, get_password_hash, create_access_token


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    user = db.query(User).filter(User.username == username).first()
    if user and verify_password(password, user.password_hash):
        return user
    return None


def create_user(db: Session, username: str, password: str, email: str = None) -> User:
    user = User(
        username=username,
        password_hash=get_password_hash(password),
        email=email,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_token_for_user(user: User) -> str:
    return create_access_token(data={"sub": str(user.id), "username": user.username})
