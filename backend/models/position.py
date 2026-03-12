"""持仓模型"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Numeric
from sqlalchemy.sql import func
from core.database import Base


class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    broker_id = Column(Integer, ForeignKey("broker_accounts.id"), nullable=False)
    symbol = Column(String(32), nullable=False)
    amount = Column(Numeric(20, 8), nullable=False)
    avg_cost = Column(Numeric(20, 8))
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
