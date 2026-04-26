"""按用户+模式+订阅ID 存储风控参数（内存，可换数据库）"""

from __future__ import annotations

_store: dict[tuple[int, str, int], dict] = {}


def _defaults_from_caps(caps: dict) -> dict:
    return {
        "max_position_pct": round(min(0.18, caps.get("max_position_pct", 0.3)), 4),
        "stop_loss": round(-min(0.04, caps.get("max_stop_loss_magnitude", 0.12)), 4),
        "max_single_order_pct": round(min(0.06, caps.get("max_single_order_pct", 0.12)), 4),
    }


def clamp_settings(settings: dict, caps: dict) -> dict:
    max_pos = float(caps.get("max_position_pct", 0.5))
    max_single = float(caps.get("max_single_order_pct", 0.2))
    max_sl = float(caps.get("max_stop_loss_magnitude", 0.2))

    mp = float(settings.get("max_position_pct", 0.15))
    mp = max(0.01, min(mp, max_pos))

    ms = float(settings.get("max_single_order_pct", 0.05))
    ms = max(0.01, min(ms, max_single, mp))

    sl = float(settings.get("stop_loss", -0.05))
    mag = min(abs(sl), max_sl)
    sl = -mag

    return {
        "max_position_pct": round(mp, 4),
        "stop_loss": round(sl, 4),
        "max_single_order_pct": round(ms, 4),
    }


def get_risk_settings(user_id: int, mode: str, subscription_id: int, caps: dict) -> dict:
    key = (user_id, mode, subscription_id)
    if key not in _store:
        _store[key] = _defaults_from_caps(caps)
    return clamp_settings(_store[key], caps)


def update_risk_settings(user_id: int, mode: str, subscription_id: int, caps: dict, patch: dict) -> dict:
    key = (user_id, mode, subscription_id)
    cur = get_risk_settings(user_id, mode, subscription_id, caps)
    for k in ("max_position_pct", "stop_loss", "max_single_order_pct"):
        if k in patch and patch[k] is not None:
            cur[k] = patch[k]
    cur = clamp_settings(cur, caps)
    _store[key] = cur
    return cur


def apply_preset(
    user_id: int, mode: str, subscription_id: int, caps: dict, preset: dict
) -> dict:
    """应用 DeepSeek 或前端选中的预设（先 clamp）"""
    merged = {
        "max_position_pct": preset.get("max_position_pct"),
        "stop_loss": preset.get("stop_loss"),
        "max_single_order_pct": preset.get("max_single_order_pct"),
    }
    return update_risk_settings(user_id, mode, subscription_id, caps, merged)
