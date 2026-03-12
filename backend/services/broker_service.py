"""交易所绑定服务（Gate.io 封装）"""
import re
from sqlalchemy.orm import Session
from gate_api.exceptions import ApiException, GateApiException
from models.broker import BrokerAccount
from models.user_preference import UserPreference
from utils.gate_client import get_client, get_config, SpotApi


def _parse_gate_error(e: Exception) -> str:
    """解析 Gate.io API 错误，返回用户友好的中文提示"""
    msg = str(e)
    # IP 白名单限制（403 Forbidden）- 从 "whitelist: X.X.X.X" 提取真实 IP，避免误匹配 Server 版本号
    if "whitelist" in msg.lower():
        m = re.search(r"whitelist:\s*(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", msg, re.I)
        ip = m.group(1) if m else None
        ip_part = f"（{ip}）" if ip else ""
        return f"您的 IP 地址{ip_part}不在 Gate.io API 密钥的白名单中。请登录 Gate.io → API 管理 → 编辑该密钥 → 将 IP 加入白名单，或关闭 IP 限制。"
    # 其他 403
    if "403" in msg or "Forbidden" in msg:
        return "API 密钥无权限或已被限制。请检查 Gate.io 后台的 API 权限设置。"
    # 401 认证失败
    if "401" in msg or "Unauthorized" in msg:
        return "API Key 或 Secret 错误。模拟账户请确认：1) 创建 Key 时选择「模拟账户」类型 2) 实盘/模拟使用同一地址 api.gateio.ws"
    # 404 或 NOT_FOUND
    if "404" in msg or "not found" in msg.lower():
        return "接口不存在，请确认使用的 API 地址正确（模拟/实盘均用 api.gateio.ws）"
    return f"API 验证失败: {msg}"


def bind_broker(db: Session, user_id: int, mode: str, api_key: str, api_secret: str) -> BrokerAccount:
    """绑定 Gate.io 账户，验证 API 有效性"""
    try:
        client = get_client(mode, api_key, api_secret)
        api = SpotApi(client)
        api.list_spot_accounts()  # 验证
    except (GateApiException, ApiException) as e:
        raise ValueError(_parse_gate_error(e))
    except Exception as e:
        raise ValueError(_parse_gate_error(e))

    # 加密存储（简化：实际应加密）
    existing = db.query(BrokerAccount).filter(BrokerAccount.user_id == user_id, BrokerAccount.mode == mode).first()
    if existing:
        existing.api_key_enc = api_key
        existing.api_secret_enc = api_secret
        db.commit()
        db.refresh(existing)
        return existing

    broker = BrokerAccount(
        user_id=user_id,
        mode=mode,
        api_key_enc=api_key,
        api_secret_enc=api_secret,
        exchange="gateio",
    )
    db.add(broker)
    db.commit()
    db.refresh(broker)
    return broker


def get_broker(db: Session, user_id: int, mode: str) -> BrokerAccount | None:
    return db.query(BrokerAccount).filter(BrokerAccount.user_id == user_id, BrokerAccount.mode == mode).first()


def get_mode(db: Session, user_id: int) -> str:
    """获取用户当前交易模式"""
    pref = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
    return pref.current_mode if pref else "simulated"


def get_broker_status(db: Session, user_id: int) -> dict:
    real = db.query(BrokerAccount).filter(BrokerAccount.user_id == user_id, BrokerAccount.mode == "real").first()
    sim = db.query(BrokerAccount).filter(BrokerAccount.user_id == user_id, BrokerAccount.mode == "simulated").first()
    pref = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
    current = pref.current_mode if pref else "simulated"
    return {
        "real_bound": real is not None,
        "simulated_bound": sim is not None,
        "current_mode": current,
        "exchange": "gateio",
    }


def set_mode(db: Session, user_id: int, mode: str):
    pref = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
    if pref:
        pref.current_mode = mode
    else:
        pref = UserPreference(user_id=user_id, current_mode=mode)
        db.add(pref)
    db.commit()


def unbind_broker(db: Session, user_id: int, mode: str = None):
    q = db.query(BrokerAccount).filter(BrokerAccount.user_id == user_id)
    if mode:
        q = q.filter(BrokerAccount.mode == mode)
    q.delete()
    db.commit()
