"""
模拟账户镜像 API

* GET  /api/v1/simulated-mirror/status            - 查询当前镜像配置与快照摘要
* POST /api/v1/simulated-mirror/enable            - 将指定 backtest_run 设为模拟账户展示源
* POST /api/v1/simulated-mirror/disable           - 关闭镜像，恢复走真实/空数据
* GET  /api/v1/simulated-mirror/snapshot          - 返回派生后的完整快照（投资组合+交易+净值曲线）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.database import get_db
from core.security import decode_token
from models.backtest_run import BacktestRun
from services import simulated_mirror_service as sms

router = APIRouter()


def _uid(authorization: str | None) -> int | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    payload = decode_token(authorization[7:])
    return int(payload["sub"]) if payload and payload.get("sub") else None


class EnableMirrorBody(BaseModel):
    backtest_run_id: int = Field(..., description="backtest_runs.id")
    current_nav: float = Field(..., gt=0, description="固定当前净值（USDT）")
    account_scope: str = Field("spot", description="spot 或 futures")


@router.get("/status")
def status(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    uid = _uid(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    cfg = sms.get_mirror_config(db, uid)
    run_name = None
    if cfg.get("backtest_run_id"):
        row = (
            db.query(BacktestRun)
            .filter(BacktestRun.id == int(cfg["backtest_run_id"]), BacktestRun.user_id == uid)
            .first()
        )
        if row:
            run_name = row.name or ""
    return {
        "success": True,
        "data": {**cfg, "backtest_run_name": run_name},
        "message": "ok",
        "code": 200,
    }


@router.post("/enable")
def enable(
    body: EnableMirrorBody,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    uid = _uid(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    run = (
        db.query(BacktestRun)
        .filter(BacktestRun.id == int(body.backtest_run_id), BacktestRun.user_id == uid)
        .first()
    )
    if not run:
        return {"success": False, "data": None, "message": "回测记录不存在", "code": 404}
    cfg = sms.set_mirror(db, uid, int(body.backtest_run_id), float(body.current_nav), body.account_scope)
    snap = sms.build_snapshot(db, uid, cfg["account_scope"]) or {}
    return {
        "success": True,
        "data": {"config": cfg, "summary": snap.get("summary")},
        "message": "已开启模拟账户镜像",
        "code": 200,
    }


@router.post("/disable")
def disable(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    uid = _uid(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    sms.clear_mirror(db, uid)
    return {"success": True, "data": None, "message": "已关闭模拟账户镜像", "code": 200}


@router.get("/snapshot")
def snapshot(
    account_scope: str = "spot",
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    uid = _uid(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    snap = sms.build_snapshot(db, uid, account_scope)
    if not snap:
        return {"success": True, "data": {"active": False}, "message": "未启用或数据缺失", "code": 200}
    return {"success": True, "data": snap, "message": "ok", "code": 200}
