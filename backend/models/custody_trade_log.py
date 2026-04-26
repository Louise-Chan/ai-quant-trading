"""托管跟单执行日志"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from core.database import Base


class CustodyTradeLog(Base):
    __tablename__ = "custody_trade_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    mode = Column(String(16), nullable=False)
    user_strategy_id = Column(Integer, ForeignKey("user_strategies.id"), nullable=False, index=True)
    symbol = Column(String(64), nullable=False)

    signal_side = Column(String(16), nullable=True)
    order_type = Column(String(16), nullable=True)
    price = Column(String(64), nullable=True)
    amount = Column(String(64), nullable=True)

    status = Column(String(16), nullable=False, default="pending")
    message = Column(Text, nullable=True)
    details_json = Column(Text, nullable=True)
    exchange_order_id = Column(String(64), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
