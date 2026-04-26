"""投资组合计算服务 - 夏普比率、Beta、Alpha"""
from datetime import date, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import asc

from models.portfolio_snapshot import PortfolioSnapshot
from utils.gate_client import list_candlesticks


# 基准：BTC_USDT 作为市场代理
BENCHMARK_SYMBOL = "BTC_USDT"
BENCHMARK_INTERVAL = "1d"
# 最少需要的历史天数
MIN_DAYS = 7
# 年化因子（日收益转年化）
ANNUALIZE_FACTOR = 365 ** 0.5  # 夏普年化用 sqrt(365)
TRADING_DAYS = 365  # 年化收益用


def _mean(arr: list[float]) -> float:
    if not arr:
        return 0.0
    return sum(arr) / len(arr)


def _variance(arr: list[float], ddof: int = 0) -> float:
    if len(arr) < 2:
        return 0.0
    m = _mean(arr)
    n = len(arr) - ddof
    if n <= 0:
        return 0.0
    return sum((x - m) ** 2 for x in arr) / n


def _covariance(x: list[float], y: list[float]) -> float:
    if len(x) != len(y) or len(x) < 2:
        return 0.0
    mx, my = _mean(x), _mean(y)
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / len(x)


def _get_portfolio_daily_returns(
    db: Session, uid: int, mode: str, account_scope: str = "spot", days: int = 90
) -> list[tuple[date, float]]:
    """获取组合日收益率序列 [(date, return), ...]，return 为小数"""
    cutoff = date.today() - timedelta(days=days)
    snapshots = (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.user_id == uid,
            PortfolioSnapshot.mode == mode,
            PortfolioSnapshot.account_scope == account_scope,
            PortfolioSnapshot.date >= cutoff,
        )
        .order_by(asc(PortfolioSnapshot.date))
        .all()
    )
    result = []
    for i in range(1, len(snapshots)):
        prev_nav = float(snapshots[i - 1].nav)
        curr_nav = float(snapshots[i].nav)
        if prev_nav and prev_nav > 0:
            ret = (curr_nav - prev_nav) / prev_nav
            result.append((snapshots[i].date, ret))
    return result


def _get_benchmark_daily_returns(days: int = 90, mode: str = "real") -> list[tuple[date, float]]:
    """获取基准(BTC)日收益率序列 [(date, return), ...]"""
    candles = list_candlesticks(BENCHMARK_SYMBOL, BENCHMARK_INTERVAL, limit=min(days + 5, 200), mode=mode)
    if len(candles) < 2:
        return []
    result = []
    for i in range(1, len(candles)):
        prev_close = float(candles[i - 1]["close"])
        curr_close = float(candles[i]["close"])
        if prev_close and prev_close > 0:
            ret = (curr_close - prev_close) / prev_close
            ts = candles[i]["time"]
            d = date.fromtimestamp(ts if ts < 1e12 else ts / 1000)
            result.append((d, ret))
    return result


def _align_returns(
    portfolio_returns: list[tuple[date, float]],
    benchmark_returns: list[tuple[date, float]],
) -> tuple[list[float], list[float]]:
    """按日期对齐，返回 (portfolio_returns, benchmark_returns)"""
    bm_map = {d: r for d, r in benchmark_returns}
    pr_list, bm_list = [], []
    for d, r in portfolio_returns:
        if d in bm_map:
            pr_list.append(r)
            bm_list.append(bm_map[d])
    return pr_list, bm_list


def compute_sharpe_ratio(returns: list[float], risk_free_rate: float = 0.0) -> float | None:
    """
    夏普比率（年化）：(Rp - Rf) / σp * sqrt(365)
    无风险利率默认 0
    """
    if len(returns) < MIN_DAYS:
        return None
    mean_ret = _mean(returns)
    std_ret = (_variance(returns, ddof=1)) ** 0.5
    if std_ret <= 0:
        return None
    excess = mean_ret - risk_free_rate
    sharpe = (excess / std_ret) * ANNUALIZE_FACTOR
    return round(sharpe, 4)


def compute_beta(portfolio_returns: list[float], market_returns: list[float]) -> float | None:
    """
    Beta = Cov(Rp, Rm) / Var(Rm)
    """
    if len(portfolio_returns) != len(market_returns) or len(portfolio_returns) < MIN_DAYS:
        return None
    var_m = _variance(market_returns, ddof=1)
    if var_m <= 0:
        return None
    cov = _covariance(portfolio_returns, market_returns)
    beta = cov / var_m
    return round(beta, 4)


def compute_alpha(
    portfolio_returns: list[float],
    market_returns: list[float],
    beta: float,
    risk_free_rate: float = 0.0,
) -> float | None:
    """
    Alpha（年化）：Rp - [Rf + β(Rm - Rf)]，年化后
    Rf=0 时：Alpha = (mean(Rp) - β * mean(Rm)) * 365
    """
    if len(portfolio_returns) != len(market_returns) or len(portfolio_returns) < MIN_DAYS:
        return None
    mean_rp = _mean(portfolio_returns)
    mean_rm = _mean(market_returns)
    # 日度 Alpha 年化
    alpha_daily = mean_rp - (risk_free_rate + beta * (mean_rm - risk_free_rate))
    alpha_annual = alpha_daily * TRADING_DAYS
    return round(alpha_annual, 4)


def compute_portfolio_metrics(db: Session, uid: int, mode: str, account_scope: str = "spot") -> dict:
    """
    计算夏普、Beta、Alpha。
    返回 {"sharpe": float|None, "beta": float|None, "alpha": float|None}
    """
    result = {"sharpe": None, "beta": None, "alpha": None}
    pr_tuples = _get_portfolio_daily_returns(db, uid, mode, account_scope)
    if len(pr_tuples) < MIN_DAYS:
        return result
    bm_tuples = _get_benchmark_daily_returns(days=120, mode=mode)
    if len(bm_tuples) < MIN_DAYS:
        return result
    pr_list, bm_list = _align_returns(pr_tuples, bm_tuples)
    if len(pr_list) < MIN_DAYS:
        return result
    result["sharpe"] = compute_sharpe_ratio(pr_list)
    result["beta"] = compute_beta(pr_list, bm_list)
    if result["beta"] is not None:
        result["alpha"] = compute_alpha(pr_list, bm_list, result["beta"])
    return result
