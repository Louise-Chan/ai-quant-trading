"""技术指标与基础因子（仅使用历史数据，无未来函数）"""
from __future__ import annotations

import numpy as np  # pyright: ignore[reportMissingImports]
import pandas as pd  # pyright: ignore[reportMissingImports]


def candles_to_df(candles: list[dict]) -> pd.DataFrame:
    if not candles:
        return pd.DataFrame()
    df = pd.DataFrame(candles)
    if "time" in df.columns:
        df = df.sort_values("time").reset_index(drop=True)
    else:
        # 无时间戳时假定列表已按时间升序
        df = df.reset_index(drop=True)
    for c in ("open", "high", "low", "close", "volume"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "close" not in df.columns or df["close"].isna().all():
        return pd.DataFrame()
    # 缺 OHLC 时用 close 补齐，避免部分数据源只有收盘价
    c0 = df["close"]
    if "open" not in df.columns:
        df["open"] = c0
    if "high" not in df.columns:
        df["high"] = c0
    if "low" not in df.columns:
        df["low"] = c0
    if "volume" not in df.columns:
        df["volume"] = 0.0
    return df.dropna(subset=["close"])


def add_factor_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """在 df 上增加因子列（因果：第 t 行只依赖 <=t 的 K 线）"""
    if df.empty or len(df) < 30:
        return df, []
    o = df["open"].astype(float)
    h = df["high"].astype(float)
    low = df["low"].astype(float)
    c = df["close"].astype(float)
    v = df["volume"].astype(float).replace(0, np.nan)

    df = df.copy()
    df["ret_1"] = c.pct_change()
    # 动量 / 反转
    df["mom_5"] = c / c.shift(5) - 1.0
    df["mom_10"] = c / c.shift(10) - 1.0
    df["rev_1"] = -df["ret_1"]
    # 波动
    df["vol_20"] = df["ret_1"].rolling(20, min_periods=10).std()
    # RSI 14
    delta = c.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    ag = gain.rolling(14, min_periods=7).mean()
    al = loss.rolling(14, min_periods=7).mean()
    rs = ag / al.replace(0, np.nan)
    df["rsi_14"] = 100.0 - (100.0 / (1.0 + rs))
    # 布林带位置
    ma20 = c.rolling(20, min_periods=10).mean()
    sd20 = c.rolling(20, min_periods=10).std()
    df["bb_pos"] = (c - ma20) / (2 * sd20).replace(0, np.nan)
    # 成交量异常
    vma = v.rolling(20, min_periods=10).mean()
    df["vol_z"] = (v - vma) / vma.replace(0, np.nan)
    # ATR 14
    tr = pd.concat([h - low, (h - c.shift(1)).abs(), (low - c.shift(1)).abs()], axis=1).max(axis=1)
    df["atr_14"] = tr.rolling(14, min_periods=7).mean()
    # MACD 简化
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    df["macd_hist"] = macd - signal

    factor_cols = [
        "mom_5",
        "mom_10",
        "rev_1",
        "vol_20",
        "rsi_14",
        "bb_pos",
        "vol_z",
        "macd_hist",
    ]
    for col in factor_cols:
        df[col] = df[col].replace([np.inf, -np.inf], np.nan)

    # Qlib / VNPy Alpha158（158）+ 经典价量（5），见 alpha158.py
    if len(df) >= 65:
        from services.strategy_engine.alpha158 import add_alpha158_columns

        df, a158_cols = add_alpha158_columns(df)
        factor_cols = factor_cols + a158_cols

    return df, factor_cols


_LEGACY_LIBRARY: list[dict[str, str]] = [
    {"id": "mom_5", "name": "5 期动量", "description": "收盘价相对 5 根 K 前的收益率"},
    {"id": "mom_10", "name": "10 期动量", "description": "收盘价相对 10 根 K 前的收益率"},
    {"id": "rev_1", "name": "1 期反转", "description": "与上一根涨跌幅相反（短期反转）"},
    {"id": "vol_20", "name": "20 期波动", "description": "日收益率滚动标准差"},
    {"id": "rsi_14", "name": "RSI(14)", "description": "相对强弱指标"},
    {"id": "bb_pos", "name": "布林带位置", "description": "价格相对 20 均线与 2 倍标准差带的位置"},
    {"id": "vol_z", "name": "成交量 Z", "description": "成交量相对 20 期均量的偏离"},
    {"id": "macd_hist", "name": "MACD 柱", "description": "MACD 与信号线之差"},
]


def _build_factor_library() -> list[dict[str, str]]:
    from services.strategy_engine.alpha158 import alpha158_factor_library_entries

    return list(_LEGACY_LIBRARY) + alpha158_factor_library_entries()


# 前端因子库 / API 展示用（与 add_factor_columns 返回的 factor_cols 顺序一致）
FACTOR_LIBRARY: list[dict[str, str]] = _build_factor_library()

# 内置策略模板默认勾选因子（注册时默认用户策略、回测页加载内置模板与之一致）
DEFAULT_BUILTIN_FACTOR_IDS: tuple[str, ...] = ("rev_1", "vol_20", "vol_z")


def default_factor_ids() -> list[str]:
    return [x["id"] for x in FACTOR_LIBRARY]


def resolve_active_factor_cols(all_cols: list[str], selected: list[str] | None) -> list[str]:
    """
    selected 为空或无效时退回全部 all_cols；否则仅保留在 all_cols 中且被点名的因子（至少 1 个）。
    """
    if not all_cols:
        return []
    if not selected:
        return list(all_cols)
    s = {str(x).strip() for x in selected if str(x).strip()}
    out = [c for c in all_cols if c in s]
    return out if len(out) >= 1 else list(all_cols)


def latest_factor_snapshot(df: pd.DataFrame, factor_cols: list[str]) -> dict:
    if df.empty:
        return {}
    last = df.iloc[-1]
    out = {}
    for col in factor_cols:
        if col in df.columns:
            val = last.get(col)
            out[col] = None if pd.isna(val) else float(val)
    return out
