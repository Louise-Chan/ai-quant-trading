"""DeepSeek Agent 选币：从候选池中选出最优 10 个标的"""
from __future__ import annotations

from services.deepseek_service import chat_completion, extract_json_object, chat_completion_json_object


def build_candidate_lines(candidates: list[dict], max_lines: int = 55) -> str:
    """candidates: [{symbol, last, change_pct, quote_volume or volume_hint}, ...]"""
    lines = []
    for c in candidates[:max_lines]:
        sym = c.get("symbol") or ""
        last = c.get("last", "")
        chg = c.get("change_pct", "")
        vol = c.get("quote_volume") or c.get("volume_hint") or ""
        lines.append(f"{sym}\tlast={last}\t24h%={chg}\tvol={vol}")
    return "\n".join(lines)


def run_agent_coin_pick(
    api_key: str,
    candidate_rows: str,
    allowed_symbols: list[str],
    preference: str | None,
    top_n: int = 10,
) -> tuple[list[dict], str, str]:
    """
    返回 (symbols 列表含 reason, summary, raw_response)
    """
    allow = set(allowed_symbols)
    pref = (preference or "").strip()
    user = f"""以下是现货 USDT 交易对的行情摘要（制表符分隔）。请从中**仅选择恰好 {top_n} 个**交易对，作为当前环境下较优的分散化标的。

【候选】（必须从下列 symbol 中选，不可编造不存在的交易对）：
{candidate_rows}

用户偏好说明：{pref or "无特别偏好，兼顾流动性与风险"}

请严格输出一个 JSON 对象，格式：
{{"symbols":[{{"symbol":"BTC_USDT","reason":"一句话理由"}}], "summary":"整体说明不超过120字"}}"""

    raw = ""
    try:
        raw = chat_completion_json_object(
            api_key,
            [
                {
                    "role": "system",
                    "content": "你是加密货币现货选币助手，只输出合法 JSON，symbol 必须与用户给出的候选列表一致。",
                },
                {"role": "user", "content": user},
            ],
        )
    except Exception:
        raw = chat_completion(
            api_key,
            [
                {
                    "role": "system",
                    "content": "你是加密货币现货选币助手。只输出一个 JSON 对象，不要 Markdown。",
                },
                {"role": "user", "content": user + "\n\n只输出 JSON。"},
            ],
        )

    data = extract_json_object(raw)
    items = data.get("symbols") or data.get("recommendations") or []
    summary = data.get("summary") or data.get("analysis") or ""

    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        sym = (it.get("symbol") or "").strip()
        if sym in allow:
            out.append({"symbol": sym, "reason": (it.get("reason") or "DeepSeek 推荐")[:200]})
        if len(out) >= top_n:
            break

    # 若模型未凑满，从 allowed 顺序补齐（保持确定性）
    for sym in allowed_symbols:
        if len(out) >= top_n:
            break
        if sym in allow and all(x["symbol"] != sym for x in out):
            out.append({"symbol": sym, "reason": "规则池补充"})

    return out[:top_n], summary, raw
