"""半导体产业数据记录模型。"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class SemiconductorEquipmentRecord:
    """SEAJ / SEMI 半导体设备月度出货额记录。"""

    report_month: str
    trade_date: date
    billings_3mma_jpy: float
    yoy_growth_3mma: float | None = None
    mom_growth_3mma: float | None = None
    unit: str = "billion_jpy"
    source: str = "SEAJ"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""
    raw_content_sha256: str = ""
    raw_snapshot_path: str = ""
    billings_jpy_raw: str | float | None = None
    yoy_reported: str | float | None = None
    mom_reported: str | float | None = None
    billings_raw: str | None = None
    yoy_raw: str | None = None
    mom_raw: str | None = None


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
    raw_content_sha256: str = ""
    raw_snapshot_path: str = ""
    worldwide_raw: str | None = None
    americas_raw: str | None = None
    europe_raw: str | None = None
    japan_raw: str | None = None
    asia_pacific_raw: str | None = None
    china_sales_raw: str | None = None
    china_yoy_growth_raw: str | None = None
    china_mom_growth_raw: str | None = None


@dataclass(frozen=True)
class SemiconductorInventoryRecord:
    """全球 IDM 季度财报库存与营业成本记录。"""

    symbol: str
    report_quarter: str
    trade_date: date
    inventory_usd_million: float
    cost_of_revenue_usd_million: float
    unit: str = "million_usd"
    source: str = "SEC_EDGAR_10Q_10K_20F_6K"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""
    inventory_usd_raw: str | None = None
    cost_of_revenue_usd_raw: str | None = None
    source_period_end: date | None = None
    fiscal_period: str = ""
    raw_content_sha256: str = ""
    raw_snapshot_path: str = ""
    cost_of_revenue_annual_raw: str | None = None
    cost_of_revenue_derivation: str = ""


@dataclass(frozen=True)
class SemiconductorLeadRecord:
    """半导体高频先导指标记录 (台积电月度营运营收)。"""

    report_month: str
    trade_date: date
    tsmc_revenue_ntd_million: float
    tsmc_revenue_usd_million: float | None = None
    tsmc_revenue_yoy: float | None = None
    tsmc_revenue_mom: float | None = None
    tsmc_revenue_3mma_usd: float | None = None
    unit: str = "million_ntd/usd"
    source: str = "TSMC"
    source_url: str = "https://investor.tsmc.com/english/monthly-revenue"
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""
    raw_content_sha256: str = ""
    raw_snapshot_path: str = ""
    tsmc_month_raw: str | None = None
    tsmc_revenue_raw: str | None = None
    tsmc_revenue_yoy_raw: str | None = None


@dataclass(frozen=True)
class ChipLeadTimeRecord:
    """全球芯片交付周期 (Chip Lead Time / 货期) 月度先导指标记录。"""

    report_month: str
    trade_date: date
    avg_lead_time_weeks: float
    mcu_lead_time_weeks: float | None = None
    analog_lead_time_weeks: float | None = None
    discrete_lead_time_weeks: float | None = None
    compute_lead_time_weeks: float | None = None
    lead_time_yoy_weeks: float | None = None
    lead_time_mom_weeks: float | None = None
    lead_time_status: str = "normal"
    unit: str = "weeks"
    source: str = "Susquehanna/Distributor"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""
    raw_content_sha256: str = ""
    raw_snapshot_path: str = ""
    lead_time_raw: str | None = None
    sku_details_raw: str | None = None
