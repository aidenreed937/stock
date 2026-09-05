"""光伏产业采集器。"""

from stock_data.fetcher.industry.power.collectors.infolink import (
    INFOLINK_HEADERS,
    INFOLINK_HISTORY_URL,
    InfoLinkPvPriceCrawler,
    InfoLinkSpotPriceHtmlParser,
    PvPriceChainCollector,
    compute_pv_price_derivatives,
    load_pv_price_raw_csv,
    save_pv_price_raw_csv,
)
from stock_data.fetcher.industry.power.collectors.nbs import (
    NBS_EXTERNAL_QUERY_URL,
    NBS_HEADERS,
    NBS_SOLAR_CELL_CID,
    NBS_SOLAR_CELL_INDICATOR_IDS,
    NBS_SOLAR_CELL_ROOT_ID,
    NBS_STREAM_DATA_URL,
    NbsSolarCellCollector,
    NbsSolarCellCrawler,
)
from stock_data.fetcher.industry.power.collectors.nea import SolarCollector
from stock_data.fetcher.industry.power.collectors.nea_crawler import (
    NEA_BASE_URL,
    NEA_HEADERS,
    NeaBulletinCrawler,
)
from stock_data.fetcher.industry.power.collectors.silicon import (
    SOLARBE_SILICON_SEARCH_URL,
    SOLARBE_SILICON_SOURCE,
    SiliconBranchCollector,
    SiliconBranchCrawler,
)

__all__ = [
    "INFOLINK_HEADERS",
    "INFOLINK_HISTORY_URL",
    "NBS_EXTERNAL_QUERY_URL",
    "NBS_HEADERS",
    "NBS_SOLAR_CELL_CID",
    "NBS_SOLAR_CELL_INDICATOR_IDS",
    "NBS_SOLAR_CELL_ROOT_ID",
    "NBS_STREAM_DATA_URL",
    "NEA_BASE_URL",
    "NEA_HEADERS",
    "SOLARBE_SILICON_SEARCH_URL",
    "SOLARBE_SILICON_SOURCE",
    "InfoLinkPvPriceCrawler",
    "InfoLinkSpotPriceHtmlParser",
    "NbsSolarCellCollector",
    "NbsSolarCellCrawler",
    "NeaBulletinCrawler",
    "PvPriceChainCollector",
    "SiliconBranchCollector",
    "SiliconBranchCrawler",
    "SolarCollector",
    "compute_pv_price_derivatives",
    "load_pv_price_raw_csv",
    "save_pv_price_raw_csv",
]
