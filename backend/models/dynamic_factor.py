"""用户动态因子：由 DeepSeek 生成表达式后持久化；按评估结果激活/淘汰"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from core.database import Base


class DynamicFactor(Base):
    __tablename__ = "dynamic_factors"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # 动态因子对前端而言的唯一标识（字符串 id），避免与静态因子 id 冲突
    factor_id = Column(String(128), nullable=False, index=True)
    name = Column(String(128), nullable=True)
    description = Column(Text, nullable=True)

    # DSL 表达式（仅允许白名单函数/变量；由执行器安全校验）
    expression_dsl = Column(Text, nullable=False)

    # 激活状态：active=True 的会出现在 /factor-library；active=False 会从前端消失
    active = Column(Boolean, default=True, index=True, nullable=False)

    # 最近一次评估分数/指标（score 数值用于排序；metrics_json 用于调试/解释）
    score = Column(Float, default=0.0, nullable=False)
    metrics_json = Column(Text, nullable=True)
    invalid_reason = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_eval_at = Column(DateTime(timezone=True), nullable=True)

    def factor_key(self) -> str:
        """前端因子库 id：带前缀，避免与系统因子 id 冲突"""
        return f"dyn_{self.id}"

