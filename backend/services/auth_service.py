"""认证服务"""
import json

from sqlalchemy.orm import Session

from core.security import verify_password, get_password_hash, create_access_token
from models.user import User
from models.user_strategy import UserStrategy
from services.strategy_engine.factors import DEFAULT_BUILTIN_FACTOR_IDS


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    user = db.query(User).filter(User.username == username).first()
    if user and verify_password(password, user.password_hash):
        return user
    return None


def _seed_default_builtin_user_strategy(db: Session, user_id: int) -> None:
    """新用户默认一条「内置策略」配置，因子为 rev_1 / vol_20 / vol_z。"""
    cfg = {
        "symbols": "",
        "interval": "1h",
        "max_opens_per_day": 0,
        "avg_daily_mode": "trading",
        "active_factors": list(DEFAULT_BUILTIN_FACTOR_IDS),
    }
    r = UserStrategy(
        user_id=user_id,
        name="内置策略（默认）",
        description="默认因子：1期反转、20期波动、成交量Z（rev_1, vol_20, vol_z）",
        status="active",
        config_json=json.dumps(cfg, ensure_ascii=False),
        weights_json=json.dumps({}, ensure_ascii=False),
        backtest_summary_json=None,
    )
    db.add(r)


def create_user(db: Session, username: str, password: str, email: str = None) -> User:
    user = User(
        username=username,
        password_hash=get_password_hash(password),
        email=email,
    )
    db.add(user)
    db.flush()
    _seed_default_builtin_user_strategy(db, user.id)
    db.commit()
    db.refresh(user)
    return user


def create_token_for_user(user: User) -> str:
    return create_access_token(data={"sub": str(user.id), "username": user.username})
