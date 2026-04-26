"""行情/K 线 API"""
from fastapi import APIRouter, Query
from utils.gate_client import list_candlesticks, list_futures_candlesticks

router = APIRouter()


@router.get("/candlesticks")
def get_candlesticks(
    symbol: str = Query(..., description="现货交易对或合约名，如 BTC_USDT"),
    interval: str = Query("1h", description="1m,5m,15m,30m,1h,4h,1d,7d,30d"),
    from_ts: int = Query(None),
    to_ts: int = Query(None),
    limit: int = Query(300, le=1000),
    mode: str = Query("real"),
    market: str = Query("spot", description="spot 现货；futures 合约 U 本位"),
):
    try:
        if market in ("futures", "futures_usdt", "contract"):
            data = list_futures_candlesticks(symbol, interval, from_ts, to_ts, limit, mode, "usdt")
        else:
            data = list_candlesticks(symbol, interval, from_ts, to_ts, limit, mode)
        return {"success": True, "data": data, "message": "ok", "code": 200}
    except Exception as e:
        return {"success": False, "data": [], "message": str(e), "code": 500}
