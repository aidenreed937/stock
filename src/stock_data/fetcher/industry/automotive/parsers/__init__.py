"""汽车产业源端解析器。"""

from stock_data.fetcher.industry.automotive.parsers.cabia import parse_cabia_battery_article
from stock_data.fetcher.industry.automotive.parsers.cpca import (
    parse_cpca_bulletin_article,
    parse_cpca_snapshot,
    parse_matrix_file,
)

__all__ = [
    "parse_cabia_battery_article",
    "parse_cpca_bulletin_article",
    "parse_cpca_snapshot",
    "parse_matrix_file",
]
