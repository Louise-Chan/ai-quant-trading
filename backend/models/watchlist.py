"""自选币模型"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func
from core.database import Base


class Watchlist(Base):
    __tablename__ = "watchlist"
    __table_args__ = (UniqueConstraint("user_id", "symbol", "quote_market", name="uq_watchlist_user_symbol_market"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    symbol = Column(String(32), nullable=False)
    # spot | futures — 同一交易对可同时自选现货与合约
    quote_market = Column(String(16), default="spot", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
