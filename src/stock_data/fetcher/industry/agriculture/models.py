"""农业产业数据记录模型。"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class AgriculturePorkRecord:
    """农业农村部生猪产能月报、出栏价格与猪粮比记录。"""

    report_month: str
    trade_date: date
    sow_stock_million_heads: float | None = None
    sow_stock_yoy: float | None = None
    sow_stock_mom: float | None = None
    pig_price_cny_per_kg: float | None = None
    pig_price_yoy: float | None = None
    hog_to_grain_ratio: float | None = None
    pig_farming_profit_cny_head: float | None = None
    unit: str = "million_heads/cny_per_kg"
    source: str = "MARA"
    source_url: str = "http://www.moa.gov.cn/"
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""


__all__ = ["AgriculturePorkRecord"]
