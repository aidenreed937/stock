"""垂直产业景气指标契约模型 (含显式计量单位、数据血统与状态元数据)。"""

from dataclasses import dataclass
from datetime import date

from stock_data.fetcher.industry.pharma.models import (
    PharmaBdAssetRecord,
    PharmaBdDealRecord,
    PharmaBdEventRecord,
    PharmaLicenseOutRecord,
)

__all__ = [
    "AgriculturePorkRecord",
    "ChemicalMarketRecord",
    "CloudCapexRecord",
    "CoalMarketRecord",
    "ConstructionMachineryRecord",
    "ConsumerElectronicsRecord",
    "CustomsTradeRecord",
    "LiquorWholesaleRecord",
    "NevMonthlyRecord",
    "NonFerrousMetalsRecord",
    "PharmaBdAssetRecord",
    "PharmaBdDealRecord",
    "PharmaBdEventRecord",
    "PharmaLicenseOutRecord",
    "SemiconductorLeadRecord",
    "SemiconductorSalesRecord",
    "ShippingIndicesRecord",
    "SolarCapacityRecord",
    "SolarPriceChainRecord",
]


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
    asia_pacific_other_sales_usd: float | None = None
    yoy_growth: float | None = None
    mom_growth: float | None = None
    unit: str = "billion_usd"
    source: str = "SIA/WSTS"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""


@dataclass(frozen=True)
class NevMonthlyRecord:
    """乘联会 / 中汽协新能源汽车月度产销与渗透率记录。"""

    report_month: str
    trade_date: date
    wholesale_volume_ten_thousand: float | None = None
    wholesale_volume_3mma: float | None = None
    retail_volume_ten_thousand: float | None = None
    export_volume_ten_thousand: float | None = None
    penetration_rate: float | None = None
    battery_installation_gwh: float | None = None
    yoy_growth: float | None = None
    yoy_growth_3mma: float | None = None
    mom_growth_3mma: float | None = None
    unit: str = "ten_thousand_units"
    source: str = "CPCA"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""


@dataclass(frozen=True)
class SolarCapacityRecord:
    """国家能源局 (NEA) 全国光伏新增与累计装机容量记录。"""

    report_month: str
    trade_date: date
    monthly_new_capacity_gw: float
    monthly_new_capacity_3mma: float | None = None
    cumulative_capacity_gw: float | None = None
    yoy_growth: float | None = None
    yoy_growth_3mma: float | None = None
    mom_growth_3mma: float | None = None
    unit: str = "gw"
    source: str = "NEA"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""


@dataclass(frozen=True)
class NonFerrousMetalsRecord:
    """有色大宗金属价格与显性库存记录 (含碳酸锂/铜/铝/金/库存)。"""

    report_date: str
    trade_date: date
    lithium_carbonate_price: float | None = None
    shfe_copper_price: float | None = None
    shfe_aluminum_price: float | None = None
    sge_gold_price: float | None = None
    copper_inventory_ton: float | None = None
    unit: str = "mixed"
    source: str = "AkShare"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""


@dataclass(frozen=True)
class CloudCapexRecord:
    """北美四大云厂商 (MSFT/GOOG/META/AMZN) 季度 AI 资本开支记录。"""

    report_quarter: str
    trade_date: date
    total_capex_billion_usd: float
    msft_capex_billion_usd: float | None = None
    goog_capex_billion_usd: float | None = None
    meta_capex_billion_usd: float | None = None
    amzn_capex_billion_usd: float | None = None
    yoy_growth: float | None = None
    qoq_growth: float | None = None
    unit: str = "billion_usd"
    source: str = "Company Filings (10-Q/10-K)"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""


@dataclass(frozen=True)
class ConstructionMachineryRecord:
    """工程机械行业月度产销与小松挖掘机开工小时数记录 (CCMA/Komatsu)。"""

    report_month: str
    trade_date: date
    excavator_total_units: float | None = None
    excavator_domestic_units: float | None = None
    excavator_export_units: float | None = None
    komatsu_hours_china: float | None = None
    komatsu_hours_yoy: float | None = None
    export_ratio: float | None = None
    excavator_total_3mma: float | None = None
    yoy_growth: float | None = None
    yoy_growth_3mma: float | None = None
    mom_growth_3mma: float | None = None
    unit: str = "units/hours"
    source: str = "CCMA/Komatsu"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""


@dataclass(frozen=True)
class ShippingIndicesRecord:
    """全球海运与油运日频运价指数记录 (BDI/BDTI/BCTI/SCFI)。"""

    trade_date: date
    bdi_index: float
    bdti_index: float | None = None
    bcti_index: float | None = None
    scfi_index: float | None = None
    bdi_ma200_bias: float | None = None
    bdti_ma200_bias: float | None = None
    unit: str = "index_points"
    source: str = "BalticExchange/SSE"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""


@dataclass(frozen=True)
class CustomsTradeRecord:
    """海关重点品类进出口月度标准化记录 (支持 GACC 与 UN Comtrade 双源)。"""

    category_key: str
    category_name: str
    product_key: str
    product_name: str
    hs_code: str
    hs_name: str
    report_month: str
    trade_date: date
    trade_direction: str
    export_value_usd: float
    export_volume: float | None = None
    quantity_unit: str = ""
    export_asp_usd: float | None = None
    target_l1_code: str = ""
    target_l1_name: str = ""
    target_l2_codes: str = ""
    target_l2_names: str = ""
    export_value_3mma: float | None = None
    yoy_growth_3mma: float | None = None
    mom_growth_3mma: float | None = None
    source: str = "UN_Comtrade"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""


@dataclass(frozen=True)
class SemiconductorLeadRecord:
    """半导体高频先导指标记录 (台积电月度营运营收与 DRAM 现货价格)。"""

    report_month: str
    trade_date: date
    tsmc_revenue_ntd_million: float
    tsmc_revenue_usd_million: float | None = None
    tsmc_revenue_yoy: float | None = None
    tsmc_revenue_mom: float | None = None
    tsmc_revenue_3mma_usd: float | None = None
    dram_dxi_index: float | None = None
    dram_spot_price_usd: float | None = None
    unit: str = "million_ntd/usd"
    source: str = "TSMC/DRAMeXchange"
    source_url: str = "https://investor.tsmc.com/chinese/monthly-revenue"
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""


@dataclass(frozen=True)
class ChemicalMarketRecord:
    """基础化工重点大宗品供需开工率、库存与价差记录。"""

    report_month: str
    trade_date: date
    mdi_operating_rate: float | None = None
    tio2_operating_rate: float | None = None
    refrigerant_r32_operating_rate: float | None = None
    mdi_price_cny: float | None = None  # 生意社聚合MDI参考价 (元/吨)
    tio2_price_cny: float | None = None  # 生意社钛白粉参考价 (元/吨)
    mdi_gross_spread_cny: float | None = None
    tio2_spread_cny: float | None = None
    refrigerant_r32_price_cny: float | None = None
    chemical_inventory_days: float | None = None
    unit: str = "percent/cny_per_ton"
    source: str = "Baichuan/Zhuochuang"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""


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
    price_cycle_stage: str = "bottom_rebound"
    unit: str = "cny_per_unit"
    source: str = "PVInfoLink/SMM"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""


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


@dataclass(frozen=True)
class LiquorWholesaleRecord:
    """高端名优白酒周度一批价与动销监测记录。"""

    report_date: str
    trade_date: date
    moutai_loose_price_cny: float | None = None
    moutai_boxed_price_cny: float | None = None
    wuliangye_puwu_price_cny: float | None = None
    guojiao1573_price_cny: float | None = None
    moutai_loose_price_yoy: float | None = None
    moutai_loose_price_mom: float | None = None
    unit: str = "cny_per_bottle"
    source: str = "TodayLiquorPrice"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""


@dataclass(frozen=True)
class ConsumerElectronicsRecord:
    """消费电子终端 (智能手机 / PC / 平板) 季度出货与 AI 渗透率记录 (IDC / Canalys)。"""

    report_quarter: str
    trade_date: date
    global_smartphone_shipments_million: float | None = None
    china_smartphone_shipments_million: float | None = None
    global_pc_shipments_million: float | None = None
    ai_phone_penetration_rate: float | None = None
    ai_pc_penetration_rate: float | None = None
    smartphone_yoy_growth: float | None = None
    pc_yoy_growth: float | None = None
    apple_shipments_million: float | None = None
    transsion_shipments_million: float | None = None
    unit: str = "million_units/percent"
    source: str = "IDC/Canalys"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""


@dataclass(frozen=True)
class CoalMarketRecord:
    """煤炭行业动力煤港口平仓价与重点电厂存煤可用天数记录 (CCTD/Sxcoal)。"""

    report_date: str  # YYYY-MM-DD
    trade_date: date  # 对齐交易日
    q5500_fob_price_cny: float | None = None  # 秦皇岛港 Q5500 动力煤平仓价 (元/吨)
    coking_coal_price_cny: float | None = None  # 京唐港主焦煤库提价 (元/吨)
    power_plant_inventory_million_ton: float | None = None  # 沿海八省电厂存煤量 (百万吨)
    power_plant_daily_burn_ten_thousand_ton: float | None = None  # 沿海八省电厂日耗 (万吨/日)
    power_plant_available_days: float | None = None  # 重点电厂存煤可用天数 (天)
    qinhuangdao_inventory_million_ton: float | None = None  # 秦皇岛港煤炭库存 (百万吨)
    q5500_price_yoy: float | None = None
    q5500_price_mom: float | None = None
    unit: str = "cny_per_ton/million_tons/days"
    source: str = "CCTD/Sxcoal"
    source_url: str = "https://www.cctd.com.cn/"
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""
