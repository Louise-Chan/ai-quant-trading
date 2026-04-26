"""因子库刷新后台 Worker：DeepSeek 挖掘 -> 评估打分 -> Top10 晋升 + 末位淘汰"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from typing import Any

import numpy as np  # pyright: ignore[reportMissingImports]
from sqlalchemy.orm import Session

from core.database import SessionLocal
from models.dynamic_factor import DynamicFactor
from models.factor_library_refresh_job import FactorLibraryRefreshJob
from models.watchlist import Watchlist
from services.deepseek_factor_mining_agent import run_deepseek_factor_mining_agent
from services.strategy_engine.dynamic_factors_executor import compute_dynamic_factor_series
from services.strategy_engine.factor_mining_evaluation import score_factor_for_mining
from services.strategy_engine.factors import candles_to_df
from utils.gate_client import list_candlesticks
from services.broker_service import get_mode
from services.preference_extra import get_deepseek_api_key
from services.deepseek_service import chat_completion_json_object, extract_json_object


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_load_json(s: Any) -> dict:
    if not s:
        return {}
    if isinstance(s, dict):
        return s
    try:
        return json.loads(s)
    except Exception:
        return {}


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


def _normalize_symbol_for_gate(sym: str) -> str:
    """
    适配常见 watchlist symbol 格式差异：
    - "BTC/USDT" -> "BTC_USDT"
    - "BTC-USDT" -> "BTC_USDT"
    - " btc_usdt " -> "BTC_USDT"
    """
    s = str(sym or "").strip().upper()
    if not s:
        return s
    s = s.replace(" ", "")
    s = s.replace("/", "_")
    s = s.replace("-", "_")
    return s


def _combine_symbol_scores(per_symbol_results: list[dict[str, Any]]) -> dict[str, Any]:
    """
    per_symbol_results: 每个 symbol 的 score_factor_for_mining 返回（valid/score/metrics）
    """
    if not per_symbol_results:
        return {"valid": False, "score": 0, "metrics": {"note": "无可用 symbol 结果"}}

    scores = [float(r.get("score") or 0.0) for r in per_symbol_results]
    valid_bools = [bool(r.get("valid")) for r in per_symbol_results]
    metrics_list = [r.get("metrics") or {} for r in per_symbol_results]

    def _avg(key: str) -> float:
        vals = [float(m.get(key) or 0.0) for m in metrics_list]
        return float(np.mean(vals)) if vals else 0.0

    ic_mean_avg = _avg("ic_mean")
    icir_avg = _avg("icir")

    ratios: dict[str, float] = {}
    for comp in (
        "mono_ok",
        "stability_ok",
        "turnover_ok",
        "indep_ok",
    ):
        vals = [bool(m.get("valid_components", {}).get(comp)) for m in metrics_list]
        ratios[comp] = float(np.mean(vals)) if vals else 0.0

    valid = bool(
        abs(ic_mean_avg) >= 0.02
        and icir_avg >= 0.5
        and ratios["mono_ok"] >= 0.6
        and ratios["stability_ok"] >= 0.5
        and ratios["turnover_ok"] >= 0.5
        and ratios["indep_ok"] >= 0.6
    )

    score = int(round(float(np.mean(scores))))
    # 聚合更多指标用于前端/debug
    metrics = {
        "ic_mean_avg": round(ic_mean_avg, 6),
        "icir_avg": round(icir_avg, 6),
        "mono_ok_ratio": round(ratios["mono_ok"], 4),
        "stability_ok_ratio": round(ratios["stability_ok"], 4),
        "turnover_ok_ratio": round(ratios["turnover_ok"], 4),
        "indep_ok_ratio": round(ratios["indep_ok"], 4),
    }
    return {"valid": valid, "score": score, "metrics": metrics, "valid_symbol_rate": float(np.mean(valid_bools))}


def _evaluate_factor_on_symbols(
    *,
    df_by_symbol: dict[str, list[dict[str, Any]]],
    factor: DynamicFactor,
    interval: str,
    independence_ref_factor_series_by_symbol: dict[str, list[tuple[int, Any]]],
    independence_ref_ids_exclude: set[int],
) -> dict[str, Any]:
    """
    independence_ref_factor_series_by_symbol:
      symbol -> [(ref_factor_db_id, ref_series), ...]
    independence_ref_ids_exclude:
      当评估的是某个旧因子时，需要把自身从 independence refs 里剔除，避免自相关导致相关系数=1。
    """
    per_symbol: list[dict[str, Any]] = []
    for sym, candles in df_by_symbol.items():
        df = candles_to_df(candles)
        if df.empty or len(df) < 80:
            continue
        try:
            factor_series = compute_dynamic_factor_series(df, factor.expression_dsl)
        except Exception:
            continue

        refs = []
        for ref_id, ref_series in independence_ref_factor_series_by_symbol.get(sym, []):
            if ref_id in independence_ref_ids_exclude:
                continue
            refs.append(ref_series)

        r = score_factor_for_mining(
            df,
            factor_series,
            interval=interval,
            independence_refs=refs,
        )
        per_symbol.append(r)

    return _combine_symbol_scores(per_symbol)


def process_factor_library_refresh_once() -> None:
    db = SessionLocal()
    try:
        # 只取最老的一个 pending，避免同一用户并发刷新
        job = (
            db.query(FactorLibraryRefreshJob)
            .filter(FactorLibraryRefreshJob.status == "pending")
            .order_by(FactorLibraryRefreshJob.created_at.asc())
            .first()
        )
        if not job:
            return

        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        uid = int(job.user_id)
        interval = str(_safe_load_json(job.params_json).get("interval") or "1h")
        candidate_count = int(_safe_load_json(job.params_json).get("candidate_count") or 50)
        top_keep = int(_safe_load_json(job.params_json).get("top_keep") or 10)
        lib_cap_n = int(_safe_load_json(job.params_json).get("lib_cap_n") or 30)

        # 拉取 watchlist
        sym_list = _default_watchlist_symbols(db, uid, limit=12)
        sym_list = [_normalize_symbol_for_gate(s) for s in sym_list if _normalize_symbol_for_gate(s)]
        if not sym_list:
            job.status = "failed"
            job.error_message = "用户自选为空，无法挖掘因子"
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            return

        mode = get_mode(db, uid)

        def _fetch_candles(sym: str, iv: str, m: str) -> list[dict[str, Any]]:
            # Gate 公共接口对 limit 可能存在上限/波动，做降级重试更稳健
            min_ok = 30
            for lim in (2000, 1000, 600, 300):
                candles = list_candlesticks(sym, iv, limit=lim, mode=m) or []
                if len(candles) >= min_ok:
                    return candles
            return []

        # 近期约 2000 根 K 线（带降级重试，避免 limit 上限导致全空）
        candles_by_symbol: dict[str, list[dict[str, Any]]] = {}
        for sym in sym_list:
            candles = _fetch_candles(sym, interval, mode)
            candles_by_symbol[sym] = candles

        if not any(candles_by_symbol.values()):
            # 如果旧 active 因子存在，则本轮跳过因子刷新，避免把库搞空
            prev_active = (
                db.query(DynamicFactor)
                .filter(DynamicFactor.user_id == uid, DynamicFactor.active == True)  # noqa: E712
                .all()
            )
            # 附带诊断信息（前端展示也更容易定位）
            lens = [(k, len(v or [])) for k, v in candles_by_symbol.items()]
            lens_short = lens[:8]
            msg = f"无法拉取 K 线（请检查网络/绑定/区间）。本次拉取条数：{lens_short}"
            if prev_active:
                job.status = "done"
                job.finished_at = datetime.now(timezone.utc)
                job.user_message = f"{msg}本次保持现有因子库不变：仍激活 {len(prev_active)} 个因子。"
                job.error_message = None
                job.result_json = json.dumps(
                    {"skipped": True, "reason": "candlesticks_empty", "prev_active_count": len(prev_active)},
                    ensure_ascii=False,
                )
                db.commit()
                return

            # 没有旧 active：启用 seed 保底因子，避免因子库永远为空
            seeds = [
                {
                    "factor_id": "seed_mom_5",
                    "name": "Seed: 5期动量",
                    "description": "收盘价相对5根前收益率（seed保底）",
                    "expression_dsl": "(close / shift(close,5) - 1.0)",
                },
                {
                    "factor_id": "seed_mom_10",
                    "name": "Seed: 10期动量",
                    "description": "收盘价相对10根前收益率（seed保底）",
                    "expression_dsl": "(close / shift(close,10) - 1.0)",
                },
                {
                    "factor_id": "seed_rev_1",
                    "name": "Seed: 1期反转",
                    "description": "与上一根涨跌幅相反（seed保底）",
                    "expression_dsl": "-(close / shift(close,1) - 1.0)",
                },
                {
                    "factor_id": "seed_vol_20",
                    "name": "Seed: 20期波动",
                    "description": "近20期收益率标准差（seed保底）",
                    "expression_dsl": "roll_std((close / shift(close,1) - 1.0),20)",
                },
            ]
            active_cnt = 0
            for s in seeds:
                try:
                    ex = db.query(DynamicFactor).filter(
                        DynamicFactor.user_id == uid,
                        DynamicFactor.factor_id == s["factor_id"],
                    ).first()
                    if ex:
                        ex.active = True
                        ex.score = float(ex.score or 0.0)
                        ex.invalid_reason = "candlesticks_empty_seed_active"
                    else:
                        ex = DynamicFactor(
                            user_id=uid,
                            factor_id=s["factor_id"],
                            name=s["name"],
                            description=s["description"],
                            expression_dsl=s["expression_dsl"],
                            active=True,
                            score=0.0,
                            invalid_reason="candlesticks_empty_seed_active",
                            metrics_json=None,
                        )
                        db.add(ex)
                    active_cnt += 1
                except Exception:
                    continue
            db.commit()

            job.status = "done"
            job.finished_at = datetime.now(timezone.utc)
            job.user_message = f"{msg}因子库无旧激活因子，已启用 {active_cnt} 个 seed 保底因子（等待下次成功拉取 K 线后再评估/淘汰）。"
            job.error_message = None
            job.result_json = json.dumps(
                {"skipped": True, "reason": "candlesticks_empty", "seed_activated": active_cnt},
                ensure_ascii=False,
            )
            db.commit()
            return

        # 基于旧 active dynamic 因子：用于独立性相关性参考（ref pool）
        old_active_factors: list[DynamicFactor] = (
            db.query(DynamicFactor)
            .filter(DynamicFactor.user_id == uid, DynamicFactor.active == True)  # noqa: E712
            .order_by(DynamicFactor.score.desc())
            .all()
        )

        independence_ref_ids = {x.id for x in old_active_factors}

        # 先为旧 active 因子算 independence refs：每个 symbol 的 series
        independence_ref_factor_series_by_symbol: dict[str, list[tuple[int, Any]]] = {}
        for sym, candles in candles_by_symbol.items():
            df = candles_to_df(candles)
            if df.empty or len(df) < 80:
                continue
            sym_refs: list[tuple[int, Any]] = []
            for f in old_active_factors[:30]:  # 限制引用规模
                try:
                    s = compute_dynamic_factor_series(df, f.expression_dsl)
                    sym_refs.append((f.id, s))
                except Exception:
                    continue
            independence_ref_factor_series_by_symbol[sym] = sym_refs

        # DeepSeek 挖掘新候选表达式
        deepseek_failed_msg: str | None = None
        key = get_deepseek_api_key(db, uid)
        if not key:
            deepseek_failed_msg = "请在用户偏好（extra）中配置 deepseek_api_key"
            candidates: list[dict[str, Any]] = []
        else:
            try:
                mining_out = run_deepseek_factor_mining_agent(
                    api_key=key,
                    user_prompt=str(_safe_load_json(job.params_json).get("user_prompt") or ""),
                    current_dynamic_factors=[{"factor_id": f.factor_id, "name": f.name} for f in old_active_factors[:30]],
                    candidate_count=candidate_count,
                )
                candidates = mining_out.get("candidates") or []
            except Exception as e:
                deepseek_failed_msg = f"DeepSeek 挖掘失败：{e}"
                candidates = []

        # candidates 为空时：仍对旧 active 因子做重新评估与淘汰（保持系统可用）

        # 如果旧 active 动态因子为空，且 DeepSeek 也没给候选，则做 seed 回退：
        # 只使用我们 DSL 能表达的简单价量/动量类因子，保证动态因子库不会“永远为空”。
        if (not candidates) and (not old_active_factors):
            candidates = [
                {
                    "id": "seed_mom_5",
                    "name": "Seed: 5期动量",
                    "description": "收盘价相对5根前收益率（seed回退）",
                    "expression_dsl": "(close / shift(close,5) - 1.0)",
                },
                {
                    "id": "seed_mom_10",
                    "name": "Seed: 10期动量",
                    "description": "收盘价相对10根前收益率（seed回退）",
                    "expression_dsl": "(close / shift(close,10) - 1.0)",
                },
                {
                    "id": "seed_rev_1",
                    "name": "Seed: 1期反转",
                    "description": "与上一根涨跌幅相反（seed回退）",
                    "expression_dsl": "-(close / shift(close,1) - 1.0)",
                },
                {
                    "id": "seed_vol_20",
                    "name": "Seed: 20期波动",
                    "description": "近20期收益率标准差（seed回退）",
                    "expression_dsl": "roll_std((close / shift(close,1) - 1.0),20)",
                },
                {
                    "id": "seed_bb_pos",
                    "name": "Seed: 布林位置",
                    "description": "价格相对20均线与2倍标准差的位置（seed回退）",
                    "expression_dsl": "(close - roll_mean(close,20)) / (2.0 * roll_std(close,20))",
                },
                {
                    "id": "seed_vol_z",
                    "name": "Seed: 成交量Z偏离",
                    "description": "成交量相对20期均量的偏离（seed回退）",
                    "expression_dsl": "(volume - roll_mean(volume,20)) / roll_mean(volume,20)",
                },
            ]
            if deepseek_failed_msg:
                # 让前端通知明确说明是 seed 回退
                deepseek_failed_msg = f"{deepseek_failed_msg}\n（已启用 seed 动态因子回退以保持库非空）"

        # 创建新动态因子记录（先不激活，后续统一打分+激活/淘汰）
        new_dynamic_factors: list[DynamicFactor] = []
        for c in candidates:
            try:
                f = DynamicFactor(
                    user_id=uid,
                    factor_id=str(c.get("id") or ""),
                    name=str(c.get("name") or "")[:120] or None,
                    description=str(c.get("description") or "")[:2000] or None,
                    expression_dsl=str(c.get("expression_dsl") or ""),
                    active=False,
                    score=0.0,
                    invalid_reason=None,
                    metrics_json=None,
                )
                db.add(f)
                db.flush()  # 获取自增 id
                new_dynamic_factors.append(f)
            except Exception:
                continue
        db.commit()

        # 本轮评估集合：旧 active + 新候选
        eval_factors: list[DynamicFactor] = old_active_factors + new_dynamic_factors

        # 逐个因子评估（多 symbol 聚合）
        eval_results: dict[int, dict[str, Any]] = {}
        for f in eval_factors:
            exclude_self_ids = {f.id}
            res = _evaluate_factor_on_symbols(
                df_by_symbol=candles_by_symbol,
                factor=f,
                interval=interval,
                independence_ref_factor_series_by_symbol=independence_ref_factor_series_by_symbol,
                independence_ref_ids_exclude=exclude_self_ids if f.id in independence_ref_ids else set(),
            )
            eval_results[f.id] = res

        # 更新每个动态因子的 score/metrics（active 先不改，后面统一激活）
        for f in eval_factors:
            r = eval_results.get(f.id) or {}
            metrics = r.get("metrics") or {}
            f.score = float(r.get("score") or 0.0)
            f.metrics_json = json.dumps(metrics, ensure_ascii=False) if metrics else None
            f.last_eval_at = datetime.now(timezone.utc)

            if not r.get("valid"):
                f.invalid_reason = "IC/稳定性/单调性/换手/相关性不达标"
            else:
                f.invalid_reason = None

        db.commit()

        # 有效因子排序、选择 top_keep（有效）与 lib_cap_n（总容量）
        valid_factors = [f for f in eval_factors if bool(eval_results.get(f.id, {}).get("valid"))]
        valid_factors.sort(key=lambda x: float(eval_results.get(x.id, {}).get("score") or 0.0), reverse=True)

        used_score_fallback = False

        if valid_factors:
            top_valid = valid_factors[:top_keep]
            # 容量控制：从 top_valid 里拿，若仍不足就补齐到 lib_cap_n（从剩余 valid 中补；若仍超出再截断）
            target_active = valid_factors[:lib_cap_n]
        else:
            # 若严格阈值筛不出有效因子：为保证因子库可用，退化为按 score 保留前 lib_cap_n 个候选
            used_score_fallback = True
            sorted_by_score = sorted(eval_factors, key=lambda x: float(x.score or 0.0), reverse=True)
            top_valid = sorted_by_score[:top_keep]
            target_active = sorted_by_score[:lib_cap_n]

        target_active_ids = {f.id for f in target_active}

        prev_active_ids = {f.id for f in old_active_factors}
        added_ids = list(target_active_ids - prev_active_ids)
        removed_ids = list(prev_active_ids - target_active_ids)

        # 如果本轮候选为空/DeepSeek 失败导致 valid_factors 全空，
        # 则避免把旧因子“一次性淘汰到空”（尤其是样本长度偏短时更容易发生）。
        if not valid_factors and prev_active_ids:
            target_active_ids = set(prev_active_ids)
            target_active = [f for f in eval_factors if f.id in target_active_ids]
            # 若本轮评分全判为无效，则退化为：按最新 score 从旧 active 中选前 TopK 展示
            try:
                top_valid = sorted(target_active, key=lambda x: float(x.score or 0.0), reverse=True)[:top_keep]
            except Exception:
                top_valid = []
            added_ids = []
            removed_ids = []

        # 更新激活状态
        for f in eval_factors:
            f.active = f.id in target_active_ids
        db.commit()

        job.status = "done"
        job.finished_at = datetime.now(timezone.utc)
        job.result_json = json.dumps(
            {
                "interval": interval,
                "candidate_count": candidate_count,
                "lib_cap_n": lib_cap_n,
                "top_keep": top_keep,
                "added_factor_db_ids": added_ids,
                "removed_factor_db_ids": removed_ids,
                "top_active_factor_db_ids": [f.id for f in target_active],
                "top_valid_factor_db_ids": [f.id for f in top_valid],
                "updated_at": _utc_now_iso(),
            },
            ensure_ascii=False,
        )

        # DeepSeek：生成用户可读的通知文案
        try:
            factor_by_id = {f.id: f for f in eval_factors}

            added_info = [
                {
                    "db_id": str(fid),
                    "factor_id": str(factor_by_id.get(fid).factor_id if factor_by_id.get(fid) else ""),
                    "name": (factor_by_id.get(fid).name or "").strip(),
                    "score": float(factor_by_id.get(fid).score or 0.0) if factor_by_id.get(fid) else None,
                }
                for fid in added_ids
            ]
            removed_info = [
                {"db_id": str(fid), "name": (factor_by_id.get(fid).name or "").strip()}
                for fid in removed_ids
            ]
            top10_info = [
                {"db_id": str(f.id), "name": (f.name or "").strip(), "score": float(f.score or 0.0)}
                for f in top_valid
            ]

            sys_prompt = """你是量化策略助手。根据因子库的新增/淘汰结果，用中文给用户一段“简单易懂”的通知文案：
要求：
1) 不要涉及具体投资建议/保证收益；
2) 用 3-6 句话说明：新增哪些因子、淘汰哪些因子、Top10 有哪些、整体策略信号更偏向何种风格（尽量从名字/描述推断）；
3) 字数不超过 600 汉字；
4) 输出必须是合法 JSON，键名固定：{ "user_message": "..." }"""

            user_prompt = json.dumps(
                {
                    "added_factors": added_info[:20],
                    "removed_factors": removed_info[:20],
                    "top10_valid_factors": top10_info,
                    "active_count": len(target_active_ids),
                    "lib_cap_n": lib_cap_n,
                },
                ensure_ascii=False,
            )
            raw = chat_completion_json_object(
                key,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                timeout=120,
            )
            data = extract_json_object(raw)
            job.user_message = str(data.get("user_message") or "")
            if not job.user_message.strip():
                job.user_message = f"因子库刷新完成：新增 {len(added_ids)} 个候选，淘汰 {len(removed_ids)} 个旧因子；当前激活 {len(target_active_ids)} 个（上限 {lib_cap_n}）。"
        except Exception:
            job.user_message = f"因子库刷新完成：新增 {len(added_ids)} 个候选，淘汰 {len(removed_ids)} 个旧因子；当前激活 {len(target_active_ids)} 个（上限 {lib_cap_n}）。"

        if deepseek_failed_msg:
            # 仍标记 done：用于前端展示“DeepSeek挖掘失败但仍完成旧因子重评估/淘汰”
            if job.user_message:
                job.user_message = f"{deepseek_failed_msg}\n{job.user_message}"
            else:
                job.user_message = deepseek_failed_msg

        if used_score_fallback:
            msg = "保底策略：严格有效性阈值本轮未筛出足够因子，本轮按分数保留以维持因子库可用。"
            if job.user_message:
                job.user_message = f"{msg}\n{job.user_message}"
            else:
                job.user_message = msg

        job.error_message = None
        db.commit()

    except Exception as e:
        try:
            # 回滚并标记失败（若 job 已更新 running）
            db.rollback()
        except Exception:
            pass
        try:
            # 尝试找到最近的 running job 标记失败（简化）
            job2 = (
                db.query(FactorLibraryRefreshJob)
                .filter(FactorLibraryRefreshJob.status == "running")
                .order_by(FactorLibraryRefreshJob.started_at.desc())
                .first()
            )
            if job2:
                job2.status = "failed"
                job2.error_message = str(e)[:2000]
                job2.finished_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def start_factor_library_refresh_worker(interval_sec: float = 6.0) -> None:
    def _loop() -> None:
        while True:
            try:
                process_factor_library_refresh_once()
            except Exception as ex:
                print(f"[factor_library_refresh_worker] {ex}")
            time.sleep(interval_sec)

    t = threading.Thread(target=_loop, name="factor-library-refresh-worker", daemon=True)
    t.start()

