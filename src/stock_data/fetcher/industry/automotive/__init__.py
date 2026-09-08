"""新能源汽车月度产销与渗透率 (CPCA/CAAM/CABIA) 数据工程子包。"""

from stock_data.fetcher.industry.automotive.collectors import (
    CPCA_DATA_API_URL,
    CPCA_HEADERS,
    CPCA_OFFICIAL_BASE_URL,
    CPCA_REPORT_INDEX_URL,
    CabiaCollector,
    CabiaCrawler,
    CpcaBulletinCrawler,
    CpcaCollector,
    CpcaOnlineClient,
    NevCollector,
)
from stock_data.fetcher.industry.automotive.models import NevMonthlyRecord
from stock_data.fetcher.industry.automotive.parsers import (
    parse_cabia_battery_article,
    parse_cpca_bulletin_article,
)
from stock_data.fetcher.industry.automotive.paths import (
    AUTOMOTIVE_CABIA_RAW_SUBDIR,
    AUTOMOTIVE_CPCA_RAW_SUBDIR,
    AUTOMOTIVE_RAW_SUBDIR,
    AutomotiveRawPaths,
)
from stock_data.fetcher.industry.automotive.schemas import NEV_MONTHLY_RAW_SCHEMA
from stock_data.fetcher.industry.automotive.transforms import (
    NEV_MONTHLY_SCHEMA,
    empty_nev_monthly,
    empty_raw_nev_monthly,
    records_to_nev_frame,
    records_to_raw_nev_frame,
)

__all__ = [
    "AUTOMOTIVE_CABIA_RAW_SUBDIR",
    "AUTOMOTIVE_CPCA_RAW_SUBDIR",
    "AUTOMOTIVE_RAW_SUBDIR",
    "CPCA_DATA_API_URL",
    "CPCA_HEADERS",
    "CPCA_OFFICIAL_BASE_URL",
    "CPCA_REPORT_INDEX_URL",
    "NEV_MONTHLY_RAW_SCHEMA",
    "NEV_MONTHLY_SCHEMA",
    "AutomotiveRawPaths",
    "CabiaCollector",
    "CabiaCrawler",
    "CpcaBulletinCrawler",
    "CpcaCollector",
    "CpcaOnlineClient",
    "NevCollector",
    "NevMonthlyRecord",
    "empty_nev_monthly",
    "empty_raw_nev_monthly",
    "parse_cabia_battery_article",
    "parse_cpca_bulletin_article",
    "records_to_nev_frame",
    "records_to_raw_nev_frame",
]
