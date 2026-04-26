"""资产净值 API"""
from fastapi import APIRouter, Query, Header, Depends
from sqlalchemy.orm import Session
from sqlalchemy import desc
from core.database import get_db
from core.security import decode_token
from models.broker import BrokerAccount
from models.portfolio_snapshot import PortfolioSnapshot
from services.broker_service import get_broker, get_mode, _parse_gate_error
from services.gate_account_service import get_futures_usdt_total_balance, get_total_balance_usdt
from services import simulated_mirror_service as _sms

router = APIRouter()


def get_current_user_id(authorization: str = Header(None)) -> int | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    payload = decode_token(authorization[7:])
    return int(payload["sub"]) if payload and payload.get("sub") else None


def _normalize_account_scope(raw: str | None) -> str:
    s = (raw or "spot").strip().lower()
    if s in ("futures", "futures_usdt", "contract", "合约"):
        return "futures"
    return "spot"


def _pick_mode_with_binding(db: Session, user_id: int, preferred_mode: str) -> str:
    """
    若当前模式未绑定，则自动回退到另一已绑定模式，避免前端出现全 --。
    """
    pm = (preferred_mode or "simulated").strip().lower()
    if pm not in ("real", "simulated"):
        pm = "simulated"
    if db.query(BrokerAccount).filter(BrokerAccount.user_id == user_id, BrokerAccount.mode == pm).first():
        return pm
    alt = "simulated" if pm == "real" else "real"
    if db.query(BrokerAccount).filter(BrokerAccount.user_id == user_id, BrokerAccount.mode == alt).first():
        return alt
    return pm


@router.get("/balance")
def get_balance(
    mode: str = Query(None),
    account_scope: str = Query("spot", description="spot 现货 | futures U本位合约"),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    m = mode or get_mode(db, uid)
    scope = _normalize_account_scope(account_scope)
    # 模拟账户镜像：资产净值 = 当前净值；可用 = 当前净值 - 在仓市值
    if _sms.is_mirror_enabled(db, uid, m, scope):
        snap = _sms.build_snapshot(db, uid, scope)
        if snap and snap.get("summary"):
            s = snap["summary"]
            current_nav = float(s.get("current_nav") or 0)
            pos = snap.get("positions") or []
            locked = 0.0
            for p in pos:
                try:
                    locked += float(p.get("value_usdt") or 0)
                except (TypeError, ValueError):
                    continue
            avail = max(0.0, current_nav - locked)
            data = {
                "available": round(avail, 4),
                "frozen": round(locked, 4),
                "total": round(current_nav, 4),
                "today_pnl": None,
                "data_source": "simulated_mirror",
                "account_scope": scope,
            }
            return {"success": True, "data": data, "message": "ok", "code": 200}
    m = _pick_mode_with_binding(db, uid, m)
    broker = get_broker(db, uid, m)
    if broker:
        try:
            if scope == "futures":
                avail, frozen, total = get_futures_usdt_total_balance(m, broker.api_key_enc, broker.api_secret_enc)
                used_scope = "futures"
            else:
                avail, frozen, total = get_total_balance_usdt(m, broker.api_key_enc, broker.api_secret_enc)
                used_scope = "spot"
            data = {
                "available": round(avail, 4),
                "frozen": round(frozen, 4),
                "total": round(total, 4),
                "today_pnl": None,  # 暂无收益时显示 --
                "data_source": "gate",
                "account_scope": used_scope,
            }
            return {"success": True, "data": data, "message": "ok", "code": 200}
        except Exception as e:
            # 若合约资产不可用，自动回退现货资产
            if scope == "futures":
                try:
                    av2, fr2, to2 = get_total_balance_usdt(m, broker.api_key_enc, broker.api_secret_enc)
                    data = {
                        "available": round(av2, 4),
                        "frozen": round(fr2, 4),
                        "total": round(to2, 4),
                        "today_pnl": None,
                        "data_source": "gate_spot_fallback",
                        "account_scope": "spot",
                    }
                    return {
                        "success": True,
                        "data": data,
                        "message": f"合约资产暂不可用，已回退现货资产：{_parse_gate_error(e)}",
                        "code": 200,
                    }
                except Exception:
                    pass
            # Gate 失败时回退最近净值快照，至少给前端可用数值
            snap = (
                db.query(PortfolioSnapshot)
                .filter(PortfolioSnapshot.user_id == uid, PortfolioSnapshot.account_scope == scope)
                .order_by(desc(PortfolioSnapshot.date), desc(PortfolioSnapshot.id))
                .first()
            )
            if snap:
                total = float(snap.nav)
                data = {
                    "available": round(total, 4),
                    "frozen": 0.0,
                    "total": round(total, 4),
                    "today_pnl": None,
                    "data_source": "snapshot",
                    "account_scope": scope,
                }
                return {
                    "success": True,
                    "data": data,
                    "message": f"Gate暂不可用，已回退最近快照：{_parse_gate_error(e)}",
                    "code": 200,
                }
            return {"success": False, "data": None, "message": _parse_gate_error(e), "code": 500}
    # 未绑定交易所时返回 null，前端用 -- 展示
    data = {"available": None, "frozen": None, "total": None, "today_pnl": None}
    return {"success": True, "data": data, "message": "未绑定交易所，请先绑定 Gate.io 模拟 API", "code": 200}
