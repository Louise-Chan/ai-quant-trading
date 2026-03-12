"""成交记录模型"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Numeric
from sqlalchemy.sql import func
from core.database import Base


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    order_id = Column(Integer, ForeignKey("orders.id"))
    symbol = Column(String(32), nullable=False)
    price = Column(Numeric(20, 8), nullable=False)
    amount = Column(Numeric(20, 8), nullable=False)
    fee = Column(Numeric(20, 8), default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
