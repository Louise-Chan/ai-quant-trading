"""分析模块配置：行业映射、基准说明"""
from __future__ import annotations

# 交易对 → 板块（可扩展为读 DB / JSON）
DEFAULT_SECTOR_MAP: dict[str, str] = {
    "BTC_USDT": "主流币",
    "ETH_USDT": "主流币",
    "BNB_USDT": "平台币",
    "SOL_USDT": "Layer1",
    "ADA_USDT": "Layer1",
    "XRP_USDT": "支付",
    "DOGE_USDT": "Meme",
    "DOT_USDT": "跨链",
    "AVAX_USDT": "Layer1",
    "MATIC_USDT": "Layer2",
    "POL_USDT": "Layer2",
    "LINK_USDT": "DeFi",
    "UNI_USDT": "DeFi",
    "AAVE_USDT": "DeFi",
    "ATOM_USDT": "跨链",
    "LTC_USDT": "支付",
    "BCH_USDT": "支付",
    "ETC_USDT": "Layer1",
    "NEAR_USDT": "Layer1",
    "APT_USDT": "Layer1",
    "ARB_USDT": "Layer2",
    "OP_USDT": "Layer2",
    "FIL_USDT": "存储",
    "TRX_USDT": "公链",
    "TON_USDT": "公链",
    "SHIB_USDT": "Meme",
    "PEPE_USDT": "Meme",
}

BENCHMARK_DESCRIPTION = (
    "基准为组合内标的的等权买入持有（每期权重 1/N）；"
    "组合权重来自多因子信号（得分超过滚动分位则在该标的上持仓，按信号强度归一化）。"
)


def default_sector_map() -> dict[str, str]:
    return dict(DEFAULT_SECTOR_MAP)
