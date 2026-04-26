"""机构级 Brinson 归因与简化 Barra 风格风险模型（多资产对齐面板）"""
from services.analytics.brinson import brinson_fachler, brinson_result_to_json
from services.analytics.config import default_sector_map
from services.analytics.panel import build_brinson_panel_from_candles
from services.analytics.risk_model import formal_risk_analysis, risk_result_to_json

__all__ = [
    "brinson_fachler",
    "brinson_result_to_json",
    "default_sector_map",
    "build_brinson_panel_from_candles",
    "formal_risk_analysis",
    "risk_result_to_json",
]
