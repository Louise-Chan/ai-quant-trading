"""机器学习信号：逻辑回归预测短期上涨概率（特征为标准化因子）

``df`` 须为 ``pandas.DataFrame``。顶层不导入 pandas/sklearn，减少静态检查误报；运行期由调用方保证类型。
"""
from __future__ import annotations

import math
from typing import Any


def train_predict_ml(
    df: Any,
    factor_cols: list[str],
    min_train: int = 80,
    test_holdout: int = 40,
) -> dict:
    """
    使用时间序列前段训练、末段仅用于报告指标；最后一行用于预测当前 bar。
    严格避免：训练行标签 forward_ret 对该行而言是「下一根」，特征只用当前及过去。
    """
    try:
        from sklearn.linear_model import LogisticRegression  # pyright: ignore[reportMissingImports]
        from sklearn.preprocessing import StandardScaler  # pyright: ignore[reportMissingImports]
    except ImportError:
        return {
            "available": False,
            "reason": "未安装 scikit-learn，请执行: pip install scikit-learn",
            "p_up": None,
        }

    if df.empty or len(df) < min_train + test_holdout + 5:
        return {
            "available": False,
            "reason": "K 线不足",
            "p_up": None,
        }

    sub = df.dropna(subset=factor_cols + ["close"]).copy()
    if len(sub) < min_train + test_holdout + 5:
        return {"available": False, "reason": "有效样本不足", "p_up": None}

    fwd = sub["close"].pct_change().shift(-1)
    y = (fwd > 0).astype(float)
    X_all = sub[factor_cols].copy()
    valid = X_all.notna().all(axis=1) & y.notna()
    X = X_all.loc[valid]
    y = y.loc[valid].astype(int)
    if len(X) < min_train + test_holdout:
        return {"available": False, "reason": "对齐后样本不足", "p_up": None}

    X_train = X.iloc[: -test_holdout]
    y_train = y.iloc[: -test_holdout]
    X_test = X.iloc[-test_holdout:]
    y_test = y.iloc[-test_holdout:]
    X_now = X_all.iloc[-1:].copy()
    if X_now.isna().any().any():
        return {"available": False, "reason": "当前因子不完整", "p_up": None}

    if int(y_train.nunique()) < 2:
        return {
            "available": False,
            "reason": "训练集标签单一（无涨跌变化），无法训练分类器",
            "p_up": None,
        }

    scaler = StandardScaler()
    Xt = scaler.fit_transform(X_train)
    clf = LogisticRegression(max_iter=300, class_weight="balanced", random_state=42)
    try:
        clf.fit(Xt, y_train.values)
    except ValueError as e:
        return {
            "available": False,
            "reason": f"模型训练失败: {str(e)[:120]}",
            "p_up": None,
        }

    acc = None
    if len(X_test) > 5:
        Xs = scaler.transform(X_test)
        acc = float((clf.predict(Xs) == y_test.values).mean())

    p_up = float(clf.predict_proba(scaler.transform(X_now.fillna(0)))[0, 1])
    if math.isnan(p_up) or math.isinf(p_up):
        return {"available": False, "reason": "模型预测异常", "p_up": None}

    return {
        "available": True,
        "model": "logistic_regression",
        "p_up": round(p_up, 4),
        "holdout_accuracy": round(acc, 4) if acc is not None else None,
        "train_rows": int(len(X_train)),
        "note": "末段 holdout 仅作参考，防过拟合请以回测与样本外为准",
    }
