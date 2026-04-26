"""DeepSeek：根据策略描述筛选/优化回测因子子集"""
from __future__ import annotations

import json
from typing import Any

from services.deepseek_service import chat_completion, chat_completion_json_object, extract_json_object
from services.strategy_engine.factors import FACTOR_LIBRARY, default_factor_ids


def _allowed_ids() -> list[str]:
    return default_factor_ids()


def _build_system_prompt(mode: str) -> str:
    n = len(_allowed_ids())
    return f"""你是加密货币多因子量化助手。用户将描述交易思路或要求优化因子集合。

【硬性规则】
1. 只能从系统因子库中的因子 id 选择（共 {n} 个，含 Qlib/VNPy Alpha158 风格 a158_*、经典价量 cls_*、以及基础动量/技术指标如 mom_5、rsi_14 等），不得发明新 id；id 与 GET /strategy-engine/factor-library 返回的 factors[].id 一致。
2. 必须至少选 1 个、至多选全部。
3. 输出必须是合法 JSON 对象，键名固定：
   - "selected_factors": string[]  （因子 id 列表）
   - "strategy_summary": string   （1～3 句中文，概括当前策略逻辑）
   - "changes": string[]         （相对上一版增加了/移除了哪些因子，无则 []）
   - "rationale": string         （为何选这些因子，简短）

当前模式：{mode}
- generate：用户可能只给模糊目标，你可自行补全策略并选因子。
- screen：根据用户「预想策略」选因子。
- optimize：根据当前因子列表 + 回测摘要，建议增删因子以改进策略。"""


def run_deepseek_factor_agent(
    api_key: str,
    mode: str,
    user_prompt: str,
    current_factors: list[str] | None = None,
    backtest_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mode = (mode or "screen").lower().strip()
    if mode not in ("generate", "screen", "optimize"):
        mode = "screen"
    allowed = set(_allowed_ids())
    ctx = {
        "current_factors": list(current_factors or []),
        "backtest_summary": backtest_summary or {},
    }
    user = f"用户输入：\n{(user_prompt or '').strip() or '（无补充，请根据模式自行推理）'}\n\n上下文 JSON：\n{json.dumps(ctx, ensure_ascii=False)}"
    messages = [
        {"role": "system", "content": _build_system_prompt(mode)},
        {"role": "user", "content": user},
    ]
    raw = None
    try:
        raw = chat_completion_json_object(api_key, messages, timeout=180)
    except ValueError as e:
        # 仅在 HTTP 4xx（如 response_format 不支持 / 参数不合法）时回退到普通模式；
        # 超时、网络错误直接抛出，避免后端总耗时翻倍导致前端先超时。
        msg = str(e) or ""
        if "HTTP 4" in msg:
            raw = chat_completion(api_key, messages, timeout=180)
        else:
            raise
    if not raw:
        raise ValueError("DeepSeek 无返回")
    try:
        data = extract_json_object(raw)
    except Exception as e:
        raise ValueError(f"无法解析 JSON: {e}") from e
    sel = data.get("selected_factors") or data.get("factors") or []
    if not isinstance(sel, list):
        sel = []
    clean = [str(x).strip() for x in sel if str(x).strip() in allowed]
    if not clean:
        clean = list(allowed)
    seen: set[str] = set()
    ordered: list[str] = []
    for x in clean:
        if x not in seen:
            seen.add(x)
            ordered.append(x)
    ch = data.get("changes")
    if isinstance(ch, list):
        changes_out = [str(x) for x in ch][:20]
    else:
        changes_out = []
    return {
        "selected_factors": ordered,
        "strategy_summary": str(data.get("strategy_summary") or "")[:800],
        "changes": changes_out,
        "rationale": str(data.get("rationale") or "")[:1200],
        "factor_library": FACTOR_LIBRARY,
    }
