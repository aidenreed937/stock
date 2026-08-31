"""光伏装机容量 (NEA) 与光伏产业链价格链条数据工程子包。"""

from stock_data.fetcher.industry.power.collector import SolarCollector
from stock_data.fetcher.industry.power.pv_price_collector import (
    InfoLinkPvPriceCrawler,
    PvPriceChainCollector,
    parse_infolink_spot_price_html,
)
from stock_data.fetcher.industry.power.transform import (
    SOLAR_CAPACITY_SCHEMA,
    SOLAR_PRICE_CHAIN_SCHEMA,
    empty_solar_capacity,
    empty_solar_price_chain,
    records_to_solar_frame,
    records_to_solar_price_chain_frame,
)

__all__ = [
    "SOLAR_CAPACITY_SCHEMA",
    "SOLAR_PRICE_CHAIN_SCHEMA",
    "InfoLinkPvPriceCrawler",
    "PvPriceChainCollector",
    "SolarCollector",
    "empty_solar_capacity",
    "empty_solar_price_chain",
    "parse_infolink_spot_price_html",
    "records_to_solar_frame",
    "records_to_solar_price_chain_frame",
]
