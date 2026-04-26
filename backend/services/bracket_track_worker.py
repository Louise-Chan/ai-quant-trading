"""后台轮询：入场单成交后维护单笔限价平仓单，按现价相对开仓价在止损价与止盈价之间改单"""
from __future__ import annotations

import time
import threading

from sqlalchemy.orm import Session

from core.database import SessionLocal
from models.bracket_track import BracketTrack
from services.broker_service import get_broker
from services.gate_account_service import (
    amend_spot_order_price,
    cancel_order,
    create_spot_order,
    get_spot_order,
)
from utils.gate_client import get_spot_ticker_last


def _fmt_amount(x: float) -> str:
    s = f"{x:.10f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _fmt_price(x: float) -> str:
    s = f"{x:.12f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _parse_px(s: str | None) -> float | None:
    if not s or not str(s).strip():
        return None
    try:
        return float(str(s).strip())
    except ValueError:
        return None


def _px_close(a: float, b: float) -> bool:
    tol = max(1e-12, abs(a) * 1e-9, abs(b) * 1e-9)
    return abs(a - b) <= tol


def _ensure_entry_fill_price(row: BracketTrack, key: str, sec: str) -> float | None:
    p = _parse_px(row.entry_fill_price)
    if p is not None:
        return p
    od = get_spot_order(row.mode, key, sec, row.entry_order_id, row.symbol)
    if not od:
        return None
    adp = od.get("avg_deal_price")
    if adp is not None and str(adp).strip():
        row.entry_fill_price = str(adp).strip()
        return _parse_px(row.entry_fill_price)
    lp = od.get("price")
    if lp is not None and str(lp).strip():
        row.entry_fill_price = str(lp).strip()
        return _parse_px(row.entry_fill_price)
    if row.price and str(row.price).strip():
        row.entry_fill_price = str(row.price).strip()
        return _parse_px(row.entry_fill_price)
    return None


def _desired_exit_limit_price(row: BracketTrack, last: float) -> float | None:
    """
    多单：现价 < 开仓价 -> 止损价限价卖；现价 > 开仓价 -> 止盈价限价卖。
    空单：现价 > 开仓价 -> 止损价限价买；现价 < 开仓价 -> 止盈价限价买。
    现价 == 开仓价 时按止损侧处理。
    """
    entry = _parse_px(row.entry_fill_price)
    if entry is None:
        return None
    sl = _parse_px(row.stop_loss_price)
    tp = _parse_px(row.take_profit_price)
    side = (row.side or "").lower()
    if side == "buy":
        if last < entry:
            return sl
        if last > entry:
            return tp
        return sl
    if side == "sell":
        if last > entry:
            return sl
        if last < entry:
            return tp
        return sl
    return None


def _process_row(db: Session, row: BracketTrack) -> None:
    broker = get_broker(db, row.user_id, row.mode)
    if not broker:
        row.last_error = "未绑定 Gate 账户"
        row.status = "failed"
        return

    key, sec = broker.api_key_enc, broker.api_secret_enc

    if row.status == "pending_fill":
        od = get_spot_order(row.mode, key, sec, row.entry_order_id, row.symbol)
        if not od:
            return
        st = (od.get("status") or "").lower()
        filled_base = float(od.get("filled_base") or 0)
        if st == "open":
            return
        if filled_base > 1e-12:
            row.filled_amount = _fmt_amount(filled_base)
            adp = od.get("avg_deal_price")
            if adp is not None and str(adp).strip():
                row.entry_fill_price = str(adp).strip()
            elif row.price and str(row.price).strip():
                row.entry_fill_price = str(row.price).strip()
            row.status = "watching"
            row.last_error = None
            row.bracket_limit_order_id = None
            return
        if st == "cancelled":
            row.status = "cancelled"
        else:
            row.status = "closed"
            row.last_error = "订单结束且无成交，未启动止盈/止损"
        return

    if row.status == "closing":
        amt = (row.filled_amount or row.amount or "").strip()
        if not amt:
            row.status = "failed"
            row.last_error = "平仓数量为空"
            return
        close_side = "sell" if row.side == "buy" else "buy"
        try:
            oid, _raw = create_spot_order(row.mode, key, sec, row.symbol, close_side, "market", amt, None)
            row.close_order_id = str(oid) if oid is not None else None
            row.status = "closed"
            row.last_error = None
        except Exception as e:
            row.last_error = str(e)[:2000]
        return

    if row.status == "watching":
        sl = _parse_px(row.stop_loss_price)
        tp = _parse_px(row.take_profit_price)
        if sl is None and tp is None:
            row.status = "closed"
            row.last_error = "未设置止盈/止损，停止跟踪"
            return

        last = get_spot_ticker_last(row.mode, row.symbol)
        if last is None:
            return

        entry = _ensure_entry_fill_price(row, key, sec)
        if entry is None:
            row.last_error = "无法确定开仓均价，无法切换止损/止盈限价"
            return

        target_px = _desired_exit_limit_price(row, last)
        amt = (row.filled_amount or row.amount or "").strip()
        if not amt:
            row.status = "failed"
            row.last_error = "平仓数量为空"
            return

        close_side = "sell" if row.side == "buy" else "buy"
        bid = (row.bracket_limit_order_id or "").strip()

        if bid:
            pod = get_spot_order(row.mode, key, sec, bid, row.symbol)
            if not pod:
                row.bracket_limit_order_id = None
                bid = ""
            else:
                pst = (pod.get("status") or "").lower()
                fa = float(pod.get("filled_base") or 0)
                if pst == "closed" and fa > 1e-12:
                    row.close_order_id = bid
                    row.bracket_limit_order_id = None
                    row.status = "closed"
                    row.last_error = None
                    return
                if pst == "cancelled":
                    row.bracket_limit_order_id = None
                    bid = ""
                elif pst == "open":
                    pass
                else:
                    row.bracket_limit_order_id = None
                    bid = ""

        if target_px is None:
            if bid:
                try:
                    cancel_order(row.mode, key, sec, bid, row.symbol)
                except Exception:
                    pass
                row.bracket_limit_order_id = None
            row.last_error = None
            return

        price_s = _fmt_price(target_px)

        if bid:
            cur_p = _parse_px(str(pod.get("price") or "")) if pod else None
            if cur_p is not None and _px_close(cur_p, target_px):
                row.last_error = None
                return
            try:
                amend_spot_order_price(row.mode, key, sec, bid, row.symbol, price_s)
                row.last_error = None
            except Exception as e:
                row.last_error = str(e)[:2000]
            return

        try:
            oid, _raw = create_spot_order(
                row.mode, key, sec, row.symbol, close_side, "limit", amt, price_s
            )
            row.bracket_limit_order_id = str(oid) if oid is not None else None
            row.last_error = None
        except Exception as e:
            row.last_error = str(e)[:2000]
        return


def process_bracket_tracks_once() -> None:
    db = SessionLocal()
    try:
        rows = (
            db.query(BracketTrack)
            .filter(BracketTrack.status.in_(("pending_fill", "watching", "closing")))
            .order_by(BracketTrack.id.asc())
            .limit(200)
            .all()
        )
        for row in rows:
            try:
                _process_row(db, row)
                db.commit()
            except Exception as e:
                db.rollback()
                try:
                    row2 = db.query(BracketTrack).filter(BracketTrack.id == row.id).first()
                    if row2:
                        row2.last_error = str(e)[:2000]
                        db.commit()
                except Exception:
                    db.rollback()
    finally:
        db.close()


def start_bracket_track_worker(interval_sec: float = 2.5) -> None:
    def _loop():
        while True:
            try:
                process_bracket_tracks_once()
            except Exception as ex:
                print(f"[bracket_track_worker] {ex}")
            time.sleep(interval_sec)

    t = threading.Thread(target=_loop, name="bracket-track-worker", daemon=True)
    t.start()
