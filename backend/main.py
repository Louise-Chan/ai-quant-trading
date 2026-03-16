"""FastAPI 应用入口"""
from fastapi import FastAPI, Depends, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from config import get_settings
from core.database import engine, Base, get_db
from core.security import decode_token
import models  # 确保模型已加载
from api import auth, users, broker, dashboard, market, portfolio, assets, trading, strategies, subscription, risk
from services.broker_service import get_broker, get_mode
from services.gate_account_service import get_spot_accounts, get_total_balance_usdt
from utils.gate_client import HOST_SIMULATED, HOST_REAL

# 创建表（开发环境，MySQL 不可用时跳过）
try:
    Base.metadata.create_all(bind=engine)
except Exception as e:
    print(f"DB init skip: {e}")

app = FastAPI(title="AI量化交易平台 API", version="1.0.0")
settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """未捕获异常统一返回 JSON，避免前端解析 HTML 报错"""
    import traceback
    print(f"[ERROR] {exc}")
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"success": False, "data": None, "message": str(exc), "code": 500},
    )

# 注册路由，基础路径 /api/v1
app.include_router(auth.router, prefix="/api/v1/auth", tags=["认证"])
app.include_router(users.router, prefix="/api/v1/users", tags=["用户"])
app.include_router(broker.router, prefix="/api/v1/broker", tags=["交易所绑定"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["仪表盘"])
app.include_router(market.router, prefix="/api/v1/market", tags=["行情"])
app.include_router(portfolio.router, prefix="/api/v1/portfolio", tags=["投资组合"])
app.include_router(assets.router, prefix="/api/v1/assets", tags=["资产"])
app.include_router(trading.router, prefix="/api/v1/trading", tags=["交易"])
# subscription 需在 strategies 之前，否则 /subscriptions 会匹配 /{strategy_id}
app.include_router(subscription.router, prefix="/api/v1/strategies", tags=["订阅"])
app.include_router(strategies.router, prefix="/api/v1/strategies", tags=["策略"])
app.include_router(risk.router, prefix="/api/v1/risk", tags=["风险"])


@app.get("/")
def root():
    return {"message": "AI量化交易平台 API", "version": "1.0.0"}


@app.get("/api/v1/health")
def health():
    return {"success": True, "data": {"status": "ok", "backend_version": "gate-v2"}}


# 版本标识：若响应含 "backend_version": "gate-v2" 则说明运行的是本仓库最新代码（无 mock）
@app.get("/api/v1/debug/version")
def debug_version():
    return {"success": True, "data": {"backend_version": "gate-v2"}, "message": "ok", "code": 200}


def _get_uid(authorization: str = Header(None)) -> int | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    payload = decode_token(authorization[7:])
    return int(payload["sub"]) if payload and payload.get("sub") else None


# 调试接口：直接调用 Gate API，在主应用注册确保可用（不依赖 broker 模块）
@app.get("/api/v1/broker/testgate")
def broker_testgate(mode: str = Query(None), authorization: str = Header(None), db: Session = Depends(get_db)):
    """直接调用 Gate API 返回原始账户数据，用于验证数据来源"""
    uid = _get_uid(authorization)
    if not uid:
        return {"success": False, "data": None, "message": "请先登录", "code": 401}
    m = mode or get_mode(db, uid)
    b = get_broker(db, uid, m)
    if not b:
        return {"success": False, "data": None, "message": f"未绑定{m}模式", "code": 400}
    try:
        accounts = get_spot_accounts(m, b.api_key_enc, b.api_secret_enc)
        avail, frozen, total = get_total_balance_usdt(m, b.api_key_enc, b.api_secret_enc)
        return {
            "success": True,
            "data": {
                "mode": m,
                "gate_host": HOST_SIMULATED if m == "simulated" else HOST_REAL,
                "raw_accounts": accounts,
                "computed": {"available_usdt": round(avail, 4), "frozen_usdt": round(frozen, 4), "total_usdt": round(total, 4)},
            },
            "message": "ok",
            "code": 200,
        }
    except Exception as e:
        return {"success": False, "data": {"error": str(e)}, "message": str(e), "code": 500}


if __name__ == "__main__":
    import uvicorn
    import os
    port = settings.PORT
    print("\n" + "=" * 50)
    print("  gate-v2 后端 (本仓库)")
    print("  http://127.0.0.1:{port}  (gate-v2) 按 Ctrl+C 停止".format(port=port))
    print("  工作目录: {cwd}".format(cwd=os.getcwd()))
    print("=" * 50 + "\n")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
