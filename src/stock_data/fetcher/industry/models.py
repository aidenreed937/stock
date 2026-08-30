"""垂直产业景气指标契约模型。"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class SemiconductorSalesRecord:
    """SIA / WSTS 全球半导体月度销售额记录。"""

    report_month: str  # YYYY-MM
    trade_date: date  # 月末发布对齐日期
    global_sales_usd: float  # 全球销售额 (十亿美元，3MMA)
    americas_sales_usd: float | None = None
    europe_sales_usd: float | None = None
    japan_sales_usd: float | None = None
    china_sales_usd: float | None = None
    asia_pacific_other_sales_usd: float | None = None
    yoy_growth: float | None = None  # 同比增速 (小数，如 0.15 记 15%)
    mom_growth: float | None = None  # 环比增速


@dataclass(frozen=True)
class NevMonthlyRecord:
    """乘联会 / 中汽协新能源汽车月度产销与渗透率记录。"""

    report_month: str  # YYYY-MM
    trade_date: date  # 月末对齐日期
    wholesale_volume_ten_thousand: float  # 批发销量 (万辆)
    retail_volume_ten_thousand: float | None = None  # 零售销量 (万辆)
    export_volume_ten_thousand: float | None = None  # 出口销量 (万辆)
    penetration_rate: float | None = None  # 渗透率 (小数，如 0.45 记 45%)
    battery_installation_gwh: float | None = None  # 动力电池装车量 (GWh)
    yoy_growth: float | None = None  # 同比增速


@dataclass(frozen=True)
class SolarCapacityRecord:
    """国家能源局 (NEA) 全国光伏新增与累计装机容量记录。"""

    report_month: str  # YYYY-MM
    trade_date: date  # 月度对齐日期
    monthly_new_capacity_gw: float  # 当月新增装机容量 (GW)
    cumulative_capacity_gw: float | None = None  # 累计装机容量 (GW)
    yoy_growth: float | None = None  # 当月新增同比增速
