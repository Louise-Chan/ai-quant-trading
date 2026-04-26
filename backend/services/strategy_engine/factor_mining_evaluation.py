"""因子挖掘评估：用于新动态因子候选的有效性判定与打分排序

本模块与 `factor_evaluation.evaluate_factors_ic` 兼容：
- 基础预测能力：IC / ICIR
- 分层单调性：高因子值对应的下一期收益是否“随分组单调”
- 稳定性：用滚动 IC 衰减的“半衰期代理”（half_life_bars）
- 换手率/信号稳定：用 z-score 后信号翻转频率作为 turnover proxy
- 独立性：与旧动态因子池的相关性惩罚（max_abs_corr / mean_abs_corr）

注意：现有引擎的“因子评估”是单标的时间序列相关（非截面横截面因子）。
因此分层与稳定性也采用时间序列分布的代理指标。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np  # pyright: ignore[reportMissingImports]
import pandas as pd  # pyright: ignore[reportMissingImports]

from services.strategy_engine.factor_evaluation import evaluate_factors_ic, forward_return


_HALF_LIFE_BAR_MIN_BY_INTERVAL: dict[str, int] = {
    "1m": 60 * 6,  # 约 6 小时（按 1m 颗粒度）
    "15m": 96,  # 约 24 小时
    "1h": 24,
    "4h": 6,
    "1d": 1,
}


def _safe_corr(a: pd.Series, b: pd.Series) -> float:
    x = pd.to_numeric(a, errors="coerce").astype(float)
    y = pd.to_numeric(b, errors="coerce").astype(float)
    m = x.notna() & y.notna()
    if m.sum() < 20:
        return 0.0
    c = float(np.corrcoef(x[m].values, y[m].values)[0, 1])
    if not math.isfinite(c):
        return 0.0
    return c


def _half_life_proxy_bars(
    factor: pd.Series,
    close: pd.Series,
    window: int = 80,
) -> tuple[int, float]:
    """
    半衰期代理：
    - 计算 rolling IC 序列 abs(IC_t)
    - 取第一个非 NaN 的 abs(IC) 作为 initial
    - 找到 abs(IC) <= initial/2 的最早位置（以“从初始非 NaN 起算的 bars 数”表示）
    """
    fwd = forward_return(close)
    ic_series = factor.rolling(window, min_periods=max(15, window // 2)).corr(fwd)
    non_na = ic_series.abs().dropna()
    if len(non_na) < 10:
        return 0, 0.0
    initial = float(non_na.iloc[0])
    if initial <= 1e-12:
        return 0, initial
    target = initial / 2.0
    # 最早满足条件的位置
    idx = None
    for i in range(len(non_na)):
        if float(non_na.iloc[i]) <= target:
            idx = i
            break
    if idx is None:
        return len(non_na), initial
    return int(idx), initial


def _monotonicity_proxy(
    factor: pd.Series,
    close: pd.Series,
    groups: int = 5,
) -> dict[str, Any]:
    """
    分层单调性代理：
    - 用全样本分位数（qcut）把 factor 划成 5 组（低->高）
    - 对每组计算未来收益均值 fwd_return
    - 用“组序号 vs 组收益”的 Spearman 相关 + 顶底差判定单调方向
    """
    fwd = forward_return(close)
    x = pd.to_numeric(factor, errors="coerce").astype(float)
    m = x.notna() & fwd.notna()
    x = x[m]
    fwd = fwd[m]
    if len(x) < 80:
        return {"monotonicity_spearman": 0.0, "top_bottom_diff": 0.0, "monotonic_ok": False, "groups_used": 0}

    try:
        q = pd.qcut(x, q=groups, labels=False, duplicates="drop")
    except Exception:
        return {"monotonicity_spearman": 0.0, "top_bottom_diff": 0.0, "monotonic_ok": False, "groups_used": 0}

    if q is None:
        return {"monotonicity_spearman": 0.0, "top_bottom_diff": 0.0, "monotonic_ok": False, "groups_used": 0}

    k = int(pd.Series(q).nunique())
    if k < 3:
        return {"monotonicity_spearman": 0.0, "top_bottom_diff": 0.0, "monotonic_ok": False, "groups_used": k}

    means: dict[int, float] = {}
    for gi in range(k):
        sel = q == gi
        if sel.sum() < 20:
            continue
        means[gi] = float(fwd[sel].mean())

    if len(means) < 3:
        return {"monotonicity_spearman": 0.0, "top_bottom_diff": 0.0, "monotonic_ok": False, "groups_used": k}

    ordered_means = [means[i] for i in range(k)]
    group_idx = list(range(k))
    sp = float(pd.Series(ordered_means).corr(pd.Series(group_idx), method="spearman"))
    if not math.isfinite(sp):
        sp = 0.0

    top_bottom_diff = float(max(ordered_means) - min(ordered_means))

    # 单调方向由 IC mean 决定：正 IC 期待“高因子->高收益”，负 IC 反之
    ic_mean_est = float(np.corrcoef(x.values, fwd.values)[0, 1]) if len(x) >= 2 else 0.0
    direction = 1.0 if ic_mean_est >= 0 else -1.0
    monotonic_ok = (sp * direction) >= 0.5 and top_bottom_diff > 0

    return {
        "monotonicity_spearman": round(sp, 4),
        "top_bottom_diff": round(top_bottom_diff, 6),
        "monotonic_ok": bool(monotonic_ok),
        "groups_used": k,
    }


def _turnover_proxy(
    factor: pd.Series,
    z_win: int = 20,
    signal_threshold: float = 0.0,
) -> dict[str, Any]:
    """
    换手率代理：
    - factor 做 rolling zscore
    - signal = 1 / -1（z-score 超过阈值则取符号，否则 0）
    - turnover_rate = signal 翻转次数 / 有信号的步数
    """
    x = pd.to_numeric(factor, errors="coerce").astype(float)
    mu = x.rolling(z_win, min_periods=max(2, z_win // 2)).mean()
    sd = x.rolling(z_win, min_periods=max(2, z_win // 2)).std(ddof=0).replace(0.0, np.nan)
    z = (x - mu) / sd
    sig = pd.Series(0.0, index=x.index)
    sig = sig.mask(z > signal_threshold, 1.0)
    sig = sig.mask(z < -signal_threshold, -1.0)
    non0 = sig != 0
    if non0.sum() < 80:
        return {"autocorr1": 0.0, "turnover_rate": 1.0}

    autocorr1 = float(sig[non0].autocorr(lag=1) or 0.0)
    flips = (sig != sig.shift(1)) & non0 & sig.shift(1).notna()
    turnover_rate = float(flips.sum() / max(1, non0.sum()))
    if not math.isfinite(turnover_rate):
        turnover_rate = 1.0
    if not math.isfinite(autocorr1):
        autocorr1 = 0.0
    return {"autocorr1": round(autocorr1, 4), "turnover_rate": round(turnover_rate, 4)}


def _independence_penalty(
    factor: pd.Series,
    refs: list[pd.Series],
) -> dict[str, Any]:
    if not refs:
        return {"max_abs_corr": 0.0, "mean_abs_corr": 0.0}
    corrs = []
    for r in refs:
        c = _safe_corr(factor, r)
        corrs.append(abs(c))
    if not corrs:
        return {"max_abs_corr": 0.0, "mean_abs_corr": 0.0}
    return {
        "max_abs_corr": round(float(max(corrs)), 4),
        "mean_abs_corr": round(float(np.mean(corrs)), 4),
    }


def score_factor_for_mining(
    df: pd.DataFrame,
    factor_series: pd.Series,
    *,
    interval: str = "1h",
    ic_window: int = 40,
    icir_window: int = 20,
    independence_refs: list[pd.Series] | None = None,
) -> dict[str, Any]:
    """
    返回：
    - valid: 是否通过阈值（IC、ICIR、分层单调、半衰期代理、相关性）
    - score: 0-100 分用于排序
    - metrics: 详细指标（写入 metrics_json）
    """
    if df.empty or len(df) < 80:
        return {"valid": False, "score": 0, "metrics": {"note": "数据不足"}}

    independence_refs = independence_refs or []

    # 1) IC / ICIR
    tmp = df.copy()
    tmp["_dyn_tmp_"] = factor_series
    ic_res = evaluate_factors_ic(tmp, ["_dyn_tmp_"], ic_window=ic_window, icir_window=icir_window)
    icd = (ic_res.get("factors") or {}).get("_dyn_tmp_") or {}
    ic_mean = float(icd.get("ic_mean_recent") or 0.0)
    icir = float(icd.get("icir") or 0.0)

    # 2) 分层单调性
    mono = _monotonicity_proxy(factor_series, df["close"], groups=5)

    # 3) 稳定性：half-life proxy
    half_life_bars, initial_abs_ic = _half_life_proxy_bars(factor_series, df["close"], window=ic_window)
    half_life_min = _HALF_LIFE_BAR_MIN_BY_INTERVAL.get(interval, 24)
    stability_ok = half_life_bars >= half_life_min

    # 4) 换手率代理：越稳定越好（翻转率低 / 自相关高）
    turnover = _turnover_proxy(factor_series)
    # turnover 期望：较低；这里给个经验上限：0.25（可调）
    turnover_ok = float(turnover.get("turnover_rate") or 1.0) <= 0.25

    # 5) 独立性：与旧池子相关性越低越好（max_abs_corr<=0.7）
    indep = _independence_penalty(factor_series, independence_refs)
    indep_ok = float(indep.get("max_abs_corr") or 0.0) <= 0.7

    # 6) 有效性阈值：沿用 `因子评估.md` 的核心条件
    ic_ok = abs(ic_mean) >= 0.02
    icir_ok = icir >= 0.5
    valid = bool(ic_ok and icir_ok and mono.get("monotonic_ok") and stability_ok and turnover_ok and indep_ok)

    # 7) composite score（排序用，不等同于“是否有效”）
    # ICIR 主导；单调性 + 稳定性 + turnover + 独立性做校正
    ic_score = 50.0 + 18.0 * math.atan(icir) + 10.0 * min(1.0, abs(ic_mean) / 0.04)
    mono_score = 15.0 * abs(float(mono.get("monotonicity_spearman") or 0.0))
    stability_score = 15.0 * min(1.0, half_life_bars / max(1, half_life_min))
    turnover_score = 10.0 * (1.0 - min(1.0, float(turnover.get("turnover_rate") or 1.0) / 0.4))
    indep_penalty = 20.0 * max(0.0, float(indep.get("max_abs_corr") or 0.0) - 0.3) / 0.4

    raw = ic_score + mono_score + stability_score + turnover_score - indep_penalty
    score = int(round(min(100.0, max(0.0, raw))))

    metrics: dict[str, Any] = {
        "ic_mean": round(ic_mean, 6),
        "icir": round(icir, 6),
        "rolling_ic_latest": icd.get("rolling_ic_latest"),
        "monotonicity_spearman": mono.get("monotonicity_spearman"),
        "top_bottom_diff": mono.get("top_bottom_diff"),
        "monotonic_groups_used": mono.get("groups_used"),
        "half_life_bars": int(half_life_bars),
        "half_life_min_bars": int(half_life_min),
        "initial_abs_ic": round(initial_abs_ic, 6),
        "autocorr1": turnover.get("autocorr1"),
        "turnover_rate": turnover.get("turnover_rate"),
        "max_abs_corr": indep.get("max_abs_corr"),
        "mean_abs_corr": indep.get("mean_abs_corr"),
        "valid_components": {
            "ic_ok": ic_ok,
            "icir_ok": icir_ok,
            "mono_ok": bool(mono.get("monotonic_ok")),
            "stability_ok": stability_ok,
            "turnover_ok": turnover_ok,
            "indep_ok": indep_ok,
        },
    }
    return {"valid": valid, "score": score, "metrics": metrics}

