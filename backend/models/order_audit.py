"""待审核订单（DeepSeek Agent 输出 + 用户通过/拒绝）"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from core.database import Base


class OrderAudit(Base):
    __tablename__ = "order_audits"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    mode = Column(String(16), nullable=False)  # real | simulated
    # pending | rejected | executed | failed （通过后执行；不通过为 rejected）
    status = Column(String(16), default="pending", index=True)
    context_json = Column(Text)  # 策略信号、组合、风控等输入快照
    audited_order_json = Column(Text)  # Agent 建议执行的订单（可改价改量）
    agent_reason = Column(Text)
    confidence = Column(String(16))  # high | medium | low
    raw_agent_response = Column(Text, nullable=True)
    exchange_order_id = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
