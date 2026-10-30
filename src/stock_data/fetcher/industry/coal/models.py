"""煤炭产业数据记录模型。"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class CoalMarketRecord:
    """煤炭行业动力煤港口平仓价与重点电厂存煤可用天数记录。"""

    report_date: str
    trade_date: date
    q5500_fob_price_cny: float | None = None
    coking_coal_price_cny: float | None = None
    power_plant_inventory_million_ton: float | None = None
    power_plant_daily_burn_ten_thousand_ton: float | None = None
    power_plant_available_days: float | None = None
    qinhuangdao_inventory_million_ton: float | None = None
    q5500_price_yoy: float | None = None
    q5500_price_mom: float | None = None
    unit: str = "cny_per_ton/million_tons/days"
    source: str = "CCTD/Sxcoal"
    source_url: str = "https://www.cctd.com.cn/"
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""


__all__ = ["CoalMarketRecord"]
