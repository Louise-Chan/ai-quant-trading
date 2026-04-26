"""策略引擎：多因子/评估/权重/ML/回测/仓位 — 供调试与前端展示原始输出"""
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Query, Header, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.database import get_db
from core.security import decode_token
from models.watchlist import Watchlist
from services.broker_service import get_broker, get_mode
from services.gate_account_service import get_total_balance_usdt
from services.preference_extra import get_deepseek_api_key
from services.risk_settings_memory import risk_settings_for_user
from services.strategy_engine.factors import DEFAULT_BUILTIN_FACTOR_IDS, FACTOR_LIBRARY
from services.strategy_engine.portfolio_report import build_analytics_report, run_portfolio_visual_backtest
from services.strategy_engine.runner import analyze_symbol
from utils.gate_client import (
    _SPOT_LOOKBACK_SAFETY_BARS,
    _SPOT_MAX_LOOKBACK_BARS,
    _bar_seconds,
    _normalize_interval,
    list_candlesticks,
    list_candlesticks_range,
)
from models.dynamic_factor import DynamicFactor
from models.factor_library_refresh_job import FactorLibraryRefreshJob

import json

router = APIRouter()

_MAX_SYMBOLS = 15


class DeepseekFactorScreenBody(BaseModel):
    mode: str = Field("screen", description="generate | screen | optimize")
    user_prompt: str = ""
    current_factors: list[str] | None = None
    backtest_summary: dict[str, Any] | None = None


class DeepseekBacktestReportBody(BaseModel):
    user_prompt: str = ""
    backtest_summary: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] | None = None


class FactorLibraryRefreshAsyncBody(BaseModel):
    """异步刷新因子库：挖掘/评估/淘汰/补库（由后台 Worker 完成）"""

    interval: str = Field(default="1h", description="与前端回测 interval 一致（影响稳定性代理指标）")
    candidate_count: int = Field(default=50, ge=1, le=200, description="DeepSeek 生成候选因子数量")
    top_keep: int = Field(default=10, ge=1, le=50, description="TopK 有效因子用于提示（激活时实际会受 lib_cap_n 影响）")
    lib_cap_n: int = Field(default=30, ge=5, le=200, description="因子库最大保留数量（末位淘汰）")
    user_prompt: str = Field(default="", description="可选：给 DeepSeek 的挖掘需求描述")


def get_current_user_id(authorization: str = Header(None)) -> int | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    payload = decode_token(authorization[7:])
    return int(payload["sub"]) if payload and payload.get("sub") else None


@router.get("/analyze")
def analyze(
    symbol: str = Query(..., description="交易对 BTC_USDT"),
    interval: str = Query("1h"),
    mode: str = Query(None),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    m = mode or get_mode(db, uid)
    candles = list_candlesticks(symbol.strip(), interval, limit=320, mode=m)
    risk = risk_settings_for_user(uid, m)
    total_usdt = None
    broker = get_broker(db, uid, m)
    if broker:
        try:
            _, _, total_usdt = get_total_balance_usdt(m, broker.api_key_enc, broker.api_secret_enc)
        except Exception:
            pass
    pkg = analyze_symbol(symbol.strip(), candles, risk, interval=interval, total_usdt=total_usdt)
    return {"success": True, "data": pkg, "message": "ok", "code": 200}


def _parse_symbols_param(symbols: str) -> list[str]:
    return [x.strip().upper() for x in (symbols or "").split(",") if x.strip()]


def _parse_factors_param(factors: str) -> list[str] | None:
    raw = (factors or "").strip()
    if not raw:
        return None
    return [x.strip() for x in raw.split(",") if x.strip()]


def _utc_range_seconds(start_date: str, end_date: str) -> tuple[int, int] | None:
    """YYYY-MM-DD，按 UTC 日界；结束日含 23:59:59。"""
    try:
        s = datetime.strptime(start_date.strip()[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        e = datetime.strptime(end_date.strip()[:10], "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
        )
    except ValueError:
        return None
    if s > e:
        return None
    return int(s.timestamp()), int(e.timestamp())


def _default_watchlist_symbols(db: Session, uid: int, limit: int = 12) -> list[str]:
    rows = (
        db.query(Watchlist.symbol)
        .filter(Watchlist.user_id == uid, Watchlist.quote_market == "spot")
        .order_by(Watchlist.id.desc())
        .limit(limit)
        .all()
    )
    out: list[str] = []
    seen: set[str] = set()
    for (sym,) in rows:
        su = (sym or "").strip().upper()
        if su and su not in seen:
            seen.add(su)
            out.append(su)
    return out


@router.get("/analytics-report")
def analytics_report(
    symbols: str = Query("", description="逗号分隔交易对；留空则用现货自选前 12 个"),
    interval: str = Query("1h"),
    mode: str = Query(None),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """预测 / 风险 / 归因 三模型表格数据 + 评分（本地引擎，可定时刷新）"""
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    m = mode or get_mode(db, uid)
    sym_list = _parse_symbols_param(symbols)
    if not sym_list:
        sym_list = _default_watchlist_symbols(db, uid)
    if not sym_list:
        return {
            "success": False,
            "data": None,
            "message": "请填写 symbols 参数或在仪表盘添加现货自选",
            "code": 400,
        }
    sym_list = sym_list[:_MAX_SYMBOLS]
    risk = risk_settings_for_user(uid, m)
    total_usdt = None
    broker = get_broker(db, uid, m)
    if broker:
        try:
            _, _, total_usdt = get_total_balance_usdt(m, broker.api_key_enc, broker.api_secret_enc)
        except Exception:
            pass
    packages: list[tuple[str, dict]] = []
    candles_map: dict[str, list] = {}
    for s in sym_list:
        candles = list_candlesticks(s, interval, limit=320, mode=m)
        candles_map[s] = candles or []
        if not candles:
            continue
        pkg = analyze_symbol(s, candles, risk, interval=interval, total_usdt=total_usdt)
        packages.append((s, pkg))
    if not packages:
        return {"success": False, "data": None, "message": "所选标的均无可用 K 线", "code": 400}
    rep = build_analytics_report(packages, interval, candles_by_symbol=candles_map)
    rep["symbols_used"] = [p[0] for p in packages]
    return {"success": True, "data": rep, "message": "ok", "code": 200}


@router.get("/factor-library")
def factor_library(
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """可视化回测用：可用因子元数据列表"""
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}

    # 系统静态因子 + 用户动态激活因子
    dyn_rows = (
        db.query(DynamicFactor)
        .filter(DynamicFactor.user_id == uid, DynamicFactor.active == True)  # noqa: E712
        .order_by(DynamicFactor.score.desc())
        .all()
    )
    dyn_factors = [
        {
            "id": f"dyn_{r.id}",
            "name": r.name or r.factor_id or f"dyn_{r.id}",
            "description": r.description or "",
            "score": float(r.score or 0.0),
        }
        for r in dyn_rows
    ]

    # 前端主要显示/勾选 id/name/description；score 仅用于排序（也可显示）
    return {
        "success": True,
        "data": {
            "factors": FACTOR_LIBRARY + dyn_factors,
            "default_builtin_factor_ids": list(DEFAULT_BUILTIN_FACTOR_IDS),
        },
        "message": "ok",
        "code": 200,
    }


@router.post("/factor-library/refresh-async")
def factor_library_refresh_async(
    body: FactorLibraryRefreshAsyncBody,
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}

    key = get_deepseek_api_key(db, uid)
    if not key:
        return {
            "success": False,
            "data": None,
            "message": "请在用户偏好（extra）中配置 deepseek_api_key",
            "code": 400,
        }

    # 避免重复：同一用户同一时刻只允许 1 个 pending/running job
    exist = (
        db.query(FactorLibraryRefreshJob)
        .filter(
            FactorLibraryRefreshJob.user_id == uid,
            FactorLibraryRefreshJob.status.in_(("pending", "running")),
        )
        .order_by(FactorLibraryRefreshJob.updated_at.desc())
        .first()
    )
    if exist:
        return {"success": True, "data": {"job_id": exist.id, "status": exist.status}, "message": "已有任务进行中", "code": 200}

    job = FactorLibraryRefreshJob(
        user_id=uid,
        status="pending",
        params_json=json.dumps(
            {
                "interval": body.interval,
                "candidate_count": int(body.candidate_count),
                "top_keep": int(body.top_keep),
                "lib_cap_n": int(body.lib_cap_n),
                "user_prompt": body.user_prompt or "",
            },
            ensure_ascii=False,
        ),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    return {"success": True, "data": {"job_id": job.id, "status": job.status}, "message": "已提交刷新任务", "code": 200}


@router.get("/factor-library/refresh-status")
def factor_library_refresh_status(
    job_id: int = Query(..., description="refresh job id"),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}

    job = db.query(FactorLibraryRefreshJob).filter(FactorLibraryRefreshJob.id == job_id, FactorLibraryRefreshJob.user_id == uid).first()
    if not job:
        return {"success": False, "data": None, "message": "任务不存在", "code": 404}

    data = {
        "job_id": job.id,
        "status": job.status,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "user_message": job.user_message,
        "error_message": job.error_message,
        "result": json.loads(job.result_json) if job.result_json else None,
    }
    return {"success": True, "data": data, "message": "ok", "code": 200}


@router.get("/backtest-visual")
def backtest_visual(
    symbols: str = Query("", description="逗号分隔；留空则用现货自选"),
    interval: str = Query("1h"),
    mode: str = Query(None),
    factors: str = Query("", description="参与回测的因子 id，逗号分隔；留空表示全部"),
    start_date: str = Query("", description="回测开始 YYYY-MM-DD，须与 end_date 同时传入"),
    end_date: str = Query("", description="回测结束 YYYY-MM-DD（含当日），须与 start_date 同时传入"),
    max_opens_per_day: int = Query(0, ge=0, le=200, description="每天最多开仓次数；0 表示不限制"),
    avg_daily_mode: str = Query("trading", description="平均每日开仓口径：trading(交易日) / natural(自然日)"),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """组合可视化回测：净值曲线、夏普、Alpha、标的显著性、因子作用评分"""
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    m = mode or get_mode(db, uid)
    sym_list = _parse_symbols_param(symbols)
    if not sym_list:
        sym_list = _default_watchlist_symbols(db, uid)
    if not sym_list:
        return {
            "success": False,
            "data": None,
            "message": "请填写 symbols 或在仪表盘添加现货自选",
            "code": 400,
        }
    sym_list = sym_list[:_MAX_SYMBOLS]
    candles_map: dict[str, list] = {}
    range_meta: dict[str, Any]
    sd = (start_date or "").strip()
    ed = (end_date or "").strip()
    if sd and ed:
        sec = _utc_range_seconds(sd, ed)
        if not sec:
            return {
                "success": False,
                "data": None,
                "message": "日期格式无效或开始日晚于结束日（请使用 YYYY-MM-DD）",
                "code": 400,
            }
        fs, ts_end = sec
        span = ts_end - fs
        if span > 86400 * 366 * 5:
            return {"success": False, "data": None, "message": "回测区间过长（最多约 5 年）", "code": 400}
        bar_sec = max(1, _bar_seconds(_normalize_interval(interval)))
        # Gate 仅允许最近 _SPOT_MAX_LOOKBACK_BARS 根之内的 _from，超出则 400
        import time as _time_mod
        now_sec = int(_time_mod.time())
        effective_max_lookback = _SPOT_MAX_LOOKBACK_BARS - _SPOT_LOOKBACK_SAFETY_BARS
        min_allowed_from = now_sec - effective_max_lookback * bar_sec
        fs_effective = max(fs, min_allowed_from)
        lookback_clipped = fs_effective > fs
        if fs_effective >= ts_end:
            iv_norm = _normalize_interval(interval)
            earliest_ymd = datetime.fromtimestamp(min_allowed_from, tz=timezone.utc).strftime("%Y-%m-%d")
            return {
                "success": False,
                "data": None,
                "message": (
                    f"所选开始日过于久远：Gate 现货 {iv_norm} 周期只允许最近 {_SPOT_MAX_LOOKBACK_BARS} 根之内的起点，"
                    f"最早可用起点约为 {earliest_ymd}（UTC）；请缩短回测区间或选择更短的 K 线周期。"
                ),
                "code": 400,
            }
        # 按区间估算根数并留余量；默认 15000 会截断例如 15m×半年（约 1.7 万根）
        max_bars = min(250_000, max(1024, (ts_end - fs_effective) // bar_sec + 256))
        for s in sym_list:
            candles_map[s] = list_candlesticks_range(s, interval, fs_effective, ts_end, mode=m, max_bars=max_bars) or []
        effective_start_date = datetime.fromtimestamp(fs_effective, tz=timezone.utc).strftime("%Y-%m-%d")
        range_meta = {
            "mode": "date_range",
            "start_date": effective_start_date if lookback_clipped else sd[:10],
            "end_date": ed[:10],
            "from_ts": fs_effective,
            "to_ts": ts_end,
            "requested_start_date": sd[:10],
            "lookback_clipped": lookback_clipped,
            "max_lookback_bars": _SPOT_MAX_LOOKBACK_BARS,
        }
    elif sd or ed:
        return {
            "success": False,
            "data": None,
            "message": "请同时填写开始日期与结束日期，或两者都留空以使用最近 K 线",
            "code": 400,
        }
    else:
        for s in sym_list:
            candles_map[s] = list_candlesticks(s, interval, limit=2000, mode=m) or []
        range_meta = {"mode": "recent", "bars_limit": 2000}
    if not any(candles_map.values()):
        return {"success": False, "data": None, "message": "无法拉取 K 线（检查网络、区间是否有数据或绑定）", "code": 400}
    active = _parse_factors_param(factors)

    # 动态因子表达式：把 dyn_{db_id} -> expression_dsl 注入到回测引擎
    dyn_expressions: dict[str, str] = {}
    if active:
        dyn_keys = [str(x).strip() for x in active if str(x).strip().startswith("dyn_")]
        dyn_db_ids: list[int] = []
        for k in dyn_keys:
            try:
                dyn_db_ids.append(int(k.split("dyn_")[1]))
            except Exception:
                continue
        if dyn_db_ids:
            dyn_rows = (
                db.query(DynamicFactor)
                .filter(DynamicFactor.user_id == uid, DynamicFactor.id.in_(dyn_db_ids), DynamicFactor.active == True)  # noqa: E712
                .all()
            )
            for r in dyn_rows:
                dyn_expressions[f"dyn_{r.id}"] = r.expression_dsl

    # 需要动态因子计算的表达式映射（给 portfolio_report 注入 df[dyn_xxx]）
    dyn_map = dyn_expressions if dyn_expressions else None
    data = run_portfolio_visual_backtest(
        sym_list,
        candles_map,
        interval=interval,
        active_factors=active,
        dynamic_factor_expressions=dyn_map,
        max_opens_per_day=(int(max_opens_per_day) if int(max_opens_per_day) > 0 else None),
        avg_daily_mode=("natural" if str(avg_daily_mode).strip().lower() == "natural" else "trading"),
    )
    data["symbols_requested"] = sym_list
    data["backtest_range"] = range_meta
    return {"success": True, "data": data, "message": "ok", "code": 200}


@router.post("/deepseek-factor-screen")
def deepseek_factor_screen(
    body: DeepseekFactorScreenBody,
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """DeepSeek：按策略描述筛选/生成/优化因子子集（需用户配置 DeepSeek API Key）"""
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    key = get_deepseek_api_key(db, uid)
    if not key:
        return {
            "success": False,
            "data": None,
            "message": "请在用户偏好（extra）中配置 deepseek_api_key",
            "code": 400,
        }
    try:
        from services.deepseek_factor_agent import run_deepseek_factor_agent

        out = run_deepseek_factor_agent(
            key,
            body.mode,
            body.user_prompt or "",
            body.current_factors,
            body.backtest_summary,
        )
        return {"success": True, "data": out, "message": "ok", "code": 200}
    except ValueError as e:
        return {"success": False, "data": None, "message": str(e), "code": 400}
    except Exception as e:
        return {"success": False, "data": None, "message": str(e), "code": 500}


@router.post("/deepseek-backtest-report")
def deepseek_backtest_report(
    body: DeepseekBacktestReportBody,
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """DeepSeek：根据最近一次回测的结构化摘要生成中文解读报告（需配置 DeepSeek API Key）"""
    uid = get_current_user_id(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    key = get_deepseek_api_key(db, uid)
    if not key:
        return {
            "success": False,
            "data": None,
            "message": "请在用户偏好（extra）中配置 deepseek_api_key",
            "code": 400,
        }
    if not body.backtest_summary:
        return {
            "success": False,
            "data": None,
            "message": "请传入回测摘要 backtest_summary",
            "code": 400,
        }
    try:
        from services.deepseek_backtest_report import run_deepseek_backtest_report

        out = run_deepseek_backtest_report(
            key,
            body.user_prompt or "",
            body.backtest_summary,
            body.context,
        )
        return {"success": True, "data": out, "message": "ok", "code": 200}
    except ValueError as e:
        return {"success": False, "data": None, "message": str(e), "code": 400}
    except Exception as e:
        return {"success": False, "data": None, "message": str(e), "code": 500}
