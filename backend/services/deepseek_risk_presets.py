"""DeepSeek 生成低/中/高风险默认风控预设（按策略上限裁剪）"""
from __future__ import annotations

from services.deepseek_service import chat_completion, extract_json_object, chat_completion_json_object
from services.strategy_risk_store import clamp_settings


PRESET_SYSTEM = """你是量化交易风控顾问。根据策略名称、风险上限与用户当前组合概况，给出三组风控预设。

必须只输出一个 JSON 对象，结构如下：
{
  "analysis": "对当前风险环境的简短总结，80字以内",
  "presets": {
    "low": {
      "max_position_pct": 0.12,
      "stop_loss": -0.03,
      "max_single_order_pct": 0.04,
      "label": "低风险"
    },
    "medium": {
      "max_position_pct": 0.20,
      "stop_loss": -0.06,
      "max_single_order_pct": 0.08,
      "label": "中风险"
    },
    "high": {
      "max_position_pct": 0.28,
      "stop_loss": -0.09,
      "max_single_order_pct": 0.10,
      "label": "高风险"
    }
  }
}

说明：
- max_position_pct、max_single_order_pct 为 0~1 的小数。
- stop_loss 为负数，表示单笔/组合可承受亏损比例（如 -0.05 表示约 5%）。
- 三组数值必须满足：low < medium <= high，且都不得超过用户给出的「硬上限」。"""


def run_risk_presets(
    api_key: str,
    strategy_name: str,
    strategy_desc: str,
    caps: dict,
    portfolio_hint: str | None = None,
) -> tuple[dict, str]:
    """
    返回 ( { analysis, presets: { low, medium, high } 已 clamp }, raw )
    """
    import json as _json

    cap_text = _json.dumps(
        {
            "max_position_pct": caps.get("max_position_pct"),
            "max_single_order_pct": caps.get("max_single_order_pct"),
            "max_stop_loss_magnitude": caps.get("max_stop_loss_magnitude"),
        },
        ensure_ascii=False,
    )
    user = f"""策略名称：{strategy_name}
策略说明：{strategy_desc}

该策略允许的硬上限（不得超过）：{cap_text}

组合/市场简述：{portfolio_hint or "未提供，请按中性假设给出保守到进取三档。"}

请输出 JSON。"""

    raw = ""
    try:
        raw = chat_completion_json_object(
            api_key,
            [
                {"role": "system", "content": PRESET_SYSTEM},
                {"role": "user", "content": user},
            ],
        )
    except Exception:
        raw = chat_completion(
            api_key,
            [
                {"role": "system", "content": PRESET_SYSTEM},
                {"role": "user", "content": user + "\n只输出 JSON，不要用代码块。"},
            ],
        )

    data = extract_json_object(raw)
    analysis = data.get("analysis") or ""
    presets_in = data.get("presets") or {}

    out_presets = {}
    for tier in ("low", "medium", "high"):
        block = presets_in.get(tier)
        if not isinstance(block, dict):
            continue
        cleaned = {
            "max_position_pct": block.get("max_position_pct"),
            "stop_loss": block.get("stop_loss"),
            "max_single_order_pct": block.get("max_single_order_pct"),
            "label": block.get("label") or tier,
        }
        clamped = clamp_settings(
            {
                "max_position_pct": float(cleaned["max_position_pct"] or 0.1),
                "stop_loss": float(cleaned["stop_loss"] or -0.05),
                "max_single_order_pct": float(cleaned["max_single_order_pct"] or 0.05),
            },
            caps,
        )
        out_presets[tier] = {**clamped, "label": cleaned["label"]}

    # 若模型缺档，用默认三档
    if len(out_presets) < 3:
        mpc = float(caps.get("max_position_pct", 0.35))
        mso = float(caps.get("max_single_order_pct", 0.12))
        msl = float(caps.get("max_stop_loss_magnitude", 0.12))
        base = clamp_settings(
            {
                "max_position_pct": mpc * 0.35,
                "stop_loss": -msl * 0.35,
                "max_single_order_pct": mso * 0.35,
            },
            caps,
        )
        mid = clamp_settings(
            {
                "max_position_pct": mpc * 0.55,
                "stop_loss": -msl * 0.55,
                "max_single_order_pct": mso * 0.55,
            },
            caps,
        )
        hi = clamp_settings(
            {
                "max_position_pct": mpc * 0.85,
                "stop_loss": -msl * 0.85,
                "max_single_order_pct": mso * 0.85,
            },
            caps,
        )
        out_presets.setdefault("low", {**base, "label": "低风险"})
        out_presets.setdefault("medium", {**mid, "label": "中风险"})
        out_presets.setdefault("high", {**hi, "label": "高风险"})

    return {"analysis": analysis, "presets": out_presets}, raw
