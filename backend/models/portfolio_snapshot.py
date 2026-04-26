"""净值快照模型"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Numeric, Date
from sqlalchemy.sql import func
from core.database import Base


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    nav = Column(Numeric(20, 4), nullable=False)
    total_return = Column(Numeric(10, 4))
    date = Column(Date, nullable=False)
    mode = Column(String(16), default="real")
    # spot | futures — 与现货/合约账户净值分别记账
    account_scope = Column(String(16), default="spot", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
