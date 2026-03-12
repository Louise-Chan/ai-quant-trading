"""投资组合 API - 真实初始资金来自 Gate 首次余额，收益按此计算，无收益时显示 --"""
from datetime import date
from fastapi import APIRouter, Query, Header, Depends
from sqlalchemy.orm import Session
from sqlalchemy import asc
from core.database import get_db
from core.security import decode_token
from models.portfolio_snapshot import PortfolioSnapshot
from services.broker_service import get_broker, get_mode, _parse_gate_error
from services.gate_account_service import get_total_balance_usdt
from services.portfolio_service import compute_portfolio_metrics

router = APIRouter()


def get_current_user_id(authorization: str = Header(None)) -> int | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    payload = decode_token(authorization[7:])
    return int(payload["sub"]) if payload and payload.get("sub") else None


@router.get("/summary")
def get_summary(mode: str = Query(None), authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    m = mode or get_mode(db, uid)
    broker = get_broker(db, uid, m)
    if broker:
        try:
            _, _, total = get_total_balance_usdt(m, broker.api_key_enc, broker.api_secret_enc)
            total = round(float(total), 4)
            today = date.today()

            # 真实初始资金：取最早快照的 nav，若无则用当前余额并保存
            first = db.query(PortfolioSnapshot).filter(
                PortfolioSnapshot.user_id == uid,
                PortfolioSnapshot.mode == m,
            ).order_by(asc(PortfolioSnapshot.date)).first()

            if not first:
                initial = total
                db.add(PortfolioSnapshot(user_id=uid, nav=total, total_return=None, date=today, mode=m))
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
                    PortfolioSnapshot.date == today,
                ).first()
                if existing:
                    existing.nav = total
                    existing.total_return = total_return_val
                else:
                    db.add(PortfolioSnapshot(user_id=uid, nav=total, total_return=total_return_val, date=today, mode=m))
                db.commit()

            annual_return = round(total_return_val * 0.5, 4) if total_return_val is not None else None
            try:
                metrics = compute_portfolio_metrics(db, uid, m)
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
            }
            return {"success": True, "data": data, "message": "ok", "code": 200}
        except Exception as e:
            return {"success": False, "data": None, "message": _parse_gate_error(e), "code": 500}
    data = {
        "total_return": None, "annual_return": None, "current_nav": None, "daily_pnl": None,
        "max_drawdown": None, "sharpe": None, "initial_capital": None, "alpha": None, "beta": None,
    }
    return {"success": True, "data": data, "message": "未绑定交易所，请先绑定 Gate.io 模拟 API", "code": 200}


@router.get("/nav-history")
def get_nav_history(mode: str = Query(None), from_date: str = None, to_date: str = None, interval: str = "1d",
                    authorization: str = Header(None), db: Session = Depends(get_db)):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": [], "message": "请先登录", "code": 401}
    m = mode or get_mode(db, uid)
    broker = get_broker(db, uid, m)
    if broker:
        try:
            _, _, total = get_total_balance_usdt(m, broker.api_key_enc, broker.api_secret_enc)
            data = [{"date": "today", "nav": round(total, 4)}]
            return {"success": True, "data": data, "message": "ok", "code": 200}
        except Exception:
            pass
    data = [{"date": "today", "nav": 0}]
    return {"success": True, "data": data, "message": "ok", "code": 200}
