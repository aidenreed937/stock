"""农业产业源端解析器。"""

from stock_data.fetcher.industry.agriculture.parsers.mara import (
    MaraPorkHtmlParser,
    parse_mara_monthly_table,
    parse_mara_pork_bulletin_text,
)
from stock_data.fetcher.industry.agriculture.parsers.raw_csv import (
    PORK_CSV_FIELDNAMES,
    load_pork_raw_csv,
    save_pork_raw_csv,
)

__all__ = [
    "PORK_CSV_FIELDNAMES",
    "MaraPorkHtmlParser",
    "load_pork_raw_csv",
    "parse_mara_monthly_table",
    "parse_mara_pork_bulletin_text",
    "save_pork_raw_csv",
]
