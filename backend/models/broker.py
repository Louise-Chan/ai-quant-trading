"""交易所绑定模型"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from core.database import Base


class BrokerAccount(Base):
    __tablename__ = "broker_accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    mode = Column(String(16), nullable=False)  # real | simulated
    api_key_enc = Column(String(512), nullable=False)
    api_secret_enc = Column(String(512), nullable=False)
    exchange = Column(String(32), default="gateio")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
