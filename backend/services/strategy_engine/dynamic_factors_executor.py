"""动态因子表达式执行器（安全 DSL）

目的：在不使用 eval/exec 的前提下，根据 DSL 字符串安全地计算出动态因子序列（pd.Series）。
DSL 只允许：
- 变量：open/high/low/close/volume
- 常量：int/float
- 运算：+ - * / **（其余可按需扩展）
- 函数：
  - shift(x, n)
  - roll_mean(x, w)
  - roll_std(x, w)
  - roll_min(x, w)
  - roll_max(x, w)
  - zscore(x, w)        （滚动标准化）
  - ts_rank(x, w)       （滚动窗口内的百分位秩，取窗口最后一个值的 rank(pct)）
  - log(x)              （log(abs(x)+1e-12）避免负数/0）

注意：该模块不保证“经济逻辑合理”，只保证“无未来函数/无不安全代码执行”。
"""

from __future__ import annotations

import ast
import operator
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np  # pyright: ignore[reportMissingImports]
import pandas as pd  # pyright: ignore[reportMissingImports]


class DynamicFactorExpressionError(ValueError):
    pass


_BIN_OPS: dict[type[ast.AST], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}

_UNARY_OPS: dict[type[ast.AST], Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_ALLOWED_VARS = {"open", "high", "low", "close", "volume"}


def _as_int(x: Any, *, name: str, min_v: int | None = None, max_v: int | None = None) -> int:
    try:
        v = int(x)
    except Exception as e:
        raise DynamicFactorExpressionError(f"{name} 必须是整数：{x!r}") from e
    if min_v is not None and v < min_v:
        raise DynamicFactorExpressionError(f"{name} 太小：{v} < {min_v}")
    if max_v is not None and v > max_v:
        raise DynamicFactorExpressionError(f"{name} 太大：{v} > {max_v}")
    return v


def shift(x: pd.Series, n: int) -> pd.Series:
    n = _as_int(n, name="n", min_v=0, max_v=2000)
    return x.shift(n)


def roll_mean(x: pd.Series, w: int) -> pd.Series:
    w = _as_int(w, name="w", min_v=2, max_v=4000)
    return x.rolling(w, min_periods=max(2, w // 2)).mean()


def roll_std(x: pd.Series, w: int) -> pd.Series:
    w = _as_int(w, name="w", min_v=2, max_v=4000)
    # ddof=0：更稳定（避免样本过少导致方差奇异）
    return x.rolling(w, min_periods=max(2, w // 2)).std(ddof=0)


def roll_min(x: pd.Series, w: int) -> pd.Series:
    w = _as_int(w, name="w", min_v=2, max_v=4000)
    return x.rolling(w, min_periods=max(2, w // 2)).min()


def roll_max(x: pd.Series, w: int) -> pd.Series:
    w = _as_int(w, name="w", min_v=2, max_v=4000)
    return x.rolling(w, min_periods=max(2, w // 2)).max()


def zscore(x: pd.Series, w: int) -> pd.Series:
    w = _as_int(w, name="w", min_v=2, max_v=4000)
    mu = x.rolling(w, min_periods=max(2, w // 2)).mean()
    sd = x.rolling(w, min_periods=max(2, w // 2)).std(ddof=0).replace(0.0, np.nan)
    return (x - mu) / sd


def ts_rank(x: pd.Series, w: int) -> pd.Series:
    """
    滚动窗口内最后一个值的百分位秩。
    说明：用 apply 可能偏慢，但动态因子刷新是“按需/异步”，可接受。
    """
    w = _as_int(w, name="w", min_v=2, max_v=2000)

    def _rank_last(arr: np.ndarray) -> float:
        s = pd.Series(arr)
        r = s.rank(pct=True).iloc[-1]
        if pd.isna(r):
            return np.nan
        return float(r)

    return x.rolling(w, min_periods=max(2, w // 2)).apply(_rank_last, raw=True)


def log(x: pd.Series) -> pd.Series:
    return np.log(np.abs(x) + 1e-12)


_ALLOWED_FUNCS: dict[str, Callable[..., Any]] = {
    "shift": shift,
    "roll_mean": roll_mean,
    "roll_std": roll_std,
    "roll_min": roll_min,
    "roll_max": roll_max,
    "zscore": zscore,
    "ts_rank": ts_rank,
    "log": log,
}


@dataclass(frozen=True)
class EvalContext:
    env: dict[str, Any]
    df_len: int


def _eval_ast(node: ast.AST, ctx: EvalContext) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_ast(node.body, ctx)

    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, (int, float)):
            return float(v)
        raise DynamicFactorExpressionError(f"常量类型不允许：{type(v).__name__}")

    if isinstance(node, ast.Name):
        if node.id not in ctx.env:
            raise DynamicFactorExpressionError(f"未知变量：{node.id}")
        return ctx.env[node.id]

    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _BIN_OPS:
            raise DynamicFactorExpressionError(f"不允许的二元运算：{op_type.__name__}")
        left = _eval_ast(node.left, ctx)
        right = _eval_ast(node.right, ctx)
        return _BIN_OPS[op_type](left, right)

    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _UNARY_OPS:
            raise DynamicFactorExpressionError(f"不允许的单元运算：{op_type.__name__}")
        v = _eval_ast(node.operand, ctx)
        return _UNARY_OPS[op_type](v)

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise DynamicFactorExpressionError("只允许直接调用函数名，不允许链式调用/属性访问")
        fn_name = node.func.id
        if fn_name not in _ALLOWED_FUNCS:
            raise DynamicFactorExpressionError(f"不允许的函数：{fn_name}")
        if node.keywords:
            raise DynamicFactorExpressionError("不允许关键字参数（keywords）")
        fn = _ALLOWED_FUNCS[fn_name]
        args = [_eval_ast(a, ctx) for a in node.args]
        return fn(*args)

    # 其余节点（Attribute/Subscript/Compare/...）统统拒绝
    raise DynamicFactorExpressionError(f"表达式包含不允许的语法节点：{type(node).__name__}")


def compute_dynamic_factor_series(
    df: pd.DataFrame,
    expression_dsl: str,
) -> pd.Series:
    """
    计算单个表达式，返回因子序列。
    注意：df 必须包含 open/high/low/close/volume（至少 close）。
    """
    if not expression_dsl or not str(expression_dsl).strip():
        raise DynamicFactorExpressionError("expression_dsl 为空")

    expr = str(expression_dsl).strip()
    if len(expr) > 800:
        raise DynamicFactorExpressionError("expression_dsl 过长")

    # parse
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise DynamicFactorExpressionError(f"表达式语法错误：{e}") from e

    env: dict[str, Any] = {}
    for v in _ALLOWED_VARS:
        if v not in df.columns:
            # 允许 volume 缺失：统一用 0；允许 open/high/low 缺失：后续由上游补齐
            if v == "volume":
                env[v] = pd.Series(0.0, index=df.index)
            else:
                raise DynamicFactorExpressionError(f"df 缺少必要字段：{v}")
        else:
            env[v] = pd.to_numeric(df[v], errors="coerce").astype(float)

    ctx = EvalContext(env=env, df_len=len(df))
    out = _eval_ast(tree, ctx)

    if isinstance(out, pd.Series):
        s = out
    else:
        # 常量表达式（很少见），扩展成长度一致的常量序列
        s = pd.Series(float(out), index=df.index)

    s = s.replace([np.inf, -np.inf], np.nan).astype(float)
    return s

