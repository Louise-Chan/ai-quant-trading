"""订单模型"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Numeric
from sqlalchemy.sql import func
from core.database import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    broker_id = Column(Integer, ForeignKey("broker_accounts.id"), nullable=False)
    symbol = Column(String(32), nullable=False)
    side = Column(String(8), nullable=False)  # buy | sell
    price = Column(Numeric(20, 8))
    amount = Column(Numeric(20, 8), nullable=False)
    status = Column(String(16), default="open")  # open | closed | cancelled
    order_id_exchange = Column(String(64))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
