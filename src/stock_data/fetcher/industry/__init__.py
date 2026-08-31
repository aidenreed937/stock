"""垂直产业中观量化数据工程包。

包含 9 大子领域:
- customs: 海关重点品类进出口贸易 (UN Comtrade / GACC)
- semiconductor: 全球半导体月度销售额 (SIA / WSTS)
- automotive: 新能源汽车月度产销与渗透率 (CPCA / CAAM)
- power: 全国光伏新增与累计装机容量 (NEA)
- metals: 有色大宗金属价格与显性库存 (SHFE / SGE / AkShare)
- pharma: 中国创新药海外 License-out 交易 (PharmaCube)
- cloud: 北美云厂商季度 AI 资本开支 (10-Q)
- machinery: 工程机械月度产销与小松开工小时 (CCMA / Komatsu)
- shipping: 全球海运与油运日频运价指数 (Baltic Exchange / SCFI)
"""

from stock_data.fetcher.industry.automotive import (
    NEV_MONTHLY_SCHEMA,
    NevCollector,
    empty_nev_monthly,
    records_to_nev_frame,
)
from stock_data.fetcher.industry.cloud import (
    CLOUD_CAPEX_SCHEMA,
    CloudCapexCollector,
    empty_cloud_capex,
    records_to_cloud_capex_frame,
)
from stock_data.fetcher.industry.common import (
    get_month_end_date,
    read_raw_text,
    save_curated_fact,
    save_raw_snapshot,
)
from stock_data.fetcher.industry.customs import (
    CUSTOMS_TRADE_SCHEMA,
    ComtradeCollector,
    empty_customs_trade,
    get_hs6_query_list,
    load_hs_catalog,
    parse_comtrade_items,
    parse_raw_csv_rows,
    records_to_customs_trade_frame,
)
from stock_data.fetcher.industry.machinery import (
    CONSTRUCTION_MACHINERY_SCHEMA,
    MachineryCollector,
    empty_construction_machinery,
    records_to_machinery_frame,
)
from stock_data.fetcher.industry.metals import (
    NON_FERROUS_METALS_SCHEMA,
    NonFerrousCollector,
    empty_non_ferrous_metals,
    records_to_metals_frame,
)
from stock_data.fetcher.industry.models import (
    CloudCapexRecord,
    ConstructionMachineryRecord,
    CustomsTradeRecord,
    NevMonthlyRecord,
    NonFerrousMetalsRecord,
    PharmaLicenseOutRecord,
    SemiconductorSalesRecord,
    ShippingIndicesRecord,
    SolarCapacityRecord,
)
from stock_data.fetcher.industry.pharma import (
    PHARMA_LICENSE_OUT_SCHEMA,
    PharmaBdCollector,
    empty_pharma_license_out,
    records_to_pharma_bd_frame,
)
from stock_data.fetcher.industry.pipeline import sync_all_industry_metrics
from stock_data.fetcher.industry.power import (
    SOLAR_CAPACITY_SCHEMA,
    SolarCollector,
    empty_solar_capacity,
    records_to_solar_frame,
)
from stock_data.fetcher.industry.semiconductor import (
    SEMICONDUCTOR_SALES_SCHEMA,
    SemiconductorCollector,
    empty_semiconductor_sales,
    records_to_semiconductor_frame,
)
from stock_data.fetcher.industry.shipping import (
    SHIPPING_INDICES_SCHEMA,
    ShippingCollector,
    empty_shipping_indices,
    records_to_shipping_frame,
)

__all__ = [
    "CLOUD_CAPEX_SCHEMA",
    "CONSTRUCTION_MACHINERY_SCHEMA",
    "CUSTOMS_TRADE_SCHEMA",
    "NEV_MONTHLY_SCHEMA",
    "NON_FERROUS_METALS_SCHEMA",
    "PHARMA_LICENSE_OUT_SCHEMA",
    "SEMICONDUCTOR_SALES_SCHEMA",
    "SHIPPING_INDICES_SCHEMA",
    "SOLAR_CAPACITY_SCHEMA",
    "CloudCapexCollector",
    "CloudCapexRecord",
    "ComtradeCollector",
    "ConstructionMachineryRecord",
    "CustomsTradeRecord",
    "MachineryCollector",
    "NevCollector",
    "NevMonthlyRecord",
    "NonFerrousCollector",
    "NonFerrousMetalsRecord",
    "PharmaBdCollector",
    "PharmaLicenseOutRecord",
    "SemiconductorCollector",
    "SemiconductorSalesRecord",
    "ShippingCollector",
    "ShippingIndicesRecord",
    "SolarCapacityRecord",
    "SolarCollector",
    "empty_cloud_capex",
    "empty_construction_machinery",
    "empty_customs_trade",
    "empty_nev_monthly",
    "empty_non_ferrous_metals",
    "empty_pharma_license_out",
    "empty_semiconductor_sales",
    "empty_shipping_indices",
    "empty_solar_capacity",
    "get_hs6_query_list",
    "get_month_end_date",
    "load_hs_catalog",
    "parse_comtrade_items",
    "parse_raw_csv_rows",
    "read_raw_text",
    "records_to_cloud_capex_frame",
    "records_to_customs_trade_frame",
    "records_to_machinery_frame",
    "records_to_metals_frame",
    "records_to_nev_frame",
    "records_to_pharma_bd_frame",
    "records_to_semiconductor_frame",
    "records_to_shipping_frame",
    "records_to_solar_frame",
    "save_curated_fact",
    "save_raw_snapshot",
    "sync_all_industry_metrics",
]
