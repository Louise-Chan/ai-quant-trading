"""策略元数据（名称、分类、各策略专属风险上限）"""

STRATEGIES = [
    {
        "id": 1,
        "name": "稳健增长",
        "category": "稳健",
        "risk_level": "低",
        "description": "适合稳健型投资者，波动与回撤控制更严。",
        "risk_caps": {
            "max_position_pct": 0.30,
            "max_single_order_pct": 0.10,
            "max_stop_loss_magnitude": 0.10,
        },
    },
    {
        "id": 2,
        "name": "积极进取",
        "category": "积极",
        "risk_level": "中",
        "description": "适合积极型投资者，允许更高仓位与单笔暴露。",
        "risk_caps": {
            "max_position_pct": 0.55,
            "max_single_order_pct": 0.18,
            "max_stop_loss_magnitude": 0.18,
        },
    },
]


def get_strategy(strategy_id: int) -> dict | None:
    return next((s for s in STRATEGIES if s["id"] == strategy_id), None)


def list_strategies_public():
    """列表用：含简要风险上限说明"""
    out = []
    for s in STRATEGIES:
        caps = s.get("risk_caps") or {}
        out.append(
            {
                "id": s["id"],
                "name": s["name"],
                "category": s["category"],
                "risk_level": s["risk_level"],
                "description": s["description"],
                "max_position_pct_cap": caps.get("max_position_pct"),
                "max_single_order_pct_cap": caps.get("max_single_order_pct"),
            }
        )
    return out
