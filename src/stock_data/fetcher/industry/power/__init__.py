"""光伏与新能源装机容量 (NEA) 数据工程子包。"""

from stock_data.fetcher.industry.power.collector import SolarCollector
from stock_data.fetcher.industry.power.transform import (
    SOLAR_CAPACITY_SCHEMA,
    empty_solar_capacity,
    records_to_solar_frame,
)

__all__ = [
    "SOLAR_CAPACITY_SCHEMA",
    "SolarCollector",
    "empty_solar_capacity",
    "records_to_solar_frame",
]
