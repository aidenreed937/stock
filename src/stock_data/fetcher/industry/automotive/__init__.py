"""新能源汽车月度产销与渗透率 (CPCA/CAAM/CABIA) 数据工程子包。"""

from stock_data.fetcher.industry.automotive.collector import NevCollector
from stock_data.fetcher.industry.automotive.crawler import (
    CabiaCrawler,
    CpcaBulletinCrawler,
    parse_cabia_battery_article,
    parse_cpca_bulletin_article,
)
from stock_data.fetcher.industry.automotive.transform import (
    NEV_MONTHLY_SCHEMA,
    empty_nev_monthly,
    records_to_nev_frame,
)

__all__ = [
    "NEV_MONTHLY_SCHEMA",
    "CabiaCrawler",
    "CpcaBulletinCrawler",
    "NevCollector",
    "empty_nev_monthly",
    "parse_cabia_battery_article",
    "parse_cpca_bulletin_article",
    "records_to_nev_frame",
]
