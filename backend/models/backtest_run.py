"""回测运行记录（可视化回测页每次成功运行后持久化，便于重开软件查看历史）"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from core.database import Base


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # 关联保存的策略（可空：未保存策略直接跑也允许）
    user_strategy_id = Column(Integer, ForeignKey("user_strategies.id"), nullable=True, index=True)
    name = Column(String(200), nullable=True)  # 展示名（载入时策略名 + 时间）
    interval = Column(String(16), nullable=True)
    symbols_json = Column(Text, nullable=True)  # list[str]
    factors_json = Column(Text, nullable=True)  # list[str]
    range_json = Column(Text, nullable=True)  # { mode, start_date, end_date, from_ts, to_ts, bars_limit }
    summary_json = Column(Text, nullable=True)  # compactBacktestSummary 级别的摘要
    result_json = Column(Text, nullable=True)  # /strategy-engine/backtest-visual 完整 data（含开/平仓事件）
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
