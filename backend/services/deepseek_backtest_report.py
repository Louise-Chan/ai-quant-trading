"""DeepSeek：根据回测摘要生成可读解读报告（非 JSON，纯文本/Markdown）"""
from __future__ import annotations

import json
from typing import Any

from services.deepseek_service import chat_completion

_MAX_CONTEXT_CHARS = 12000


def run_deepseek_backtest_report(
    api_key: str,
    user_prompt: str,
    backtest_summary: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ctx = {
        "backtest_summary": backtest_summary or {},
        "context": context or {},
    }
    raw = json.dumps(ctx, ensure_ascii=False)
    if len(raw) > _MAX_CONTEXT_CHARS:
        raw = raw[:_MAX_CONTEXT_CHARS] + "…(已截断)"

    system = """你是面向散户的加密货币量化回测解读助手。用户上传的是本地多因子组合回测的**结构化摘要**（非原始 K 线）。

要求：
1. 使用简体中文，可用 Markdown 小标题（##、###）与列表，语气专业、克制。
2. 结构建议：## 概览 → ## 收益与风险 → ## 因子与组合 → ## 显著性/标的（若摘要中有）→ ## 风险提示（必须明确：历史回测不代表未来，非投资建议）。
3. 仅根据摘要中的数字与字段推断，不要编造未出现的指标；缺数据处写「摘要未提供」。
4. 不要输出 JSON；不要要求用户执行交易。"""

    up = (user_prompt or "").strip()
    user = f"以下为回测摘要 JSON：\n{raw}\n\n"
    if up:
        user += f"用户额外要求：\n{up}\n"

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    text = chat_completion(api_key, messages, timeout=120, temperature=0.35)
    if not text or not str(text).strip():
        raise ValueError("DeepSeek 无有效正文")
    return {"report": str(text).strip()}
