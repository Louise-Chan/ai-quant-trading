"""安全：密码哈希、JWT"""
from datetime import datetime, timedelta
from typing import Optional

# 兼容 passlib 与 bcrypt 4.1+：新版 bcrypt 移除了 __about__，passlib 仍会读取
import bcrypt
if not hasattr(bcrypt, "__about__"):
    import types
    bcrypt.__about__ = types.SimpleNamespace(__version__=getattr(bcrypt, "__version__", "4.0.1"))

from jose import JWTError, jwt
from passlib.context import CryptContext
from config import get_settings

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None
