"""现货快捷下单后的止盈/止损跟踪（成交后挂限价平仓单，按现价相对开仓价在止损/止盈价之间改单）"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from core.database import Base


class BracketTrack(Base):
    __tablename__ = "bracket_tracks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    mode = Column(String(16), nullable=False)  # real | simulated
    symbol = Column(String(32), nullable=False, index=True)
    side = Column(String(8), nullable=False)  # buy | sell 入场方向
    order_type = Column(String(16), nullable=False)  # limit | market
    entry_order_id = Column(String(64), nullable=False, index=True)
    amount = Column(String(32), nullable=False)  # 下单数量（基础币）
    price = Column(String(32), nullable=True)
    stop_loss_price = Column(String(32), nullable=True)
    take_profit_price = Column(String(32), nullable=True)
    # pending_fill: 等待入场单成交 | watching: 已成交，监控 TP/SL | closing: 正在下平仓单 | closed | cancelled | failed
    status = Column(String(24), nullable=False, default="pending_fill", index=True)
    filled_amount = Column(String(32), nullable=True)  # 实际成交基础币数量（用于平仓）
    # 成交均价（入场），用于与现价比较以决定挂止损价还是止盈价
    entry_fill_price = Column(String(32), nullable=True)
    # 当前维护中的限价平仓单（卖平多 / 买平空），在止损价与止盈价之间改价
    bracket_limit_order_id = Column(String(64), nullable=True, index=True)
    close_order_id = Column(String(64), nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
