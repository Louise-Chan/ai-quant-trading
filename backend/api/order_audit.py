"""订单审核：DeepSeek 生成、列表、通过（下单）、不通过"""
import json
from fastapi import APIRouter, Body, Header, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.database import get_db
from core.security import decode_token
from models.order_audit import OrderAudit
from services.broker_service import get_broker, get_mode
from gate_api.exceptions import ApiException, GateApiException

from services.gate_account_service import adjust_spot_amount_min_quote_usdt, create_spot_order
from services.order_audit_service import (
    audit_to_api_dict,
    build_audit_context,
    create_pending_audit,
    run_deepseek_audit,
)
from datetime import datetime, timezone

from models.custody_trade_log import CustodyTradeLog
from models.subscription import Subscription
from models.user_strategy import UserStrategy
from services.preference_extra import get_deepseek_api_key, get_dashboard_trading, patch_dashboard_trading
from services.risk_settings_memory import risk_settings_for_user
from services.strategy_engine.runner import analyze_symbol
from utils.gate_client import list_candlesticks
from services.gate_account_service import get_total_balance_usdt

router = APIRouter()


def get_current_user_id(authorization: str = Header(None)) -> int | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    payload = decode_token(authorization[7:])
    return int(payload["sub"]) if payload and payload.get("sub") else None


class ApproveAuditBody(BaseModel):
    """用户通过前可修改委托价、止损/止盈（落库便于核对与后续跟踪展示）、订单类型"""

    price: str | None = Field(None, description="委托价格；市价单可为空字符串")
    stop_loss_price: str | None = Field(None, description="止损价")
    take_profit_price: str | None = Field(None, description="止盈价")
    order_type: str | None = Field(None, description="limit 或 market")


def _custody_executed_today_count(db: Session, uid: int) -> int:
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        db.query(CustodyTradeLog)
        .filter(
            CustodyTradeLog.user_id == uid,
            CustodyTradeLog.status == "executed",
            CustodyTradeLog.created_at >= start,
        )
        .count()
    )


class CustodySettingsBody(BaseModel):
    custody_max_opens_per_day: int = Field(0, ge=0, le=9999)


class GenerateAuditBody(BaseModel):
    symbol: str = Field(..., description="交易对，如 BTC_USDT")
    signal: dict | None = Field(None, description="策略信号：方向、强度、原因等")
    mode: str | None = None
    use_strategy_engine: bool = Field(False, description="为 True 时拉取 K 线并运行多因子/ML/回测/仓位引擎，结果写入 signal.strategy_engine")
    interval: str = Field("1h", description="K 线周期，如 1h、4h、1d")
    quote_market: str | None = Field(None, description="spot | futures，标的类型，写入 signal 供审核条展示")


@router.post("/generate")
def generate_audit(body: GenerateAuditBody, authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    api_key = get_deepseek_api_key(db, uid)
    if not api_key:
        return {"success": False, "data": None, "message": "请先在设置中绑定 DeepSeek API Key", "code": 400}

    m = body.mode or get_mode(db, uid)
    signal = dict(body.signal) if body.signal else {}
    if body.quote_market:
        signal.setdefault("quote_market", str(body.quote_market).strip())
    if body.use_strategy_engine:
        sym = body.symbol.strip()
        candles = list_candlesticks(sym, body.interval or "1h", limit=320, mode=m)
        risk = risk_settings_for_user(uid, m)
        total_usdt = None
        broker = get_broker(db, uid, m)
        if broker:
            try:
                _, _, total_usdt = get_total_balance_usdt(m, broker.api_key_enc, broker.api_secret_enc)
            except Exception:
                pass
        engine_pkg = analyze_symbol(sym, candles, risk, interval=body.interval or "1h", total_usdt=total_usdt)
        if not engine_pkg.get("ok"):
            return {
                "success": False,
                "data": engine_pkg,
                "message": engine_pkg.get("error") or "策略引擎未产出有效信号",
                "code": 400,
            }
        signal["strategy_engine"] = engine_pkg

    ctx = build_audit_context(db, uid, m, body.symbol.strip(), signal if signal else None)
    try:
        parsed, raw = run_deepseek_audit(api_key, ctx)
    except Exception as e:
        return {"success": False, "data": None, "message": str(e), "code": 500}

    row = create_pending_audit(db, uid, m, ctx, parsed, raw)
    return {"success": True, "data": audit_to_api_dict(row), "message": "ok", "code": 200}


@router.post("/custody/start")
def custody_start(authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    st = get_dashboard_trading(db, uid)
    sid = st.get("active_subscription_id")
    if not sid:
        return {
            "success": False,
            "data": None,
            "message": "请先在策略中心选择要运行的订阅，再回到仪表盘开启托管",
            "code": 400,
        }
    sub = db.query(Subscription).filter(Subscription.id == int(sid), Subscription.user_id == uid).first()
    if not sub or sub.status != "active":
        return {"success": False, "data": None, "message": "当前选中的订阅无效", "code": 400}
    if not sub.user_strategy_id:
        return {
            "success": False,
            "data": None,
            "message": "托管跟单仅支持「用户保存策略」的订阅，请在策略中心订阅回测保存的策略",
            "code": 400,
        }
    us = db.query(UserStrategy).filter(UserStrategy.id == sub.user_strategy_id, UserStrategy.user_id == uid).first()
    if not us or us.status != "active":
        return {"success": False, "data": None, "message": "用户策略不存在或已删除", "code": 400}
    patch_dashboard_trading(db, uid, custody_running=True)
    st2 = get_dashboard_trading(db, uid)
    return {"success": True, "data": st2, "message": "托管跟单已开启（不经人工审核自动下单）", "code": 200}


@router.post("/custody/stop")
def custody_stop(authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    patch_dashboard_trading(db, uid, custody_running=False)
    st = get_dashboard_trading(db, uid)
    return {"success": True, "data": st, "message": "已停止托管跟单", "code": 200}


@router.put("/custody/settings")
def custody_put_settings(body: CustodySettingsBody, authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    patch_dashboard_trading(db, uid, custody_max_opens_per_day=body.custody_max_opens_per_day)
    st = get_dashboard_trading(db, uid)
    st["custody_executed_today"] = _custody_executed_today_count(db, uid)
    return {"success": True, "data": st, "message": "已保存", "code": 200}


@router.get("/custody/status")
def custody_status(authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    st = get_dashboard_trading(db, uid)
    st["custody_executed_today"] = _custody_executed_today_count(db, uid)
    return {"success": True, "data": st, "message": "ok", "code": 200}


@router.get("/list")
def list_audits(
    status: str = Query(None),
    limit: int = Query(80, ge=1, le=200),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": {"list": []}, "message": "请先登录", "code": 401}
    q = db.query(OrderAudit).filter(OrderAudit.user_id == uid)
    if status:
        q = q.filter(OrderAudit.status == status)
    rows = q.order_by(OrderAudit.id.asc()).limit(limit).all()
    return {"success": True, "data": {"list": [audit_to_api_dict(r) for r in rows]}, "message": "ok", "code": 200}


def _merge_approve_overrides(audited: dict, body: ApproveAuditBody | None) -> dict:
    """将用户提交的字段合并进审核单（空字符串的止损/止盈视为清空）"""
    out = dict(audited)
    if not body:
        return out
    if body.order_type is not None and str(body.order_type).strip():
        ot = str(body.order_type).strip().lower()
        if ot in ("limit", "market"):
            out["order_type"] = ot
    if body.price is not None:
        out["price"] = str(body.price).strip()
    if body.stop_loss_price is not None:
        s = str(body.stop_loss_price).strip()
        out["stop_loss_price"] = s if s else None
    if body.take_profit_price is not None:
        s = str(body.take_profit_price).strip()
        out["take_profit_price"] = s if s else None
    return out


@router.post("/{audit_id}/approve")
def approve_audit(
    audit_id: int,
    body: ApproveAuditBody | None = Body(default=None),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    row = db.query(OrderAudit).filter(OrderAudit.id == audit_id, OrderAudit.user_id == uid).first()
    if not row:
        return {"success": False, "data": None, "message": "记录不存在", "code": 404}
    if row.status != "pending":
        return {"success": False, "data": None, "message": f"当前状态不可执行: {row.status}", "code": 400}

    try:
        audited = json.loads(row.audited_order_json or "{}")
    except Exception:
        audited = {}

    audited = _merge_approve_overrides(audited, body)

    symbol = audited.get("symbol") or ""
    side = (audited.get("side") or "").lower()
    order_type = (audited.get("order_type") or "limit").lower()
    amount = audited.get("amount")
    price = audited.get("price")

    if not symbol or side not in ("buy", "sell"):
        row.status = "failed"
        row.error_message = "审核单缺少 symbol 或 side"
        db.commit()
        return {"success": False, "data": audit_to_api_dict(row), "message": row.error_message, "code": 400}

    if amount is None or str(amount).strip() == "":
        row.status = "failed"
        row.error_message = "审核单缺少 amount"
        db.commit()
        return {"success": False, "data": audit_to_api_dict(row), "message": row.error_message, "code": 400}

    if order_type == "limit":
        if price is None or str(price).strip() == "":
            row.status = "failed"
            row.error_message = "限价单缺少 price"
            db.commit()
            return {"success": False, "data": audit_to_api_dict(row), "message": row.error_message, "code": 400}

    broker = get_broker(db, uid, row.mode)
    if not broker:
        row.status = "failed"
        row.error_message = "未绑定当前模式下的 Gate.io 账户"
        db.commit()
        return {"success": False, "data": audit_to_api_dict(row), "message": row.error_message, "code": 400}

    p = str(price).strip() if price is not None else None
    if order_type == "market":
        p = None if not p else p

    amt_raw = str(amount).strip()
    try:
        amt_exec, adj_note = adjust_spot_amount_min_quote_usdt(
            row.mode,
            broker.api_key_enc,
            broker.api_secret_enc,
            symbol,
            amt_raw,
            order_type,
            p,
            side,
        )
    except ValueError as ve:
        row.status = "failed"
        row.error_message = str(ve)[:2000]
        db.commit()
        return {"success": False, "data": audit_to_api_dict(row), "message": str(ve), "code": 400}

    if adj_note:
        audited["amount"] = amt_exec

    try:
        oid, raw = create_spot_order(
            row.mode,
            broker.api_key_enc,
            broker.api_secret_enc,
            symbol,
            side,
            order_type,
            amt_exec,
            p,
        )
        row.status = "executed"
        row.exchange_order_id = str(oid) if oid is not None else None
        row.error_message = None
        # 保存用户最终确认的字段（含止损/止盈备注，便于列表展示与后续扩展「跟踪」）
        row.audited_order_json = json.dumps(audited, ensure_ascii=False)
        db.commit()
        msg_ok = "已提交交易所"
        if adj_note:
            msg_ok = msg_ok + "（" + adj_note + "）"
        return {
            "success": True,
            "data": {**audit_to_api_dict(row), "gate_response": raw},
            "message": msg_ok,
            "code": 200,
        }
    except (ApiException, GateApiException) as e:
        row.status = "failed"
        em = str(e)
        row.error_message = em[:2000]
        db.commit()
        http_code = getattr(e, "status", None)
        code = http_code if http_code in (400, 401, 403, 404) else 500
        msg = em
        low = em.lower()
        if "too small" in low or "invalid_param" in low or "minimum" in low:
            msg = (
                "订单金额低于 Gate 要求（现货单笔成交额通常需 ≥ 约 3 USDT）。"
                " 系统已尝试自动调高数量；若仍失败请检查交易对精度、余额，或在审核单中改大数量后重新生成审核。"
            )
        return {"success": False, "data": audit_to_api_dict(row), "message": msg, "code": code}
    except Exception as e:
        row.status = "failed"
        row.error_message = str(e)[:2000]
        db.commit()
        return {"success": False, "data": audit_to_api_dict(row), "message": str(e), "code": 500}


@router.post("/{audit_id}/reject")
def reject_audit(audit_id: int, authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    row = db.query(OrderAudit).filter(OrderAudit.id == audit_id, OrderAudit.user_id == uid).first()
    if not row:
        return {"success": False, "data": None, "message": "记录不存在", "code": 404}
    if row.status != "pending":
        return {"success": False, "data": audit_to_api_dict(row), "message": f"当前状态不可拒绝: {row.status}", "code": 400}
    row.status = "rejected"
    db.commit()
    return {"success": True, "data": audit_to_api_dict(row), "message": "已拒绝", "code": 200}
