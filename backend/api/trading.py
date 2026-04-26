"""交易记录 API - 订单、持仓、成交"""
from fastapi import APIRouter, Query, Header, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from core.database import get_db
from core.security import decode_token
from models.user_preference import UserPreference
from models.watchlist import Watchlist
from models.bracket_track import BracketTrack
from services.broker_service import get_broker, get_mode
from services import simulated_mirror_service as _sms
from services.gate_account_service import (
    get_open_orders,
    get_finished_orders,
    get_my_trades,
    get_positions_with_value,
    cancel_order as gate_cancel_order,
    adjust_spot_amount_min_quote_usdt,
    create_spot_order,
    close_spot_symbol_flat,
)

router = APIRouter()


class CloseAllSymbolBody(BaseModel):
    """一键结束当前标的：撤销该交易对全部现货挂单 + 市价卖出基础币持仓，并取消本地止盈止损跟踪"""

    symbol: str = Field(..., description="如 BTC_USDT")


class SpotBracketOrderBody(BaseModel):
    """仪表盘快捷下单：现货限价/市价 + 可选止盈止损（成交后由后台跟踪平仓）"""

    symbol: str = Field(..., description="如 BTC_USDT")
    side: str = Field(..., description="buy 或 sell")
    order_type: str = Field("limit", description="limit 或 market")
    amount: str = Field(..., description="数量（基础币）")
    price: str | None = Field(None, description="限价必填；市价可空")
    stop_loss_price: str | None = None
    take_profit_price: str | None = None


class BracketTrackUpdateBody(BaseModel):
    """更新跟踪任务上的止盈/止损价（K 线拖动或前端改单后同步，成交后维护单按新价格改价）"""

    take_profit_price: str | None = None
    stop_loss_price: str | None = None


def _parse_px_bracket(s: str | None) -> float | None:
    if not s or not str(s).strip():
        return None
    try:
        x = float(str(s).strip().replace(",", ""))
        return x if x > 0 else None
    except ValueError:
        return None


def _bracket_entry_px(row: BracketTrack) -> float | None:
    for raw in (getattr(row, "entry_fill_price", None), row.price):
        p = _parse_px_bracket(raw if isinstance(raw, str) else (str(raw) if raw is not None else None))
        if p is not None:
            return p
    return None


def _validate_bracket_tp_sl(row: BracketTrack, tp: float | None, sl: float | None) -> str | None:
    """返回错误文案；通过返回 None。多单 buy：止损<入场<止盈；空单 sell：止盈<入场<止损"""
    entry = _bracket_entry_px(row)
    if entry is None:
        return "无法确定入场参考价，不能更新止盈/止损"
    side = (row.side or "").lower()
    if side == "buy":
        if tp is not None and tp <= entry:
            return "买方：止盈价须高于入场参考价"
        if sl is not None and sl >= entry:
            return "买方：止损价须低于入场参考价"
    elif side == "sell":
        if tp is not None and tp >= entry:
            return "卖方：止盈价须低于入场参考价"
        if sl is not None and sl <= entry:
            return "卖方：止损价须高于入场参考价"
    else:
        return "无效的入场方向"
    if tp is None and sl is None:
        return "请至少提供止盈或止损价格"
    return None


def get_current_user_id(authorization: str = Header(None)) -> int | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    payload = decode_token(authorization[7:])
    return int(payload["sub"]) if payload and payload.get("sub") else None


@router.get("/orders")
def get_orders(
    mode: str = Query(None),
    status: str = Query(None),
    symbol: str = Query(None),
    page: int = Query(1),
    size: int = Query(20),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": {"list": [], "total": 0}, "message": "请先登录", "code": 401}
    m = mode or get_mode(db, uid)
    # 模拟账户镜像：未成交=空；已成交=派生的回测交易
    if _sms.is_mirror_enabled(db, uid, m, "spot"):
        snap = _sms.build_snapshot(db, uid, "spot")
        if snap:
            if (status or "open").lower() == "open":
                return {"success": True, "data": {"list": [], "total": 0}, "message": "ok", "code": 200}
            lst = list(snap.get("orders") or [])
            if symbol:
                lst = [o for o in lst if str(o.get("symbol") or "").upper() == str(symbol).upper()]
            try:
                p, sz = max(1, int(page or 1)), max(1, int(size or 20))
            except (TypeError, ValueError):
                p, sz = 1, 20
            total = len(lst)
            lst = lst[(p - 1) * sz : p * sz]
            return {"success": True, "data": {"list": lst, "total": total}, "message": "ok", "code": 200}
    broker = get_broker(db, uid, m)
    if not broker:
        return {"success": True, "data": {"list": [], "total": 0}, "message": "ok", "code": 200}
    try:
        if status == "open" or not status:
            lst = get_open_orders(m, broker.api_key_enc, broker.api_secret_enc, page, size)
        else:
            symbols = [symbol] if symbol else [w.symbol for w in db.query(Watchlist).filter(Watchlist.user_id == uid).limit(20).all()]
            lst = get_finished_orders(m, broker.api_key_enc, broker.api_secret_enc, symbol, symbols, page, size)
        if symbol:
            lst = [o for o in lst if o.get("symbol") == symbol]
        total = len(lst)
        return {"success": True, "data": {"list": lst, "total": total}, "message": "ok", "code": 200}
    except Exception as e:
        return {"success": False, "data": {"list": [], "total": 0}, "message": str(e), "code": 500}


@router.get("/orders/{order_id}")
def get_order_detail(order_id: str, symbol: str = Query(None), authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    return {"success": True, "data": None, "message": "ok", "code": 200}


@router.post("/orders/cancel/{order_id}")
def cancel_order(order_id: str, symbol: str = Query(..., description="交易对如 BTC_USDT"), authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    m = get_mode(db, uid)
    broker = get_broker(db, uid, m)
    if not broker:
        return {"success": False, "data": None, "message": "未绑定交易所", "code": 400}
    try:
        ok = gate_cancel_order(m, broker.api_key_enc, broker.api_secret_enc, order_id, symbol)
        return {"success": ok, "data": None, "message": "撤单成功" if ok else "撤单失败", "code": 200}
    except Exception as e:
        return {"success": False, "data": None, "message": str(e), "code": 500}


@router.get("/positions")
def get_positions(mode: str = Query(None), authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": {"list": []}, "message": "请先登录", "code": 401}
    m = mode or get_mode(db, uid)
    # 模拟账户镜像：最后一个未平仓开仓事件转为持仓
    if _sms.is_mirror_enabled(db, uid, m, "spot"):
        snap = _sms.build_snapshot(db, uid, "spot")
        if snap:
            return {"success": True, "data": {"list": list(snap.get("positions") or [])}, "message": "ok", "code": 200}
    broker = get_broker(db, uid, m)
    if not broker:
        return {"success": True, "data": {"list": []}, "message": "ok", "code": 200}
    try:
        lst = get_positions_with_value(m, broker.api_key_enc, broker.api_secret_enc)
        return {"success": True, "data": {"list": lst}, "message": "ok", "code": 200}
    except Exception as e:
        return {"success": False, "data": {"list": []}, "message": str(e), "code": 500}


@router.post("/close-all-symbol")
def close_all_for_symbol(
    body: CloseAllSymbolBody,
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """
    一键平仓（现货）：撤销该标的全部未成交挂单，市价卖出该交易对基础币全部余额；
    并将本账户下该标的未结束的 BracketTrack 标记为 cancelled（停止后台维护）。
    """
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    m = get_mode(db, uid)
    broker = get_broker(db, uid, m)
    if not broker:
        return {"success": False, "data": None, "message": "未绑定当前模式下的 Gate.io 账户", "code": 400}

    sym = (body.symbol or "").strip().upper().replace("/", "_")
    if not sym or "_" not in sym:
        return {"success": False, "data": None, "message": "请传入有效交易对，如 BTC_USDT", "code": 400}

    try:
        gate_result = close_spot_symbol_flat(m, broker.api_key_enc, broker.api_secret_enc, sym)
    except Exception as e:
        return {"success": False, "data": None, "message": str(e), "code": 500}

    tracks = (
        db.query(BracketTrack)
        .filter(
            BracketTrack.user_id == uid,
            BracketTrack.mode == m,
            BracketTrack.symbol == sym,
            BracketTrack.status.in_(("pending_fill", "watching", "closing")),
        )
        .all()
    )
    n_cancelled_tracks = 0
    for r in tracks:
        r.status = "cancelled"
        if hasattr(r, "bracket_limit_order_id"):
            r.bracket_limit_order_id = None
        r.last_error = None
        n_cancelled_tracks += 1
    db.commit()

    sell = gate_result.get("market_sell") or {}
    sell_err = sell.get("error")
    # 无挂单可撤、无仓可平时仍视为成功
    ok = not sell_err
    msg_parts = [
        f"已撤 {len(gate_result.get('cancelled_order_ids') or [])} 笔挂单",
        "已取消止盈止损跟踪 %d 条" % n_cancelled_tracks,
    ]
    if sell.get("skipped"):
        msg_parts.append("无基础币可市价卖出")
    elif sell.get("order_id"):
        msg_parts.append("已提交市价卖单 %s" % sell["order_id"])
    if sell_err:
        msg_parts.append("市价卖出失败: %s" % sell_err)
    return {
        "success": ok,
        "data": {**gate_result, "cancelled_bracket_tracks": n_cancelled_tracks},
        "message": "；".join(msg_parts),
        "code": 200 if ok else 500,
    }


@router.post("/spot-bracket-order")
def place_spot_bracket_order(
    body: SpotBracketOrderBody,
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """现货下单；若填写止盈或止损，则创建跟踪任务（成交后按行情在止损/止盈限价之间维护平仓单）"""
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    m = get_mode(db, uid)
    broker = get_broker(db, uid, m)
    if not broker:
        return {"success": False, "data": None, "message": "未绑定当前模式下的 Gate.io 账户", "code": 400}

    sym = (body.symbol or "").strip().upper().replace("/", "_")
    side = (body.side or "").lower().strip()
    ot = (body.order_type or "limit").lower().strip()
    amt = (body.amount or "").strip()
    if not sym or side not in ("buy", "sell") or ot not in ("limit", "market") or not amt:
        return {"success": False, "data": None, "message": "参数无效：symbol、side(buy/sell)、order_type(limit/market)、amount 必填", "code": 400}
    if ot == "limit":
        pr = (body.price or "").strip()
        if not pr:
            return {"success": False, "data": None, "message": "限价单请填写委托价格", "code": 400}
    else:
        pr = (body.price or "").strip() or None

    sl = (body.stop_loss_price or "").strip() or None
    tp = (body.take_profit_price or "").strip() or None

    try:
        amt_exec, adj_note = adjust_spot_amount_min_quote_usdt(
            m, broker.api_key_enc, broker.api_secret_enc, sym, amt, ot, pr, side
        )
    except ValueError as ve:
        return {"success": False, "data": None, "message": str(ve), "code": 400}

    try:
        oid, raw = create_spot_order(m, broker.api_key_enc, broker.api_secret_enc, sym, side, ot, amt_exec, pr)
    except Exception as e:
        return {"success": False, "data": None, "message": str(e), "code": 500}

    track_id = None
    if sl or tp:
        row = BracketTrack(
            user_id=uid,
            mode=m,
            symbol=sym,
            side=side,
            order_type=ot,
            entry_order_id=str(oid) if oid is not None else "",
            amount=amt_exec,
            price=pr,
            stop_loss_price=sl,
            take_profit_price=tp,
            status="pending_fill",
        )
        if not row.entry_order_id:
            db.rollback()
            return {"success": False, "data": {"gate_response": raw}, "message": "下单成功但未返回订单号，无法启动止盈/止损跟踪", "code": 500}
        db.add(row)
        db.commit()
        db.refresh(row)
        track_id = row.id

    return {
        "success": True,
        "data": {
            "order_id": oid,
            "track_id": track_id,
            "symbol": sym,
            "amount_submitted": amt_exec,
            "gate_response": raw,
            "tracking": bool(sl or tp),
        },
        "message": "已提交"
        + ("（" + adj_note + "）" if adj_note else "")
        + ("，已启用止盈/止损跟踪" if (sl or tp) else ""),
        "code": 200,
    }


@router.get("/bracket-tracks")
def list_bracket_tracks(
    limit: int = Query(30, ge=1, le=100),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": {"list": []}, "message": "请先登录", "code": 401}
    rows = (
        db.query(BracketTrack)
        .filter(BracketTrack.user_id == uid)
        .order_by(BracketTrack.id.desc())
        .limit(limit)
        .all()
    )
    lst = []
    for r in rows:
        ca = r.created_at
        ca_iso = ca.isoformat() if ca is not None else None
        lst.append(
            {
                "id": r.id,
                "symbol": r.symbol,
                "side": r.side,
                "order_type": r.order_type,
                "status": r.status,
                "entry_order_id": r.entry_order_id,
                "amount": r.amount,
                "filled_amount": r.filled_amount,
                "price": r.price,
                "stop_loss_price": r.stop_loss_price,
                "take_profit_price": r.take_profit_price,
                "entry_fill_price": getattr(r, "entry_fill_price", None),
                "bracket_limit_order_id": getattr(r, "bracket_limit_order_id", None),
                "close_order_id": r.close_order_id,
                "last_error": r.last_error,
                "mode": r.mode,
                "created_at": ca_iso,
            }
        )
    return {"success": True, "data": {"list": lst}, "message": "ok", "code": 200}


@router.patch("/bracket-tracks/{track_id}")
def patch_bracket_track(
    track_id: int,
    body: BracketTrackUpdateBody,
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    row = db.query(BracketTrack).filter(BracketTrack.id == track_id, BracketTrack.user_id == uid).first()
    if not row:
        return {"success": False, "data": None, "message": "记录不存在", "code": 404}
    st = (row.status or "").lower()
    if st not in ("pending_fill", "watching"):
        return {"success": False, "data": None, "message": "仅待成交或监控中的跟踪可修改止盈/止损", "code": 400}

    tp_new = (body.take_profit_price or "").strip() or None
    sl_new = (body.stop_loss_price or "").strip() or None
    if tp_new is None and sl_new is None:
        return {"success": False, "data": None, "message": "请提供 take_profit_price 或 stop_loss_price", "code": 400}

    tp_f = _parse_px_bracket(row.take_profit_price)
    sl_f = _parse_px_bracket(row.stop_loss_price)
    if tp_new is not None:
        tp_f = _parse_px_bracket(tp_new)
        if tp_f is None:
            return {"success": False, "data": None, "message": "止盈价格式无效", "code": 400}
    if sl_new is not None:
        sl_f = _parse_px_bracket(sl_new)
        if sl_f is None:
            return {"success": False, "data": None, "message": "止损价格式无效", "code": 400}

    err = _validate_bracket_tp_sl(row, tp_f, sl_f)
    if err:
        return {"success": False, "data": None, "message": err, "code": 400}

    if tp_new is not None:
        row.take_profit_price = tp_new
    if sl_new is not None:
        row.stop_loss_price = sl_new
    row.last_error = None
    db.commit()
    db.refresh(row)
    return {
        "success": True,
        "data": {
            "id": row.id,
            "take_profit_price": row.take_profit_price,
            "stop_loss_price": row.stop_loss_price,
        },
        "message": "已更新止盈/止损，挂单将由后台按新价格维护",
        "code": 200,
    }


@router.get("/trades")
def get_trades(
    mode: str = Query(None),
    symbol: str = Query(None),
    page: int = Query(1),
    size: int = Query(20),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": {"list": [], "total": 0}, "message": "请先登录", "code": 401}
    m = mode or get_mode(db, uid)
    # 模拟账户镜像：返回派生的成交流水
    if _sms.is_mirror_enabled(db, uid, m, "spot"):
        snap = _sms.build_snapshot(db, uid, "spot")
        if snap:
            lst = list(snap.get("trades") or [])
            if symbol:
                lst = [t for t in lst if str(t.get("symbol") or "").upper() == str(symbol).upper()]
            try:
                p, sz = max(1, int(page or 1)), max(1, int(size or 20))
            except (TypeError, ValueError):
                p, sz = 1, 20
            total = len(lst)
            lst = lst[(p - 1) * sz : p * sz]
            return {"success": True, "data": {"list": lst, "total": total}, "message": "ok", "code": 200}
    broker = get_broker(db, uid, m)
    if not broker:
        return {"success": True, "data": {"list": [], "total": 0}, "message": "ok", "code": 200}
    try:
        lst = get_my_trades(m, broker.api_key_enc, broker.api_secret_enc, symbol, page, size)
        return {"success": True, "data": {"list": lst, "total": len(lst)}, "message": "ok", "code": 200}
    except Exception as e:
        return {"success": False, "data": {"list": [], "total": 0}, "message": str(e), "code": 500}
