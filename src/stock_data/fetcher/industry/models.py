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
    wholesale_volume_3mma: float | None = None  # 3个月移动平均销量 (平滑季节性与春节脉冲)
    retail_volume_ten_thousand: float | None = None  # 零售销量
    export_volume_ten_thousand: float | None = None  # 出口销量
    penetration_rate: float | None = None  # 新能源乘用车零售渗透率 (消费端需求景气度)
    battery_installation_gwh: float | None = None  # 动力电池装车量 (GWh)
    yoy_growth: float | None = None  # 批发销量同比增速
    yoy_growth_3mma: float | None = None  # 3MMA 同比增速 (与半导体 3MMA 同频可比)
    mom_growth_3mma: float | None = None  # 3MMA 环比增速 / 斜率
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
    monthly_new_capacity_3mma: float | None = None  # 3个月移动平均新增装机 (平滑年底抢装脉冲)
    cumulative_capacity_gw: float | None = None  # 累计装机容量
    yoy_growth: float | None = None  # 当月新增同比增速
    yoy_growth_3mma: float | None = None  # 3MMA 同比增速 (与半导体 3MMA 同频可比)
    mom_growth_3mma: float | None = None  # 3MMA 环比增速 / 斜率
    unit: str = "gw"  # 显式计量单位: 吉瓦 (GW / 百万千瓦)
    source: str = "NEA"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"  # actual | derived | estimated | revised
    collected_at: str = ""


@dataclass(frozen=True)
class NonFerrousMetalsRecord:
    """有色大宗金属价格与显性库存记录 (含碳酸锂/铜/铝/金/库存)。"""

    report_date: str  # YYYY-MM-DD
    trade_date: date  # 交易日
    lithium_carbonate_price: float | None = None  # 碳酸锂期货主力结算价 (元/吨)
    shfe_copper_price: float | None = None  # 沪铜期货主力结算价 (元/吨)
    shfe_aluminum_price: float | None = None  # 沪铝期货主力结算价 (元/吨)
    sge_gold_price: float | None = None  # 上海黄金交易所 Au99.99 现货收盘价 (元/克)
    copper_inventory_ton: float | None = None  # 上期所铜显性库存 (吨)
    unit: str = "mixed"  # 显式计量单位说明
    source: str = "AkShare"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"  # actual | derived | estimated | revised
    collected_at: str = ""


@dataclass(frozen=True)
class TransformerExportRecord:
    """海关变压器月度出口金额、数量与均价记录 (HS 850421-850423等)。"""

    report_month: str  # YYYY-MM
    trade_date: date  # 月末自然日
    export_value_million_usd: float  # 当月出口金额 (百万美元)
    export_volume_units: float | None = None  # 出口台数 (台)
    export_asp_usd: float | None = None  # 出口均价 (美元/台)
    export_value_3mma: float | None = None  # 3个月移动平均出口金额 (平滑船期脉冲)
    yoy_growth: float | None = None  # 当月出口金额同比增速
    yoy_growth_3mma: float | None = None  # 3MMA 同比增速
    mom_growth_3mma: float | None = None  # 3MMA 环比斜率
    unit: str = "million_usd"  # 显式计量单位: 百万美元
    source: str = "GACC"
    source_url: str = "http://stats.customs.gov.cn/"
    release_date: date | None = None
    data_status: str = "actual"  # actual | derived | estimated | revised
    collected_at: str = ""


@dataclass(frozen=True)
class PharmaLicenseOutRecord:
    """中国创新药海外 License-out (BD) 交易首付款与总交易金额月度记录。"""

    report_month: str  # YYYY-MM
    trade_date: date  # 月末自然日
    monthly_upfront_million_usd: float  # 当月出海首付款总额 (百万美元)
    monthly_total_deal_million_usd: float  # 当月总交易金额 (百万美元)
    deal_count: int  # 当月交易起数
    upfront_3mma: float | None = None  # 3个月移动平均首付款 (平滑大单脉冲)
    yoy_growth_3mma: float | None = None  # 3MMA 首付款同比增速
    mom_growth_3mma: float | None = None  # 3MMA 首付款环比斜率
    unit: str = "million_usd"  # 显式计量单位: 百万美元
    source: str = "PharmaCube/Announcements"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"  # actual | derived | estimated | revised
    collected_at: str = ""


@dataclass(frozen=True)
class OpticalModuleExportRecord:
    """海关光通信收发模块出口金额、数量与均价月度记录 (HS 85176221/85176229等)。"""

    report_month: str  # YYYY-MM
    trade_date: date  # 月末自然日
    export_value_million_usd: float  # 当月出口金额 (百万美元)
    export_volume_ten_thousand: float | None = None  # 出口数量 (万个)
    export_asp_usd: float | None = None  # 出口均价 (美元/个)
    export_value_3mma: float | None = None  # 3个月移动平均出口金额 (平滑海运船期)
    yoy_growth: float | None = None  # 当月出口额同比增速
    yoy_growth_3mma: float | None = None  # 3MMA 同比增速
    mom_growth_3mma: float | None = None  # 3MMA 环比斜率
    unit: str = "million_usd"  # 显式计量单位: 百万美元
    source: str = "GACC"
    source_url: str = "http://stats.customs.gov.cn/"
    release_date: date | None = None
    data_status: str = "actual"  # actual | derived | estimated | revised
    collected_at: str = ""


@dataclass(frozen=True)
class CloudCapexRecord:
    """北美四大云厂商 (MSFT/GOOG/META/AMZN) 季度 AI 资本开支记录。"""

    report_quarter: str  # YYYY-Q1/Q2/Q3/Q4
    trade_date: date  # 季度末自然日
    total_capex_billion_usd: float  # 四大云厂商合计 CapEx (十亿美元)
    msft_capex_billion_usd: float | None = None  # 微软 CapEx
    goog_capex_billion_usd: float | None = None  # 谷歌 CapEx
    meta_capex_billion_usd: float | None = None  # Meta CapEx
    amzn_capex_billion_usd: float | None = None  # 亚马逊 CapEx
    yoy_growth: float | None = None  # 合计 CapEx 同比增速
    qoq_growth: float | None = None  # 合计 CapEx 环比增速
    unit: str = "billion_usd"  # 显式计量单位: 十亿美元
    source: str = "Company Filings (10-Q/10-K)"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"  # actual | derived | estimated | revised
    collected_at: str = ""


@dataclass(frozen=True)
class ConstructionMachineryRecord:
    """工程机械行业月度产销与小松挖掘机开工小时数记录 (CCMA/Komatsu)。"""

    report_month: str  # YYYY-MM
    trade_date: date  # 月末自然日
    excavator_total_units: float  # 挖掘机总销量 (台)
    excavator_domestic_units: float  # 挖掘机国内销量 (台)
    excavator_export_units: float  # 挖掘机出口销量 (台)
    komatsu_hours_china: float | None = None  # 小松中国区挖掘机月度开工小时数 (小时/月)
    komatsu_hours_yoy: float | None = None  # 小松工时同比增速
    export_ratio: float | None = None  # 出口销量占比 (export / total)
    excavator_total_3mma: float | None = None  # 3个月移动平均总销量
    yoy_growth: float | None = None  # 当月总销量同比增速
    yoy_growth_3mma: float | None = None  # 3MMA 总销量同比增速
    mom_growth_3mma: float | None = None  # 3MMA 环比斜率
    unit: str = "units/hours"  # 显式计量单位
    source: str = "CCMA/Komatsu"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"  # actual | derived | estimated | revised
    collected_at: str = ""


@dataclass(frozen=True)
class ShippingIndicesRecord:
    """全球海运与油运日频运价指数记录 (BDI/BDTI/BCTI/SCFI)。"""

    trade_date: date  # 交易日
    bdi_index: float  # 波罗的海干散货运价指数 (Baltic Dry Index)
    bdti_index: float | None = None  # 波罗的海原油运输指数 (Baltic Dirty Tanker Index)
    bcti_index: float | None = None  # 波罗的海成品油运输指数 (Baltic Clean Tanker Index)
    scfi_index: float | None = None  # 上海出口集装箱运价指数 (SCFI)
    bdi_ma200_bias: float | None = None  # BDI 相对 200 日均线偏离度 (%)
    bdti_ma200_bias: float | None = None  # BDTI 相对 200 日均线偏离度 (%)
    unit: str = "index_points"  # 点位
    source: str = "BalticExchange/SSE"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"  # actual | derived | estimated | revised
    collected_at: str = ""
