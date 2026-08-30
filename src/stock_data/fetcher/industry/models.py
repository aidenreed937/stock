"""垂直产业景气指标契约模型 (含显式计量单位、数据血统与状态元数据)。"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class SemiconductorSalesRecord:
    """SIA / WSTS 全球半导体月度销售额记录。"""

    report_month: str  # YYYY-MM
    trade_date: date  # 月末自然日
    global_sales_usd: float  # 全球销售额 (3MMA)
    china_sales_usd: float | None = None  # 中国区销售额
    china_yoy_growth: float | None = None  # 中国区同比增速 (小数，如 0.234 记 23.4%)
    china_mom_growth: float | None = None  # 中国区月环比增速
    americas_sales_usd: float | None = None
    europe_sales_usd: float | None = None
    japan_sales_usd: float | None = None
    asia_pacific_other_sales_usd: float | None = None
    yoy_growth: float | None = None  # 全球同比增速 (小数，如 0.15 记 15%)
    mom_growth: float | None = None  # 全球环比增速
    unit: str = "billion_usd"  # 显式计量单位: 十亿美元 (Billions USD)
    source: str = "SIA/WSTS"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"  # actual | derived | estimated | revised
    collected_at: str = ""


@dataclass(frozen=True)
class NevMonthlyRecord:
    """乘联会 / 中汽协新能源汽车月度产销与渗透率记录。"""

    report_month: str  # YYYY-MM
    trade_date: date  # 月末自然日
    wholesale_volume_ten_thousand: float  # 批发销量 (车企出货与产业链需求)
    retail_volume_ten_thousand: float | None = None  # 零售销量
    export_volume_ten_thousand: float | None = None  # 出口销量
    penetration_rate: float | None = None  # 新能源乘用车零售渗透率 (消费端需求景气度)
    battery_installation_gwh: float | None = None  # 动力电池装车量 (GWh)
    yoy_growth: float | None = None  # 批发销量同比增速
    unit: str = "ten_thousand_units"  # 显式计量单位: 万辆
    source: str = "CPCA"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"  # actual | derived | estimated | revised
    collected_at: str = ""


@dataclass(frozen=True)
class SolarCapacityRecord:
    """国家能源局 (NEA) 全国光伏新增与累计装机容量记录。"""

    report_month: str  # YYYY-MM
    trade_date: date  # 月末自然日
    monthly_new_capacity_gw: float  # 当月新增装机容量 (月度差分)
    cumulative_capacity_gw: float | None = None  # 累计装机容量
    yoy_growth: float | None = None  # 当月新增同比增速
    unit: str = "gw"  # 显式计量单位: 吉瓦 (GW / 百万千瓦)
    source: str = "NEA"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"  # actual | derived | estimated | revised
    collected_at: str = ""
