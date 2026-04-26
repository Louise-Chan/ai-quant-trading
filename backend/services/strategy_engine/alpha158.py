"""
Qlib / VNPy Alpha158 风格因子（单标的 OHLCV，与 vnpy.alpha.dataset.datasets.alpha_158 公式对齐）

参考：https://github.com/vnpy/vnpy/blob/master/vnpy/alpha/dataset/datasets/alpha_158.py
仅使用截至当前 K 线的历史，无未来函数。VWAP 用典型价成交量滚动近似（无逐笔时业界常用做法）。
另附若干开源社区常用的经典价量因子（MFI / Williams %R / 随机指标 / CCI / OBV）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd  # pyright: ignore[reportMissingImports]
from scipy import stats  # pyright: ignore[reportMissingImports]

_WINDOWS = (5, 10, 20, 30, 60)
_EPS = 1e-12


def _rolling_slope(y: pd.Series, window: int) -> pd.Series:
    x = np.arange(window, dtype=float)
    sx, sxx = float(x.sum()), float((x**2).sum())
    denom = window * sxx - sx * sx
    if abs(denom) < _EPS:
        return pd.Series(np.nan, index=y.index)

    def slope(arr: np.ndarray) -> float:
        if np.any(~np.isfinite(arr)):
            return np.nan
        sy = float(arr.sum())
        sxy = float(np.dot(x, arr))
        return (window * sxy - sx * sy) / denom

    return y.rolling(window, min_periods=window).apply(slope, raw=True)


def _rolling_rsquare(y: pd.Series, window: int) -> pd.Series:
    n = window
    sum_x2 = (n - 1) * n * (2 * n - 1) / 6.0
    mean_x = (n - 1) / 2.0
    var_x = sum_x2 / n - mean_x * mean_x
    if var_x < _EPS:
        return pd.Series(np.nan, index=y.index)
    x = np.arange(window, dtype=float)

    def rsq(arr: np.ndarray) -> float:
        if np.any(~np.isfinite(arr)):
            return np.nan
        mean_y = float(arr.mean())
        var_y = float(arr.var(ddof=0))
        if var_y < _EPS:
            return np.nan
        sxy = float(np.dot(x, arr))
        cov_xy = sxy / n - mean_x * mean_y
        r2 = (cov_xy**2) / (var_x * var_y)
        return float(r2) if np.isfinite(r2) else np.nan

    return y.rolling(window, min_periods=window).apply(rsq, raw=True)


def _rolling_resi(y: pd.Series, window: int) -> pd.Series:
    n = window
    x = np.arange(n, dtype=float)
    sx = float(x.sum())
    sxx = float((x**2).sum())
    denom = n * sxx - sx * sx
    if abs(denom) < _EPS:
        return pd.Series(np.nan, index=y.index)

    def resi(arr: np.ndarray) -> float:
        if np.any(~np.isfinite(arr)):
            return np.nan
        sy = float(arr.sum())
        sxy = float(np.dot(x, arr))
        slope = (n * sxy - sx * sy) / denom
        mean_y = sy / n
        intercept = mean_y - slope * ((n - 1) / 2.0)
        y_last = float(arr[-1])
        return y_last - (slope * (n - 1) + intercept)

    return y.rolling(window, min_periods=window).apply(resi, raw=True)


def _rolling_rank_pct(y: pd.Series, window: int) -> pd.Series:
    def rank_last(arr: np.ndarray) -> float:
        if np.any(~np.isfinite(arr)):
            return np.nan
        return float(stats.percentileofscore(arr, arr[-1], kind="rank")) / 100.0

    return y.rolling(window, min_periods=max(3, window // 2)).apply(rank_last, raw=True)


def _rolling_argmax(s: pd.Series, window: int) -> pd.Series:
    def f(arr: np.ndarray) -> float:
        if np.any(~np.isfinite(arr)):
            return np.nan
        return float(np.argmax(arr) + 1)

    return s.rolling(window, min_periods=max(2, window // 3)).apply(f, raw=True)


def _rolling_argmin(s: pd.Series, window: int) -> pd.Series:
    def f(arr: np.ndarray) -> float:
        if np.any(~np.isfinite(arr)):
            return np.nan
        return float(np.argmin(arr) + 1)

    return s.rolling(window, min_periods=max(2, window // 3)).apply(f, raw=True)


def _rolling_corr(a: pd.Series, b: pd.Series, window: int) -> pd.Series:
    return a.rolling(window, min_periods=max(3, window // 2)).corr(b)


def add_alpha158_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """在已有 open/high/low/close/volume 的 df 上追加 Alpha158 + 经典因子列。"""
    if df.empty or len(df) < 65:
        return df, []

    out = df.copy()
    o = out["open"].astype(float)
    h = out["high"].astype(float)
    low = out["low"].astype(float)
    c = out["close"].astype(float)
    v = out["volume"].astype(float).clip(lower=0.0)

    cols: list[str] = []

    # —— K 线结构（9）——
    mx_oc = np.maximum(o, c)
    mn_oc = np.minimum(o, c)
    hl = h - low + _EPS
    out["a158_kmid"] = (c - o) / (o + _EPS)
    out["a158_klen"] = (h - low) / (o + _EPS)
    out["a158_kmid_2"] = (c - o) / hl
    out["a158_kup"] = (h - mx_oc) / (o + _EPS)
    out["a158_kup_2"] = (h - mx_oc) / hl
    out["a158_klow"] = (mn_oc - low) / (o + _EPS)
    out["a158_klow_2"] = (mn_oc - low) / hl
    out["a158_ksft"] = (c * 2.0 - h - low) / (o + _EPS)
    out["a158_ksft_2"] = (c * 2.0 - h - low) / hl
    cols += [
        "a158_kmid",
        "a158_klen",
        "a158_kmid_2",
        "a158_kup",
        "a158_kup_2",
        "a158_klow",
        "a158_klow_2",
        "a158_ksft",
        "a158_ksft_2",
    ]

    # VWAP 近似：滚动典型价 × 成交量 / 成交量
    tp = (h + low + c) / 3.0
    vw = (tp * v).rolling(30, min_periods=10).sum() / (v.rolling(30, min_periods=10).sum() + _EPS)
    out["a158_open_0"] = o / (c + _EPS)
    out["a158_high_0"] = h / (c + _EPS)
    out["a158_low_0"] = low / (c + _EPS)
    out["a158_vwap_0"] = vw / (c + _EPS)
    cols += ["a158_open_0", "a158_high_0", "a158_low_0", "a158_vwap_0"]

    log_v = np.log(v + 1.0)
    c_lag1 = c.shift(1)
    v_lag1 = v.shift(1)
    ret1 = c / (c_lag1 + _EPS)
    log_v_ratio = np.log(v / (v_lag1 + _EPS) + 1.0)
    abs_ret = (c - c_lag1).abs()
    abs_dv = (v - v_lag1).abs()

    for w in _WINDOWS:
        out[f"a158_roc_{w}"] = c.shift(w) / (c + _EPS)
        out[f"a158_ma_{w}"] = c.rolling(w, min_periods=max(2, w // 2)).mean() / (c + _EPS)
        out[f"a158_std_{w}"] = c.rolling(w, min_periods=max(2, w // 2)).std(ddof=0) / (c + _EPS)
        out[f"a158_beta_{w}"] = _rolling_slope(c, w) / (c + _EPS)
        out[f"a158_rsqr_{w}"] = _rolling_rsquare(c, w)
        out[f"a158_resi_{w}"] = _rolling_resi(c, w) / (c + _EPS)
        out[f"a158_max_{w}"] = h.rolling(w, min_periods=max(2, w // 2)).max() / (c + _EPS)
        out[f"a158_min_{w}"] = low.rolling(w, min_periods=max(2, w // 2)).min() / (c + _EPS)
        out[f"a158_qtlu_{w}"] = (
            c.rolling(w, min_periods=max(2, w // 2)).quantile(0.8) / (c + _EPS)
        )
        out[f"a158_qtld_{w}"] = (
            c.rolling(w, min_periods=max(2, w // 2)).quantile(0.2) / (c + _EPS)
        )
        out[f"a158_rank_{w}"] = _rolling_rank_pct(c, w)
        hi_m = h.rolling(w, min_periods=max(2, w // 2)).max()
        lo_m = low.rolling(w, min_periods=max(2, w // 2)).min()
        out[f"a158_rsv_{w}"] = (c - lo_m) / (hi_m - lo_m + _EPS)
        amx = _rolling_argmax(h, w)
        amn = _rolling_argmin(low, w)
        out[f"a158_imax_{w}"] = amx / float(w)
        out[f"a158_imin_{w}"] = amn / float(w)
        out[f"a158_imxd_{w}"] = (amx - amn) / float(w)
        out[f"a158_corr_{w}"] = _rolling_corr(c, log_v, w)
        out[f"a158_cord_{w}"] = _rolling_corr(ret1, log_v_ratio, w)
        up = (c > c_lag1).astype(float)
        dn = (c < c_lag1).astype(float)
        out[f"a158_cntp_{w}"] = up.rolling(w, min_periods=max(2, w // 2)).mean()
        out[f"a158_cntn_{w}"] = dn.rolling(w, min_periods=max(2, w // 2)).mean()
        out[f"a158_cntd_{w}"] = out[f"a158_cntp_{w}"] - out[f"a158_cntn_{w}"]

        pos_r = (c - c_lag1).clip(lower=0.0)
        neg_r = (c_lag1 - c).clip(lower=0.0)
        sum_abs_r = abs_ret.rolling(w, min_periods=max(2, w // 2)).sum() + _EPS
        out[f"a158_sump_{w}"] = pos_r.rolling(w, min_periods=max(2, w // 2)).sum() / sum_abs_r
        out[f"a158_sumn_{w}"] = neg_r.rolling(w, min_periods=max(2, w // 2)).sum() / sum_abs_r
        out[f"a158_sumd_{w}"] = out[f"a158_sump_{w}"] - out[f"a158_sumn_{w}"]

        out[f"a158_vma_{w}"] = v.rolling(w, min_periods=max(2, w // 2)).mean() / (v + _EPS)
        out[f"a158_vstd_{w}"] = v.rolling(w, min_periods=max(2, w // 2)).std(ddof=0) / (v + _EPS)
        vl = abs_ret * v
        out[f"a158_wvma_{w}"] = vl.rolling(w, min_periods=max(2, w // 2)).std(ddof=0) / (
            vl.rolling(w, min_periods=max(2, w // 2)).mean() + _EPS
        )

        pv = (v - v_lag1).clip(lower=0.0)
        nv = (v_lag1 - v).clip(lower=0.0)
        sum_abs_dv = abs_dv.rolling(w, min_periods=max(2, w // 2)).sum() + _EPS
        out[f"a158_vsump_{w}"] = pv.rolling(w, min_periods=max(2, w // 2)).sum() / sum_abs_dv
        out[f"a158_vsumn_{w}"] = nv.rolling(w, min_periods=max(2, w // 2)).sum() / sum_abs_dv
        out[f"a158_vsumd_{w}"] = out[f"a158_vsump_{w}"] - out[f"a158_vsumn_{w}"]

        for suffix in (
            f"roc_{w}",
            f"ma_{w}",
            f"std_{w}",
            f"beta_{w}",
            f"rsqr_{w}",
            f"resi_{w}",
            f"max_{w}",
            f"min_{w}",
            f"qtlu_{w}",
            f"qtld_{w}",
            f"rank_{w}",
            f"rsv_{w}",
            f"imax_{w}",
            f"imin_{w}",
            f"imxd_{w}",
            f"corr_{w}",
            f"cord_{w}",
            f"cntp_{w}",
            f"cntn_{w}",
            f"cntd_{w}",
            f"sump_{w}",
            f"sumn_{w}",
            f"sumd_{w}",
            f"vma_{w}",
            f"vstd_{w}",
            f"wvma_{w}",
            f"vsump_{w}",
            f"vsumn_{w}",
            f"vsumd_{w}",
        ):
            cols.append(f"a158_{suffix}")

    # —— 经典价量（开源 TA / 文献常用）——
    typ = (h + low + c) / 3.0
    mf = typ * v
    pos_mf = mf.where(typ > typ.shift(1), 0.0).rolling(14, min_periods=7).sum()
    neg_mf = mf.where(typ < typ.shift(1), 0.0).rolling(14, min_periods=7).sum()
    mfr = pos_mf / (neg_mf + _EPS)
    out["cls_mfi_14"] = 100.0 - (100.0 / (1.0 + mfr))
    out["cls_mfi_14"] = (out["cls_mfi_14"] - 50.0) / 50.0

    hh14 = h.rolling(14, min_periods=7).max()
    ll14 = low.rolling(14, min_periods=7).min()
    out["cls_wr_14"] = (hh14 - c) / (hh14 - ll14 + _EPS) * (-1.0)

    hh10 = h.rolling(14, min_periods=7).max()
    ll10 = low.rolling(14, min_periods=7).min()
    out["cls_stoch_k_14"] = (c - ll10) / (hh10 - ll10 + _EPS)

    tp_ma = typ.rolling(20, min_periods=10).mean()
    mad = (typ - tp_ma).abs().rolling(20, min_periods=10).mean()
    out["cls_cci_20"] = (typ - tp_ma) / (0.015 * mad + _EPS)

    obv = (np.sign(c.diff().fillna(0.0)) * v).cumsum()
    out["cls_obv_slope_20"] = _rolling_slope(obv, 20) / (obv.abs().clip(lower=1.0) + _EPS)

    cols += ["cls_mfi_14", "cls_wr_14", "cls_stoch_k_14", "cls_cci_20", "cls_obv_slope_20"]

    # —— WorldQuant Alpha101 选摘：alpha_001 / alpha_002（修改为因果截面退化为时序近似）——
    # alpha_001: rank(Ts_ArgMax(SignedPower((ret<0 ? std(ret,20) : close), 2), 5)) - 0.5
    ret_1bar = c.pct_change()
    std_ret_20 = ret_1bar.rolling(20, min_periods=10).std(ddof=0)
    base_a1 = ret_1bar.where(ret_1bar < 0, c).where(~ret_1bar.isna(), np.nan)
    base_a1 = base_a1.mask(ret_1bar < 0, std_ret_20)
    signed_sq = np.sign(base_a1) * (base_a1.abs() ** 2)
    argmax5 = _rolling_argmax(signed_sq, 5) / 5.0
    out["a158_alpha_001"] = _rolling_rank_pct(argmax5, 60) - 0.5

    # alpha_002: -1 * corr(rank(delta(log(volume), 2)), rank((close-open)/open), 6)
    log_v_full = np.log(v.replace(0, np.nan)).fillna(0.0)
    delta_logv_2 = log_v_full.diff(2)
    intraday_ret = (c - o) / (o + _EPS)
    rank_delta_logv = _rolling_rank_pct(delta_logv_2, 60)
    rank_intra = _rolling_rank_pct(intraday_ret, 60)
    out["a158_alpha_002"] = -_rolling_corr(rank_delta_logv, rank_intra, 6)

    cols += ["a158_alpha_001", "a158_alpha_002"]

    # —— 经典量比（5 日平均量）与 ATR14（/close 归一化） ——
    vol_ma5 = v.rolling(5, min_periods=3).mean().replace(0, np.nan)
    out["cls_volume_ratio"] = v / vol_ma5 - 1.0

    tr_cls = pd.concat(
        [h - low, (h - c.shift(1)).abs(), (low - c.shift(1)).abs()], axis=1
    ).max(axis=1)
    out["cls_atr_14"] = tr_cls.rolling(14, min_periods=7).mean() / (c + _EPS)

    cols += ["cls_volume_ratio", "cls_atr_14"]

    for col in cols:
        if col in out.columns:
            out[col] = out[col].replace([np.inf, -np.inf], np.nan)

    return out, cols


def alpha158_factor_library_entries() -> list[dict[str, str]]:
    """供 FACTOR_LIBRARY 合并：Alpha158 元数据 + 经典因子说明。"""
    entries: list[dict[str, str]] = [
        {"id": "a158_kmid", "name": "A158 KMID", "description": "K 线实体相对开盘价：(c-o)/o（Qlib Alpha158）"},
        {"id": "a158_klen", "name": "A158 KLEN", "description": "振幅相对开盘价：(h-l)/o"},
        {"id": "a158_kmid_2", "name": "A158 KMID2", "description": "实体占振幅比例：(c-o)/(h-l)"},
        {"id": "a158_kup", "name": "A158 KUP", "description": "上影相对开盘：(h-max(o,c))/o"},
        {"id": "a158_kup_2", "name": "A158 KUP2", "description": "上影占振幅比例"},
        {"id": "a158_klow", "name": "A158 KLOW", "description": "下影相对开盘：(min(o,c)-l)/o"},
        {"id": "a158_klow_2", "name": "A158 KLOW2", "description": "下影占振幅比例"},
        {"id": "a158_ksft", "name": "A158 KSFT", "description": "收盘在 bar 内位置（相对开盘）"},
        {"id": "a158_ksft_2", "name": "A158 KSFT2", "description": "收盘在 bar 内位置（占振幅）"},
        {"id": "a158_open_0", "name": "A158 OPEN0", "description": "open/close"},
        {"id": "a158_high_0", "name": "A158 HIGH0", "description": "high/close"},
        {"id": "a158_low_0", "name": "A158 LOW0", "description": "low/close"},
        {
            "id": "a158_vwap_0",
            "name": "A158 VWAP0",
            "description": "滚动 VWAP 近似/close（典型价×量滚动，无逐笔时的常用替代）",
        },
    ]
    labels = {
        "roc": "滞后收盘比：close[t-w]/close[t]（VNPy ts_delay(close,w)/close）",
        "ma": "均线比：mean(close,w)/close",
        "std": "滚动标准差/close",
        "beta": "价序列线性趋势斜率/close",
        "rsqr": "价对时间的回归 R²",
        "resi": "价对时间回归残差/close",
        "max": "滚动最高价/close",
        "min": "滚动最低价/close",
        "qtlu": "80% 分位价/close",
        "qtld": "20% 分位价/close",
        "rank": "当前价在窗口内的分位秩 [0,1]",
        "rsv": "随机指标核心：(c-min_low)/(max_high-min_low)",
        "imax": "最高价出现在窗口内的位置（归一化）",
        "imin": "最低价出现位置（归一化）",
        "imxd": "最高/最低出现位置差（归一化）",
        "corr": "收盘价与 log(volume+1) 滚动相关",
        "cord": "涨跌幅与成交量变化 log 比滚动相关",
        "cntp": "上涨根数占比",
        "cntn": "下跌根数占比",
        "cntd": "涨跌根数占比差",
        "sump": "上涨幅度占绝对收益和比例",
        "sumn": "下跌幅度占绝对收益和比例",
        "sumd": "涨跌幅度不对称度",
        "vma": "均量/当前量",
        "vstd": "量标准差/当前量",
        "wvma": "量价波动项的变异系数类指标",
        "vsump": "放量占成交量绝对变化比例",
        "vsumn": "缩量占成交量绝对变化比例",
        "vsumd": "量能变化不对称度",
    }
    for w in _WINDOWS:
        for key, desc in labels.items():
            entries.append(
                {
                    "id": f"a158_{key}_{w}",
                    "name": f"A158 {key.upper()}({w})",
                    "description": f"w={w}：{desc}",
                }
            )
    entries += [
        {
            "id": "cls_mfi_14",
            "name": "经典 MFI(14)",
            "description": "资金流量指标（量价），归一化到约 [-1,1] 区间",
        },
        {
            "id": "cls_wr_14",
            "name": "经典 Williams %R(14)",
            "description": "超买超卖类动量，开源 TA-Lib 常见实现",
        },
        {
            "id": "cls_stoch_k_14",
            "name": "经典随机 %K(14)",
            "description": "随机振荡器主线，广泛用于回测筛选",
        },
        {
            "id": "cls_cci_20",
            "name": "经典 CCI(20)",
            "description": "商品通道指数，趋势/偏离度",
        },
        {
            "id": "cls_obv_slope_20",
            "name": "经典 OBV 斜率(20)",
            "description": "能量潮 20 期线性斜率（归一化），量价背离常用",
        },
        {
            "id": "cls_volume_ratio",
            "name": "经典量比(5)",
            "description": "当前成交量 / 过去 5 期均量 − 1，>0 表示放量、<0 缩量",
        },
        {
            "id": "cls_atr_14",
            "name": "经典 ATR(14)/close",
            "description": "14 期平均真实波幅除以收盘价，衡量波动相对强度",
        },
        {
            "id": "a158_alpha_001",
            "name": "Alpha101 #1",
            "description": "rank(Ts_ArgMax(SignedPower(cond, 2), 5))-0.5：上涨时看 close、下跌时看 ret 波动的位置因子",
        },
        {
            "id": "a158_alpha_002",
            "name": "Alpha101 #2",
            "description": "−corr(rank Δ log(volume,2), rank 日内涨跌幅, 6)：放量与日内方向的逆向相关",
        },
    ]
    return entries
