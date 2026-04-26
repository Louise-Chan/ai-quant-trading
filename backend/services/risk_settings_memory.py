"""风控参数内存存储（与 api.risk 共用，可后续改为数据库）"""

_risk_settings: dict = {}  # (user_id, mode) -> settings


def risk_settings_for_user(user_id: int, mode: str) -> dict:
    key = (user_id, mode)
    return dict(_risk_settings.get(key, {"max_position_pct": 0.2, "stop_loss": -0.05}))


def set_risk_settings(user_id: int, mode: str, data: dict):
    key = (user_id, mode)
    cur = dict(_risk_settings.get(key, {"max_position_pct": 0.2, "stop_loss": -0.05}))
    cur.update({k: v for k, v in data.items() if v is not None})
    _risk_settings[key] = cur
    return cur
