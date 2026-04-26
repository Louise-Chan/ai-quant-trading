"""简化回测：信号仅基于历史因子，收益为下一根 K 线；无未来函数"""
from __future__ import annotations

import numpy as np  # pyright: ignore[reportMissingImports]
import pandas as pd  # pyright: ignore[reportMissingImports]


def _extract_trade_events_masked(
    df: pd.DataFrame, signal: pd.Series, mask: pd.Series, max_events: int = 2500
) -> tuple[list[dict], bool]:
    """
    与 open_count 一致：仅在 mask 为 True 的 bar 序列上检测 0→1（开仓）与 1→0（平仓）。
    bar_index 为回测 df 的行号（与 candles_to_df 排序后一致）。
    """
    sig_aligned = signal.iloc[:-1]
    mask = mask.reindex(sig_aligned.index).fillna(False)
    sig_masked = sig_aligned[mask]
    if sig_masked.empty:
        return [], False
    idxs = [int(i) for i in sig_masked.index.tolist()]
    pos = (sig_masked > 0.5).astype(int)
    events: list[dict] = []
    prev = 0
    for k in range(len(idxs)):
        cur = int(pos.iloc[k])
        bi = idxs[k]
        if cur == 1 and prev == 0:
            events.append({"kind": "open", "bar_index": bi})
        elif cur == 0 and prev == 1:
            events.append({"kind": "close", "bar_index": bi})
        prev = cur
    for ev in events:
        bi = int(ev["bar_index"])
        if not (0 <= bi < len(df)):
            if "time" in df.columns:
                ev["time"] = None
            continue
        if "close" in df.columns:
            try:
                p = float(pd.to_numeric(df.iloc[bi]["close"], errors="coerce"))
                if np.isfinite(p):
                    ev["price"] = round(p, 8)
            except (TypeError, ValueError):
                pass
        if "time" in df.columns:
            tv = df.iloc[bi]["time"]
            try:
                t = float(tv)
                if t > 10_000_000_000:
                    t = t / 1000.0
                ev["time"] = int(t)
            except (TypeError, ValueError):
                ev["time"] = None
    truncated = len(events) > max_events
    if truncated:
        events = events[:max_events]
    return events, truncated


def composite_score_series(df: pd.DataFrame, factor_cols: list[str], weights: dict[str, float]) -> pd.Series:
    if df.empty or not factor_cols:
        return pd.Series(0.0, index=df.index)
    wsum = sum(weights.get(c, 0) for c in factor_cols) or 1.0
    if wsum < 1e-9:
        weights = {c: 1.0 / len(factor_cols) for c in factor_cols}
        wsum = 1.0
    z = pd.DataFrame(index=df.index)
    for c in factor_cols:
        if c not in df.columns:
            continue
        mu = df[c].rolling(60, min_periods=20).mean()
        sd = df[c].rolling(60, min_periods=20).std().replace(0, np.nan)
        z[c] = ((df[c] - mu) / sd).fillna(0.0)
    score = np.zeros(len(df))
    for c in factor_cols:
        if c in z.columns:
            score += z[c].values * (weights.get(c, 0) / wsum)
    return pd.Series(score, index=df.index)


def run_simple_backtest(
    df: pd.DataFrame,
    factor_cols: list[str],
    weights: dict[str, float],
    quantile_threshold: float = 0.55,
    bars_per_year: float = 24 * 365,
    max_opens_per_day: int | None = None,
    avg_daily_mode: str = "trading",
    include_per_bar: bool = False,
    include_trade_events: bool = False,
) -> dict:
    if df.empty or len(df) < 80:
        return {"ok": False, "reason": "数据不足以回测"}

    score = composite_score_series(df, factor_cols, weights)
    q = score.rolling(80, min_periods=40).quantile(quantile_threshold)
    signal = (score > q).astype(float)
    day_series = None
    if "time" in df.columns:
        tser = pd.to_numeric(df["time"], errors="coerce")
        # Gate time 多为秒；若为毫秒则折算
        tser = tser.where(tser <= 10_000_000_000, tser / 1000.0)
        day_series = pd.to_datetime(tser, unit="s", utc=True, errors="coerce").dt.strftime("%Y-%m-%d")

    # 限制每天最多开仓次数：仅限制 0->1 的入场事件
    if max_opens_per_day is not None and int(max_opens_per_day) > 0 and day_series is not None:
        cap = int(max_opens_per_day)
        sig_adj = signal.astype(int).copy()
        prev_pos = 0
        current_day = ""
        opens_today = 0
        for i in range(len(sig_adj)):
            day_key = str(day_series.iloc[i] or "")
            if day_key != current_day:
                current_day = day_key
                opens_today = 0
            desired = int(sig_adj.iloc[i] > 0)
            if desired == 1 and prev_pos == 0:
                if opens_today >= cap:
                    desired = 0
                else:
                    opens_today += 1
            sig_adj.iloc[i] = desired
            prev_pos = desired
        signal = sig_adj.astype(float)
    next_ret = df["close"].astype(float).pct_change().shift(-1)
    raw_next = next_ret.iloc[:-1]
    raw_strat = (signal * next_ret).iloc[:-1]
    mask = raw_strat.notna() & raw_next.notna()
    pnl = raw_strat[mask]
    bench_pnl = raw_next[mask]
    # 与 pnl 对齐的持仓信号：由空转多（0→1）计为一次开仓
    sig_aligned = signal.iloc[:-1]
    sig_masked = sig_aligned[mask]
    pos = (sig_masked > 0.5).astype(int)
    if len(pos) == 0:
        open_count = 0
    else:
        prev = pos.shift(1).fillna(0)
        open_count = int(((pos == 1) & (prev == 0)).sum())
    if day_series is not None:
        day_masked = day_series.iloc[:-1][mask]
        trading_days = max(1, int(day_masked.nunique()) if len(day_masked) else 0)
        natural_days = trading_days
        try:
            if len(day_masked):
                first_day = str(day_masked.iloc[0])
                last_day = str(day_masked.iloc[-1])
                if first_day and last_day:
                    d0 = pd.to_datetime(first_day, utc=True, errors="coerce")
                    d1 = pd.to_datetime(last_day, utc=True, errors="coerce")
                    if pd.notna(d0) and pd.notna(d1):
                        natural_days = max(1, int((d1.date() - d0.date()).days) + 1)
        except Exception:
            natural_days = trading_days
        avg_daily_open_count_trading = float(open_count / trading_days)
        avg_daily_open_count_natural = float(open_count / max(1, natural_days))
    else:
        bars_per_day = max(1.0, float(bars_per_year) / 365.0)
        est_days = max(1.0, float(len(pnl)) / bars_per_day)
        avg_daily_open_count_trading = float(open_count / est_days)
        avg_daily_open_count_natural = float(open_count / est_days)
    mode = "natural" if str(avg_daily_mode or "").strip().lower() == "natural" else "trading"
    avg_daily_open_count = (
        avg_daily_open_count_natural if mode == "natural" else avg_daily_open_count_trading
    )
    if len(pnl) < 10:
        return {"ok": False, "reason": "有效回测样本过少"}

    equity = (1.0 + pnl).cumprod()
    bench_equity = (1.0 + bench_pnl).cumprod()
    total_ret = float(equity.iloc[-1] - 1.0)
    bench_total_ret = float(bench_equity.iloc[-1] - 1.0)
    alpha_vs_buyhold = float(total_ret - bench_total_ret)
    vol = float(pnl.std()) or 1e-9
    sharpe = float(np.sqrt(bars_per_year) * pnl.mean() / vol) if vol > 0 else 0.0

    peak = equity.cummax()
    dd = (equity / peak - 1.0).min()
    max_dd = float(dd)

    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    win_rate = float((pnl > 0).mean())
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0
    # avg_loss 为负；盈亏比 = 总盈利 / 总亏损绝对值
    gross_win = avg_win * len(wins)
    gross_loss_abs = abs(avg_loss) * len(losses)
    profit_factor = (gross_win / gross_loss_abs) if len(losses) and gross_loss_abs > 1e-12 else None

    def _downsample_curve(vals: list[float], max_points: int = 480) -> list[dict]:
        n = len(vals)
        if n <= max_points:
            return [{"i": i, "v": round(float(vals[i]), 6)} for i in range(n)]
        step = max(1, n // max_points)
        out = []
        for i in range(0, n, step):
            out.append({"i": i, "v": round(float(vals[i]), 6)})
        if out[-1]["i"] != n - 1:
            out.append({"i": n - 1, "v": round(float(vals[-1]), 6)})
        return out

    eq_list = equity.tolist()
    b_eq_list = bench_equity.tolist()

    out = {
        "ok": True,
        "bars": int(len(pnl)),
        "open_count": int(open_count),
        "avg_daily_open_count": round(avg_daily_open_count, 4),
        "avg_daily_open_count_trading": round(avg_daily_open_count_trading, 4),
        "avg_daily_open_count_natural": round(avg_daily_open_count_natural, 4),
        "avg_daily_mode": mode,
        "total_return": round(total_ret, 4),
        "benchmark_total_return": round(bench_total_ret, 4),
        "alpha_vs_buyhold": round(alpha_vs_buyhold, 4),
        "sharpe_approx": round(sharpe, 4),
        "max_drawdown": round(max_dd, 4),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
        "avg_win": round(avg_win, 6),
        "avg_loss": round(avg_loss, 6),
        "equity_curve": _downsample_curve(eq_list),
        "benchmark_curve": _downsample_curve(b_eq_list),
        "note": "单标的、按 K 线持有至下一根；不含手续费与滑点；Alpha 为相对同期买入持有的超额收益",
    }
    if include_per_bar:
        out["per_bar_pnl"] = [round(float(x), 8) for x in pnl.tolist()]
        out["per_bar_bench"] = [round(float(x), 8) for x in bench_pnl.tolist()]
    if include_trade_events:
        ev, trunc = _extract_trade_events_masked(df, signal, mask)
        out["trade_events"] = ev
        if trunc:
            out["trade_events_truncated"] = True
    return out
