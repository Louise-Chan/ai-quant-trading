"""DeepSeek：动态因子挖掘（生成新表达式/元数据）"""

from __future__ import annotations

import ast
import json
import time
from typing import Any

from services.deepseek_service import chat_completion_json_object, extract_json_object
from services.deepseek_service import chat_completion


_ALLOWED_VARS = {"open", "high", "low", "close", "volume"}
_ALLOWED_FUNCS = {"shift", "roll_mean", "roll_std", "roll_min", "roll_max", "zscore", "ts_rank", "log"}


class DeepseekFactorMiningValidationError(ValueError):
    pass


def _validate_expression_dsl(expression_dsl: str) -> None:
    if not expression_dsl or not str(expression_dsl).strip():
        raise DeepseekFactorMiningValidationError("expression_dsl 为空")
    s = str(expression_dsl).strip()
    if len(s) > 800:
        raise DeepseekFactorMiningValidationError("expression_dsl 过长")

    try:
        tree = ast.parse(s, mode="eval")
    except SyntaxError as e:
        raise DeepseekFactorMiningValidationError(f"表达式语法错误：{e}") from e

    for node in ast.walk(tree):
        if isinstance(node, ast.Expression):
            continue
        if isinstance(node, ast.Load):
            # 变量读取上下文：ast.Load 只是标注语义，不参与计算；无需拒绝
            continue
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)):
                raise DeepseekFactorMiningValidationError("只允许数值常量")
            continue
        if isinstance(node, ast.Name):
            # 只允许变量名（open/high/low/close/volume）
            if node.id not in _ALLOWED_VARS and node.id not in _ALLOWED_FUNCS:
                raise DeepseekFactorMiningValidationError(f"不允许的名字：{node.id}")
            continue
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
                raise DeepseekFactorMiningValidationError("只允许白名单函数调用")
            if node.keywords:
                raise DeepseekFactorMiningValidationError("不允许关键字参数")
            continue
        if isinstance(
            node,
            (
                ast.BinOp,
                ast.UnaryOp,
                ast.Add,
                ast.Sub,
                ast.Mult,
                ast.Div,
                ast.Pow,
                ast.UAdd,
                ast.USub,
            ),
        ):
            continue

        # 其它节点（Compare/Subscript/Attribute/BoolOp/IfExp/..）拒绝
        raise DeepseekFactorMiningValidationError(f"不允许的语法节点：{type(node).__name__}")


def _build_system_prompt(candidate_count: int) -> str:
    return f"""你是加密货币多因子量化研究员。
你需要根据用户描述“挖掘新动态因子”，输出 JSON（必须是合法 JSON 对象）。

硬性规则（必须遵守）：
1. 每个候选因子必须给出：id / name / description / expression_dsl。
2. expression_dsl 必须只使用变量：open, high, low, close, volume 以及以下函数：
   - shift(x,n)
   - roll_mean(x,w)
   - roll_std(x,w)
   - roll_min(x,w)
   - roll_max(x,w)
   - zscore(x,w)
   - ts_rank(x,w)
   - log(x)
3. expression_dsl 只能用算术运算 + - * / **，不允许比较、不允许 if/布尔逻辑、不允许任何属性访问/下标访问/导入/IO/循环。
4. 输出必须包含恰好 {candidate_count} 个候选（如果做不到也至少给出 1 个，但不要多于该数量）。
5. id 必须唯一、非空字符串；表达式可不同但 id 不得重复。

JSON 输出格式（键名固定）：
{{
  "candidates": [
    {{
      "id": "cand_001",
      "name": "...",
      "description": "...（一句话，解释可能的市场含义与方向）",
      "expression_dsl": "（只写表达式本身）"
    }}
  ]
}}
"""


def run_deepseek_factor_mining_agent(
    api_key: str,
    *,
    user_prompt: str = "",
    current_dynamic_factors: list[dict[str, Any]] | None = None,
    candidate_count: int = 50,
) -> dict[str, Any]:
    """
    返回：
    {{
      "candidates": [ {id,name,description,expression_dsl}, ... ]
    }}
    """
    current_dynamic_factors = current_dynamic_factors or []
    cur_slim = [
        {"factor_id": str(x.get("factor_id") or x.get("id") or ""), "name": str(x.get("name") or "")[:60]}
        for x in current_dynamic_factors
    ]
    ctx = {
        "current_dynamic_factors": cur_slim[:30],
        "user_prompt": (user_prompt or "").strip(),
        "candidate_count": int(candidate_count),
    }

    messages = [
        {"role": "system", "content": _build_system_prompt(int(candidate_count))},
        {"role": "user", "content": f"用户需求：\n{json.dumps(ctx, ensure_ascii=False)}"},
    ]

    # DeepSeek 请求偶发网络中断（如 IncompleteRead），做更强重试并支持 json/non-json 两种模式解析
    last_err: Exception | None = None
    data: dict[str, Any] | None = None
    for i in range(5):
        try:
            raw = chat_completion_json_object(api_key, messages, timeout=180)
            data = extract_json_object(raw)
            break
        except Exception as e:
            last_err = e
            # 同一轮再尝试普通 chat（有些代理/网关不稳定时 json_object 也可能失败）
            try:
                txt = chat_completion(api_key, messages, timeout=200, temperature=0.2)
                data = extract_json_object(txt)
                break
            except Exception as e2:
                last_err = e2
        # 指数退避：等待更久一些
        time.sleep(1.5 * (2**i))

    if not data:
        raise last_err or ValueError("DeepSeek 因子挖掘请求失败")
    cand = data.get("candidates") or []
    if not isinstance(cand, list):
        cand = []

    out: list[dict[str, Any]] = []
    seen_expr: set[str] = set()
    seen_id: set[str] = set()

    for item in cand:
        if len(out) >= int(candidate_count):
            break
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        desc = str(item.get("description") or "").strip()
        expr = str(item.get("expression_dsl") or "").strip()
        if not cid or not expr:
            continue
        if cid in seen_id:
            continue
        # DSL 白名单校验
        try:
            _validate_expression_dsl(expr)
        except Exception:
            continue
        if expr in seen_expr:
            continue
        seen_id.add(cid)
        seen_expr.add(expr)
        out.append(
            {
                "id": cid[:64],
                "name": name[:80],
                "description": desc[:400],
                "expression_dsl": expr,
            }
        )

    # 兜底：如果模型输出为空，至少返回空列表（刷新 worker 会标记 failed/无有效候选）
    return {"candidates": out, "count": len(out)}

