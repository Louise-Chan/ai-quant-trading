"""测试 Gate.io API 连接 - 用于排查无法获取账户资产

用法（在项目根目录执行）:
  python backend/scripts/test_gate_api.py YOUR_KEY YOUR_SECRET [simulated|real]

或在 backend 目录下:
  cd backend
  python scripts/test_gate_api.py YOUR_KEY YOUR_SECRET [simulated|real]
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    if len(sys.argv) < 3:
        print("用法: python backend/scripts/test_gate_api.py YOUR_KEY YOUR_SECRET [simulated|real]")
        print("示例: python backend/scripts/test_gate_api.py abc123 xyz789 simulated")
        return 1
    api_key = sys.argv[1]
    api_secret = sys.argv[2]
    mode = sys.argv[3] if len(sys.argv) > 3 else "simulated"

    from utils.gate_client import HOST_REAL, HOST_SIMULATED, get_client
    from gate_api import SpotApi

    host = HOST_REAL if mode == "real" else HOST_SIMULATED
    print(f"模式: {mode}, 地址: {host}")
    try:
        client = get_client(mode, api_key, api_secret)
        api = SpotApi(client)
        accounts = api.list_spot_accounts()
        print(f"成功! 账户数量: {len(accounts or [])}")
        for a in (accounts or [])[:10]:
            curr = getattr(a, "currency", "") or (a.get("currency") if isinstance(a, dict) else "")
            avail = getattr(a, "available", "0") or (a.get("available", "0") if isinstance(a, dict) else "0")
            locked = getattr(a, "locked", "0") or (a.get("locked", "0") if isinstance(a, dict) else "0")
            print(f"  {curr}: available={avail}, locked={locked}")
        return 0
    except Exception as e:
        print(f"失败: {e}")
        print("\n请确认:")
        print("1. 模拟账户：创建 Key 时选择「模拟账户」类型")
        print("2. API 权限包含「读取」")
        print("3. 若启用 IP 白名单，请将本机 IP 加入")
        return 1

if __name__ == "__main__":
    sys.exit(main())
