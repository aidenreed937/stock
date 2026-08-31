"""农业农村部 (MARA) 生猪养殖与产能数据工程包。"""

from stock_data.fetcher.industry.agriculture.collector import AgriculturePorkCollector
from stock_data.fetcher.industry.agriculture.transform import (
    AGRICULTURE_PORK_SCHEMA,
    empty_agriculture_pork,
    records_to_agriculture_pork_frame,
)

__all__ = [
    "AGRICULTURE_PORK_SCHEMA",
    "AgriculturePorkCollector",
    "empty_agriculture_pork",
    "records_to_agriculture_pork_frame",
]
