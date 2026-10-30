"""光伏与硅料产业数据记录模型。"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class SolarCapacityRecord:
    """国家能源局 (NEA) 全国光伏新增与累计装机容量记录。"""

    report_month: str
    trade_date: date
    monthly_new_capacity_gw: float | None = None
    monthly_new_capacity_3mma: float | None = None
    cumulative_capacity_gw: float | None = None
    yoy_growth: float | None = None
    yoy_growth_3mma: float | None = None
    mom_growth_3mma: float | None = None
    unit: str = "gw/ratio"
    source: str = "NEA"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""
    raw_content_sha256: str = ""
    raw_snapshot_path: str = ""
    monthly_new_capacity_gw_raw: str | None = None
    cumulative_capacity_gw_raw: str | None = None
    yoy_growth_raw: str | None = None


@dataclass(frozen=True)
class SolarCellNbsRecord:
    """国家统计局太阳能电池月度产量记录。"""

    report_month: str
    trade_date: date
    output_current: float | None = None
    output_cumulative: float | None = None
    output_yoy: float | None = None
    output_cum_yoy: float | None = None
    output_current_3mma: float | None = None
    yoy_growth_3mma: float | None = None
    mom_growth_3mma: float | None = None
    unit: str = "ten_thousand_kw/ratio"
    source: str = "NBS"
    source_url: str = "https://data.stats.gov.cn/"
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""
    raw_content_sha256: str = ""
    raw_snapshot_path: str = ""
    output_current_raw: str | None = None
    output_cumulative_raw: str | None = None
    output_yoy_raw: str | None = None
    output_cum_yoy_raw: str | None = None


@dataclass(frozen=True)
class SolarPriceChainRecord:
    """光伏产业链中微观价格链条与周期状态记录 (周频/旬频)。"""

    report_date: str
    trade_date: date
    polysilicon_price_cny_kg: float | None = None
    wafer_price_cny_piece: float | None = None
    cell_price_cny_watt: float | None = None
    module_price_cny_watt: float | None = None
    module_price_yoy: float | None = None
    module_price_mom: float | None = None
    price_cycle_stage: str | None = None
    unit: str = "cny_per_unit"
    source: str = "PVInfoLink/SMM"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""
    raw_content_sha256: str = ""
    raw_snapshot_path: str = ""
    polysilicon_price_cny_kg_raw: str | None = None
    wafer_price_cny_piece_raw: str | None = None
    cell_price_cny_watt_raw: str | None = None
    module_price_cny_watt_raw: str | None = None


@dataclass(frozen=True)
class SiliconWaferMonthlyRecord:
    """硅业分会多晶硅/单晶硅片月度产出、开工率与库存记录。"""

    report_month: str
    trade_date: date
    polysilicon_output_w_tons: float | None = None
    polysilicon_output_yoy: float | None = None
    polysilicon_operating_rate: float | None = None
    derived_polysilicon_utilization_rate: float | None = None
    wafer_output_gw: float | None = None
    wafer_output_yoy: float | None = None
    wafer_operating_rate: float | None = None
    derived_wafer_utilization_rate: float | None = None
    polysilicon_inventory_w_tons: float | None = None
    unit: str = "ten_thousand_tons/gw/ratio"
    source: str = "Silicon_Branch_Antaike"
    source_url: str = "http://www.silicon.net.cn/"
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""
    raw_content_sha256: str = ""
    raw_snapshot_path: str = ""
    capacity_raw_content_sha256: str = ""
    capacity_raw_snapshot_path: str = ""
    polysilicon_output_w_tons_raw: str | None = None
    polysilicon_output_yoy_raw: str | None = None
    polysilicon_operating_rate_raw: str | None = None
    wafer_output_gw_raw: str | None = None
    wafer_output_yoy_raw: str | None = None
    wafer_operating_rate_raw: str | None = None
    polysilicon_inventory_w_tons_raw: str | None = None
    polysilicon_capacity_annual_w_tons_raw: str | None = None
    wafer_capacity_annual_gw_raw: str | None = None
    polysilicon_capacity_annual_w_tons: float | None = None
    wafer_capacity_annual_gw: float | None = None


@dataclass(frozen=True)
class SolarSupplyDemandRecord:
    """光伏供需剪刀差、装机消化比与过剩敞口对账记录。"""

    report_month: str
    trade_date: date
    supply_cell_gw: float
    demand_install_gw: float
    monthly_surplus_gw: float
    domestic_absorption_ratio: float | None = None
    supply_cell_yoy: float | None = None
    demand_install_yoy: float | None = None
    scissors_spread_yoy: float | None = None
    unit: str = "gw/ratio"
    source: str = "Derived_From_NBS_And_NEA"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "derived"
    collected_at: str = ""


@dataclass(frozen=True)
class PolysiliconSupplyMonthlyRecord:
    """多晶硅月度供给与开工率事实记录。"""

    report_month: str
    trade_date: date
    production_w_tons: float | None = None
    production_yoy: float | None = None
    production_mom: float | None = None
    capacity_annual_w_tons: float | None = None
    operating_rate: float | None = None
    derived_utilization_rate: float | None = None
    unit: str = "ten_thousand_tons/ratio"
    source: str = "Silicon_Branch_Antaike"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""


@dataclass(frozen=True)
class PolysiliconInventoryMonthlyRecord:
    """多晶硅月度社会库存与可用周数事实记录。"""

    report_month: str
    trade_date: date
    inventory_w_tons: float | None = None
    inventory_change_w_tons: float | None = None
    inventory_weeks: float | None = None
    inventory_status: str | None = None
    unit: str = "ten_thousand_tons/weeks"
    source: str = "Silicon_Branch_Antaike"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""


@dataclass(frozen=True)
class PvWaferMonthlyRecord:
    """单晶硅片月度产出、开工率与折算多晶硅需求事实记录。"""

    report_month: str
    trade_date: date
    wafer_output_gw: float | None = None
    wafer_output_yoy: float | None = None
    wafer_operating_rate: float | None = None
    derived_wafer_utilization_rate: float | None = None
    silicon_consumption_ratio: float | None = None
    implied_silicon_demand_w_tons: float | None = None
    unit: str = "gw/ten_thousand_tons/ratio"
    source: str = "Silicon_Branch_Antaike"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""


@dataclass(frozen=True)
class PolysiliconBalanceRecord:
    """多晶硅月度物理供需平衡、隐式消化与对账残差记录。"""

    report_month: str
    trade_date: date
    domestic_production_w_tons: float | None = None
    net_imports_w_tons: float | None = None
    total_supply_w_tons: float | None = None
    implied_demand_w_tons: float | None = None
    theoretical_surplus_w_tons: float | None = None
    observed_inventory_w_tons: float | None = None
    observed_inventory_change_w_tons: float | None = None
    inventory_weeks: float | None = None
    reconciliation_residual_w_tons: float | None = None
    supply_yoy: float | None = None
    demand_yoy: float | None = None
    scissors_spread_yoy: float | None = None
    cycle_score: float | None = None
    unit: str = "ten_thousand_tons/gw/ratio"
    source: str = "Derived_Polysilicon_Balance"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "derived"
    collected_at: str = ""
