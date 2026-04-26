"""策略订阅模型"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from core.database import Base


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    strategy_id = Column(Integer, nullable=False, default=0)  # 0 = 用户自定义策略，见 user_strategy_id
    user_strategy_id = Column(Integer, ForeignKey("user_strategies.id"), nullable=True, index=True)
    mode = Column(String(16), nullable=False)  # real | simulated
    params_json = Column(Text)
    status = Column(String(16), default="active")  # active | paused | cancelled
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
