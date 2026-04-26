"""可视化回测历史记录：列表、详情、保存、删除（每用户保留最近 N 条）"""
import json
from typing import Any

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.database import get_db
from core.security import decode_token
from models.backtest_run import BacktestRun
from models.user_strategy import UserStrategy

router = APIRouter()

# 每用户保留的历史回测上限；新保存超出时按 id 升序淘汰旧记录
_MAX_RUNS_PER_USER = 60


def _uid(authorization: str | None) -> int | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    payload = decode_token(authorization[7:])
    return int(payload["sub"]) if payload and payload.get("sub") else None


class BacktestRunSaveBody(BaseModel):
    user_strategy_id: int | None = None
    name: str | None = Field(default=None, max_length=200)
    interval: str | None = None
    symbols: list[str] | None = None
    factors: list[str] | None = None
    range: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None
    result: dict[str, Any] = Field(..., description="strategy-engine/backtest-visual 返回的完整 data")


def _dump(v: Any) -> str | None:
    if v is None:
        return None
    try:
        return json.dumps(v, ensure_ascii=False)
    except (TypeError, ValueError):
        return None


def _load(s: str | None) -> Any:
    if not s:
        return None
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return None


def _row_to_summary(row: BacktestRun, strategy_name_map: dict[int, str]) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_strategy_id": row.user_strategy_id,
        "user_strategy_name": (
            strategy_name_map.get(int(row.user_strategy_id)) if row.user_strategy_id else None
        ),
        "name": row.name or "",
        "interval": row.interval or "",
        "symbols": _load(row.symbols_json) or [],
        "factors": _load(row.factors_json) or [],
        "range": _load(row.range_json) or {},
        "summary": _load(row.summary_json) or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("")
def list_backtest_runs(
    limit: int = Query(60, ge=1, le=200),
    user_strategy_id: int | None = Query(None, description="仅筛选某策略"),
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    uid = _uid(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    q = db.query(BacktestRun).filter(BacktestRun.user_id == uid)
    if user_strategy_id and int(user_strategy_id) > 0:
        q = q.filter(BacktestRun.user_strategy_id == int(user_strategy_id))
    rows = q.order_by(BacktestRun.id.desc()).limit(int(limit)).all()
    sid_set = {int(r.user_strategy_id) for r in rows if r.user_strategy_id}
    name_map: dict[int, str] = {}
    if sid_set:
        us_rows = db.query(UserStrategy).filter(UserStrategy.id.in_(sid_set)).all()
        for us in us_rows:
            name_map[int(us.id)] = us.name or f"策略#{us.id}"
    return {
        "success": True,
        "data": {"list": [_row_to_summary(r, name_map) for r in rows]},
        "message": "ok",
        "code": 200,
    }


@router.get("/{rid}")
def get_backtest_run(
    rid: int,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    uid = _uid(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    row = (
        db.query(BacktestRun)
        .filter(BacktestRun.id == rid, BacktestRun.user_id == uid)
        .first()
    )
    if not row:
        return {"success": False, "data": None, "message": "记录不存在", "code": 404}
    name_map: dict[int, str] = {}
    if row.user_strategy_id:
        us = (
            db.query(UserStrategy)
            .filter(UserStrategy.id == int(row.user_strategy_id))
            .first()
        )
        if us:
            name_map[int(us.id)] = us.name or f"策略#{us.id}"
    out = _row_to_summary(row, name_map)
    out["result"] = _load(row.result_json) or {}
    return {"success": True, "data": out, "message": "ok", "code": 200}


@router.post("")
def save_backtest_run(
    body: BacktestRunSaveBody,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    uid = _uid(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    result = body.result or {}
    if not isinstance(result, dict) or not result:
        return {"success": False, "data": None, "message": "缺少 result（回测结果）", "code": 400}

    usid: int | None = None
    if body.user_strategy_id and int(body.user_strategy_id) > 0:
        found = (
            db.query(UserStrategy)
            .filter(
                UserStrategy.id == int(body.user_strategy_id),
                UserStrategy.user_id == uid,
            )
            .first()
        )
        if found:
            usid = int(found.id)

    row = BacktestRun(
        user_id=uid,
        user_strategy_id=usid,
        name=(body.name or "").strip() or None,
        interval=(body.interval or "").strip() or None,
        symbols_json=_dump(body.symbols or []),
        factors_json=_dump(body.factors or []),
        range_json=_dump(body.range or {}),
        summary_json=_dump(body.summary or {}),
        result_json=_dump(result),
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    # 维护每用户容量上限：超过则按 id 升序删除最旧
    try:
        total = db.query(BacktestRun).filter(BacktestRun.user_id == uid).count()
        if total > _MAX_RUNS_PER_USER:
            excess = total - _MAX_RUNS_PER_USER
            old_rows = (
                db.query(BacktestRun)
                .filter(BacktestRun.user_id == uid)
                .order_by(BacktestRun.id.asc())
                .limit(excess)
                .all()
            )
            for old in old_rows:
                db.delete(old)
            db.commit()
    except Exception:
        db.rollback()

    return {
        "success": True,
        "data": {"id": row.id, "created_at": row.created_at.isoformat() if row.created_at else None},
        "message": "已保存",
        "code": 200,
    }


@router.delete("/{rid}")
def delete_backtest_run(
    rid: int,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    uid = _uid(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    row = (
        db.query(BacktestRun)
        .filter(BacktestRun.id == rid, BacktestRun.user_id == uid)
        .first()
    )
    if not row:
        return {"success": False, "data": None, "message": "记录不存在", "code": 404}
    db.delete(row)
    db.commit()
    return {"success": True, "data": None, "message": "已删除", "code": 200}
