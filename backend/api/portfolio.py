"""投资组合 API - 真实初始资金来自 Gate 首次余额，收益按此计算，无收益时显示 --"""
from datetime import date
from fastapi import APIRouter, Query, Header, Depends
from sqlalchemy.orm import Session
from sqlalchemy import asc, desc
from core.database import get_db
from core.security import decode_token
from models.portfolio_snapshot import PortfolioSnapshot
from models.broker import BrokerAccount
from services.broker_service import get_broker, get_mode, _parse_gate_error
from services.gate_account_service import get_futures_usdt_total_balance, get_total_balance_usdt
from services.portfolio_service import compute_portfolio_metrics
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
    若当前模式未绑定，则自动回退到另一已绑定模式，避免前端显示 --。
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


def _latest_snapshot(
    db: Session,
    user_id: int,
    scope: str,
    mode: str | None = None,
) -> PortfolioSnapshot | None:
    q = db.query(PortfolioSnapshot).filter(
        PortfolioSnapshot.user_id == user_id,
        PortfolioSnapshot.account_scope == scope,
    )
    if mode:
        q = q.filter(PortfolioSnapshot.mode == mode)
    return q.order_by(desc(PortfolioSnapshot.date), desc(PortfolioSnapshot.id)).first()


@router.get("/summary")
def get_summary(
    mode: str = Query(None),
    account_scope: str = Query("spot", description="spot 现货账户 | futures U本位合约账户"),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    m = mode or get_mode(db, uid)
    scope = _normalize_account_scope(account_scope)
    # 模拟账户镜像：若已把某条回测映射到模拟账户，则直接返回派生的投资组合
    if _sms.is_mirror_enabled(db, uid, m, scope):
        snap = _sms.build_snapshot(db, uid, scope)
        if snap and snap.get("summary"):
            s = snap["summary"]
            data = {
                "total_return": s.get("total_return"),
                "annual_return": s.get("annual_return"),
                "current_nav": s.get("current_nav"),
                "daily_pnl": None,
                "max_drawdown": s.get("max_drawdown"),
                "sharpe": s.get("sharpe"),
                "initial_capital": s.get("initial_capital"),
                "alpha": s.get("alpha"),
                "beta": s.get("beta"),
                "data_source": "simulated_mirror",
                "account_scope": scope,
                "mirror_run_id": (snap.get("run") or {}).get("id"),
            }
            return {"success": True, "data": data, "message": "ok", "code": 200}
    m = _pick_mode_with_binding(db, uid, m)
    broker = get_broker(db, uid, m)
    if broker:
        try:
            if scope == "futures":
                _, _, total = get_futures_usdt_total_balance(m, broker.api_key_enc, broker.api_secret_enc)
                used_scope = "futures"
            else:
                _, _, total = get_total_balance_usdt(m, broker.api_key_enc, broker.api_secret_enc)
                used_scope = "spot"
            total = round(float(total), 4)
            today = date.today()

            # 真实初始资金：取最早快照的 nav，若无则用当前余额并保存
            first = db.query(PortfolioSnapshot).filter(
                PortfolioSnapshot.user_id == uid,
                PortfolioSnapshot.mode == m,
                PortfolioSnapshot.account_scope == scope,
            ).order_by(asc(PortfolioSnapshot.date)).first()

            if not first:
                initial = total
                db.add(
                    PortfolioSnapshot(
                        user_id=uid,
                        nav=total,
                        total_return=None,
                        date=today,
                        mode=m,
                        account_scope=scope,
                    )
                )
                db.commit()
                total_return_val = None
            else:
                initial = float(first.nav)
                total_return_val = (total - initial) / initial if initial else 0
                if abs(total_return_val) < 1e-9:
                    total_return_val = None  # 暂无收益，显示 --
                else:
                    total_return_val = round(total_return_val, 4)
                existing = db.query(PortfolioSnapshot).filter(
                    PortfolioSnapshot.user_id == uid,
                    PortfolioSnapshot.mode == m,
                    PortfolioSnapshot.account_scope == scope,
                    PortfolioSnapshot.date == today,
                ).first()
                if existing:
                    existing.nav = total
                    existing.total_return = total_return_val
                else:
                    db.add(
                        PortfolioSnapshot(
                            user_id=uid,
                            nav=total,
                            total_return=total_return_val,
                            date=today,
                            mode=m,
                            account_scope=scope,
                        )
                    )
                db.commit()

            annual_return = round(total_return_val * 0.5, 4) if total_return_val is not None else None
            try:
                metrics = compute_portfolio_metrics(db, uid, m, scope)
            except Exception:
                metrics = {"sharpe": None, "beta": None, "alpha": None}
            data = {
                "total_return": total_return_val,
                "annual_return": annual_return,
                "current_nav": total,
                "daily_pnl": None,
                "max_drawdown": None,
                "sharpe": metrics["sharpe"],
                "initial_capital": round(initial, 4),
                "alpha": metrics["alpha"],
                "beta": metrics["beta"],
                "data_source": "gate",
                "account_scope": used_scope,
            }
            return {"success": True, "data": data, "message": "ok", "code": 200}
        except Exception as e:
            # 若合约账户不可用，自动回退现货净值（用户常见仅绑定现货权限）
            if scope == "futures":
                try:
                    _, _, total_spot = get_total_balance_usdt(m, broker.api_key_enc, broker.api_secret_enc)
                    total_spot = round(float(total_spot), 4)
                    first = (
                        db.query(PortfolioSnapshot)
                        .filter(
                            PortfolioSnapshot.user_id == uid,
                            PortfolioSnapshot.account_scope == "spot",
                        )
                        .order_by(asc(PortfolioSnapshot.date), asc(PortfolioSnapshot.id))
                        .first()
                    )
                    initial = float(first.nav) if first else total_spot
                    tr = (total_spot - initial) / initial if initial else None
                    if tr is not None and abs(tr) < 1e-9:
                        tr = None
                    data = {
                        "total_return": round(tr, 4) if tr is not None else None,
                        "annual_return": round(tr * 0.5, 4) if tr is not None else None,
                        "current_nav": total_spot,
                        "daily_pnl": None,
                        "max_drawdown": None,
                        "sharpe": None,
                        "initial_capital": round(initial, 4),
                        "alpha": None,
                        "beta": None,
                        "data_source": "gate_spot_fallback",
                        "account_scope": "spot",
                    }
                    return {
                        "success": True,
                        "data": data,
                        "message": f"合约净值暂不可用，已回退现货净值：{_parse_gate_error(e)}",
                        "code": 200,
                    }
                except Exception:
                    pass
            # Gate 短时失败时回退最近快照，避免前端全为 --
            snap = _latest_snapshot(db, uid, scope, mode=m) or _latest_snapshot(db, uid, scope, mode=None)
            if snap:
                cur = float(snap.nav)
                first = (
                    db.query(PortfolioSnapshot)
                    .filter(
                        PortfolioSnapshot.user_id == uid,
                        PortfolioSnapshot.account_scope == scope,
                    )
                    .order_by(asc(PortfolioSnapshot.date), asc(PortfolioSnapshot.id))
                    .first()
                )
                initial = float(first.nav) if first else cur
                tr = ((cur - initial) / initial) if initial else None
                if tr is not None and abs(tr) < 1e-9:
                    tr = None
                data = {
                    "total_return": round(tr, 4) if tr is not None else None,
                    "annual_return": round(tr * 0.5, 4) if tr is not None else None,
                    "current_nav": round(cur, 4),
                    "daily_pnl": None,
                    "max_drawdown": None,
                    "sharpe": None,
                    "initial_capital": round(initial, 4),
                    "alpha": None,
                    "beta": None,
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
    data = {
        "total_return": None, "annual_return": None, "current_nav": None, "daily_pnl": None,
        "max_drawdown": None, "sharpe": None, "initial_capital": None, "alpha": None, "beta": None,
    }
    return {"success": True, "data": data, "message": "未绑定交易所，请先绑定 Gate.io 模拟 API", "code": 200}


@router.get("/nav-history")
def get_nav_history(
    mode: str = Query(None),
    account_scope: str = Query("spot"),
    from_date: str = None,
    to_date: str = None,
    interval: str = "1d",
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": [], "message": "请先登录", "code": 401}
    m = mode or get_mode(db, uid)
    scope = _normalize_account_scope(account_scope)
    # 模拟账户镜像：直接返回派生的时序 NAV（点位 = 等权益曲线按当前净值缩放）
    if _sms.is_mirror_enabled(db, uid, m, scope):
        snap = _sms.build_snapshot(db, uid, scope)
        if snap and isinstance(snap.get("nav_history"), list):
            data = [
                {
                    "ts": int(p.get("t") or 0),
                    "date": None,
                    "nav": float(p.get("nav") or 0),
                    "account_scope": scope,
                }
                for p in snap["nav_history"]
            ]
            return {
                "success": True,
                "data": data,
                "message": "ok",
                "code": 200,
                "meta": {"data_source": "simulated_mirror", "mirror_run_id": (snap.get("run") or {}).get("id")},
            }
    m = _pick_mode_with_binding(db, uid, m)
    broker = get_broker(db, uid, m)
    if broker:
        try:
            if scope == "futures":
                _, _, total = get_futures_usdt_total_balance(m, broker.api_key_enc, broker.api_secret_enc)
            else:
                _, _, total = get_total_balance_usdt(m, broker.api_key_enc, broker.api_secret_enc)
            data = [{"date": "today", "nav": round(total, 4), "account_scope": scope}]
            return {"success": True, "data": data, "message": "ok", "code": 200}
        except Exception:
            pass
    data = [{"date": "today", "nav": 0}]
    return {"success": True, "data": data, "message": "ok", "code": 200}
