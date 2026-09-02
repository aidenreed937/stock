"""半导体产业数据记录模型。"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class SemiconductorEquipmentRecord:
    """SEAJ / SEMI 半导体设备月度出货额记录。"""

    report_month: str
    trade_date: date
    billings_jpy_billion: float
    billings_3mma_jpy: float | None = None
    yoy_growth: float | None = None
    yoy_growth_3mma: float | None = None
    mom_growth_3mma: float | None = None
    unit: str = "billion_jpy"
    source: str = "SEAJ"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""


@dataclass(frozen=True)
class SemiconductorSalesRecord:
    """SIA / WSTS 全球半导体月度销售额记录。"""

    report_month: str
    trade_date: date
    global_sales_usd: float
    china_sales_usd: float | None = None
    china_yoy_growth: float | None = None
    china_mom_growth: float | None = None
    americas_sales_usd: float | None = None
    europe_sales_usd: float | None = None
    japan_sales_usd: float | None = None
    asia_pacific_sales_usd: float | None = None
    yoy_growth: float | None = None
    mom_growth: float | None = None
    unit: str = "billion_usd"
    source: str = "SIA/WSTS"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""
