"""新能源汽车分源采集器。"""

from stock_data.fetcher.industry.automotive.collectors.cabia import (
    CabiaCollector,
    CabiaCrawler,
)
from stock_data.fetcher.industry.automotive.collectors.cpca import (
    CPCA_DATA_API_URL,
    CPCA_HEADERS,
    CPCA_OFFICIAL_BASE_URL,
    CPCA_REPORT_INDEX_URL,
    CpcaBulletinCrawler,
    CpcaCollector,
    CpcaOnlineClient,
)
from stock_data.fetcher.industry.automotive.collectors.nev import NevCollector

__all__ = [
    "CPCA_DATA_API_URL",
    "CPCA_HEADERS",
    "CPCA_OFFICIAL_BASE_URL",
    "CPCA_REPORT_INDEX_URL",
    "CabiaCollector",
    "CabiaCrawler",
    "CpcaBulletinCrawler",
    "CpcaCollector",
    "CpcaOnlineClient",
    "NevCollector",
]
