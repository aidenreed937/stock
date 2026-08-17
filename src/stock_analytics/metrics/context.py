"""市场指标运行上下文。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from stock_core.contracts import MarketDataCatalog

if TYPE_CHECKING:
    from collections.abc import MutableMapping
    from datetime import date

    import polars as pl


def _create_default_catalog() -> MarketDataCatalog:
    from stock_data.catalog import DataCatalog

    return DataCatalog()


@dataclass(slots=True)
class MetricContext:
    """指标计算共享上下文。"""

    catalog: MarketDataCatalog = field(default_factory=_create_default_catalog)
    target_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    cache: MutableMapping[str, pl.DataFrame] = field(default_factory=dict)

    def resolve_end_date(self) -> date | None:
        """返回本次计算的结束日期。"""
        return self.end_date or self.target_date

    def cache_key(self, *parts: object) -> str:
        """构造上下文内缓存键。"""
        return ":".join(str(part) for part in parts)
