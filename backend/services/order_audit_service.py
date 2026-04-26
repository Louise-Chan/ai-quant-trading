"""订单审核：组装上下文、调用 DeepSeek、落库"""
from __future__ import annotations

import json
from sqlalchemy.orm import Session

from services.risk_settings_memory import risk_settings_for_user
from models.order_audit import OrderAudit
from services.broker_service import get_broker
from services.deepseek_service import chat_completion, extract_json_object
from services.gate_account_service import get_positions_with_value, get_total_balance_usdt


def label_instrument_from_signal(signal: dict | None) -> str:
    """标的类型展示：现货、合约、期权、ETF 等"""
    sig = signal or {}
    raw = str(sig.get("quote_market") or sig.get("instrument_type") or sig.get("instrument_kind") or "spot").lower()
    if raw in ("futures", "futures_usdt", "contract", "perp", "swap"):
        return "合约"
    if raw in ("option", "options"):
        return "期权"
    if raw in ("etf", "leveraged_etf"):
        return "ETF"
    if raw in ("margin", "杠杆"):
        return "杠杆"
    return "现货"


AUDIT_SYSTEM_PROMPT = """你是加密货币量化交易风控助理。用户可能附带「strategy_engine」对象，其中包含基于多因子与程序化流程产出的交易信号，请务必一并审阅：

- factors_latest / factor_evaluation：因子值与滚动 IC、ICIR（评估）
- dynamic_weights：多因子动态权重
- machine_learning：逻辑回归等对短期涨跌概率的预测（若 available）
- backtest：无未来函数的简化回测统计（夏普、回撤、胜率、盈亏比等）
- suggested_order、position_sizing、risk_metrics：程序给出的限价、数量、ATR 止损止盈、Kelly 与波动等

你的任务是：在理解上述**程序化策略输出**的基础上，结合账户与风控，输出「订单审核」结果；若程序信号与风险约束冲突，应调低仓位或建议不交易，并在 reason 中说明。

你必须只输出一个 JSON 对象（不要 Markdown、不要其它文字），结构如下：
{
  "audited_order": {
    "symbol": "交易对，如 BTC_USDT",
    "side": "buy 或 sell",
    "order_type": "limit 或 market",
    "price": "限价单价格字符串；市价单可为空字符串",
    "amount": "下单数量字符串（基础币数量，如 BTC 个数）",
    "stop_loss_price": "建议止损价字符串，无可填 null",
    "take_profit_price": "建议止盈价字符串，无可填 null",
    "open_time_suggestion": "何时/何种条件下开仓的简短说明",
    "close_time_suggestion": "何时平仓或持仓周期建议"
  },
  "reason": "是否同意该笔交易及调整依据的简明理由",
  "confidence": "high 或 medium 或 low（分别对应高信心、中信心、低信心）"
}

规则：
1. 若认为不应交易，仍将 audited_order 填为建议值或原信号值，但 confidence 设为 low，并在 reason 中明确反对原因。
2. 可根据风险在合理范围内修改 price、amount、side（需说明理由）。
3. amount、price 必须与 Gate.io 现货下单字段一致；symbol 使用下划线格式如 BTC_USDT。
4. amount × 价格（限价用委托价）折合的成交额须 ≥ 约 3 USDT（Gate 现货常见最小下单额），否则应提高 amount。
5. 输出合法 JSON，字符串使用双引号。"""


def build_audit_context(
    db: Session,
    user_id: int,
    mode: str,
    symbol: str,
    signal: dict | None,
) -> dict:
    broker = get_broker(db, user_id, mode)
    portfolio: dict = {"total_usdt": None, "gate_bound": broker is not None}
    positions: list = []
    if broker:
        try:
            _, _, total = get_total_balance_usdt(mode, broker.api_key_enc, broker.api_secret_enc)
            portfolio["total_usdt"] = round(float(total), 4)
            positions = get_positions_with_value(mode, broker.api_key_enc, broker.api_secret_enc)
        except Exception as e:
            portfolio["fetch_error"] = str(e)
    risk = risk_settings_for_user(user_id, mode)
    return {
        "symbol": symbol,
        "signal": signal or {},
        "portfolio": portfolio,
        "positions": positions[:30],
        "risk": risk,
        "mode": mode,
    }


def run_deepseek_audit(api_key: str, context: dict) -> tuple[dict, str]:
    user_content = "以下为当前交易上下文（JSON）：\n" + json.dumps(context, ensure_ascii=False, indent=2)
    raw = chat_completion(
        api_key,
        [
            {"role": "system", "content": AUDIT_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    )
    parsed = extract_json_object(raw)
    return parsed, raw


def create_pending_audit(
    db: Session,
    user_id: int,
    mode: str,
    context: dict,
    parsed: dict,
    raw_response: str,
) -> OrderAudit:
    audited = parsed.get("audited_order") or {}
    sig = context.get("signal") or {}
    audited["instrument_type"] = label_instrument_from_signal(sig)
    reason = parsed.get("reason") or ""
    conf = (parsed.get("confidence") or "medium").lower()
    if conf not in ("high", "medium", "low"):
        conf = "medium"

    row = OrderAudit(
        user_id=user_id,
        mode=mode,
        status="pending",
        context_json=json.dumps(context, ensure_ascii=False),
        audited_order_json=json.dumps(audited, ensure_ascii=False),
        agent_reason=reason,
        confidence=conf,
        raw_agent_response=raw_response[:65000] if raw_response else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def audit_to_api_dict(row: OrderAudit) -> dict:
    try:
        audited = json.loads(row.audited_order_json or "{}")
    except Exception:
        audited = {}
    try:
        ctx = json.loads(row.context_json or "{}")
    except Exception:
        ctx = {}
    if not audited.get("instrument_type"):
        audited["instrument_type"] = label_instrument_from_signal(ctx.get("signal"))
    conf_map = {"high": "高信心", "medium": "中信心", "low": "低信心"}
    return {
        "id": row.id,
        "status": row.status,
        "mode": row.mode,
        "context": ctx,
        "audited_order": audited,
        "agent_reason": row.agent_reason,
        "confidence": row.confidence,
        "confidence_label": conf_map.get((row.confidence or "").lower(), "中信心"),
        "exchange_order_id": row.exchange_order_id,
        "error_message": row.error_message,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
