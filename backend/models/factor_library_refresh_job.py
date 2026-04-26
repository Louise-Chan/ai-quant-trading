"""因子库刷新作业：异步挖掘/评估/淘汰/更新"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from core.database import Base


class FactorLibraryRefreshJob(Base):
    __tablename__ = "factor_library_refresh_jobs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # pending | running | done | failed
    status = Column(String(16), default="pending", index=True, nullable=False)

    # 刷新参数快照（candidate_count、interval、策略约束等）
    params_json = Column(Text, nullable=True)

    # 结果快照：added/removed/top_factors 等（JSON 字符串）
    result_json = Column(Text, nullable=True)

    # 给前端展示的简明中文通知文案
    user_message = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

