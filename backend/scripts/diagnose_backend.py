"""诊断后端是否为 gate-v2（本仓库最新代码）

用法: python backend/scripts/diagnose_backend.py
或在 backend 目录: python scripts/diagnose_backend.py
"""
# -*- coding: utf-8 -*-
import sys
import io
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import requests
except ImportError:
    print("请安装: pip install requests")
    sys.exit(1)

BASE = "http://127.0.0.1:8081/api/v1"

def main():
    print("\n========== 后端诊断 ==========\n")

    # 1. debug/version
    print("[1] debug/version (gate-v2 标识)")
    try:
        r = requests.get(f"{BASE}/debug/version", timeout=5)
        data = r.json() if r.ok else {}
        ver = data.get("data", {}).get("backend_version", "")
        if ver == "gate-v2":
            print("    [OK] backend_version = gate-v2 (本仓库后端)")
        elif r.status_code == 404:
            print("    [FAIL] 404 - 说明运行的是旧后端，没有此接口")
        else:
            print(f"    [FAIL] {r.status_code} {data}")
    except Exception as e:
        print(f"    [FAIL] 连接失败: {e}")

    # 2. broker/status
    print("\n[2] broker/status")
    try:
        r = requests.get(f"{BASE}/broker/status", timeout=5)
        if r.ok:
            j = r.json() or {}
            d = j.get("data") or {}
            print(f"    [OK] 模式: {d.get('current_mode', '?')}, 交易所: {d.get('exchange', '?')}")
        else:
            print(f"    [FAIL] {r.status_code}")
    except Exception as e:
        print(f"    [FAIL] {e}")

    # 3. broker/testgate (无 token 会 401)
    print("\n[3] broker/testgate (无登录 token 会 401)")
    try:
        r = requests.get(f"{BASE}/broker/testgate?mode=simulated", timeout=5)
        if r.status_code == 404:
            print("    [FAIL] 404 - 旧后端无此接口")
        elif r.status_code == 401:
            print("    [OK] 401 需登录 - 接口存在")
        elif r.ok:
            print("    [OK] 200 - Gate 原始数据可用")
        else:
            print(f"    {r.status_code}")
    except Exception as e:
        print(f"    ✗ {e}")

    print("\n========== 诊断完成 ==========")
    print("\ngate-v2 默认端口 8081。若 debug/version 或 testgate 返回 404，请：")
    print("  1. 关闭所有后端窗口 (Ctrl+C)")
    print("  2. 运行 start-backend.bat")
    print("  3. 确认窗口显示「gate-v2 后端」\n")
    return 0

if __name__ == "__main__":
    sys.exit(main())
