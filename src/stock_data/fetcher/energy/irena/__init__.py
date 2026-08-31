"""IRENA (国际可再生能源署) 全球新能源容量统计数据采集模块。"""

from __future__ import annotations

from stock_data.fetcher.energy.irena.client import IrenaClient
from stock_data.fetcher.energy.irena.collector import IrenaCollector
from stock_data.fetcher.energy.irena.constants import (
    IRENA_BASE_URL,
    IRENA_PXWEB_URL,
    IRENA_TECH_MAPPING,
    IRENA_TOOLS_URL,
)
from stock_data.fetcher.energy.irena.parser import (
    IrenaParser,
    parse_irena_value_and_status,
)

__all__ = [
    "IRENA_BASE_URL",
    "IRENA_PXWEB_URL",
    "IRENA_TECH_MAPPING",
    "IRENA_TOOLS_URL",
    "IrenaClient",
    "IrenaCollector",
    "IrenaParser",
    "parse_irena_value_and_status",
]
