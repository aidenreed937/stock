"""市场温度批量计算的按数据集共享缓存。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from stock_analytics.catalog_compat import load_dataset_compat

if TYPE_CHECKING:
    from stock_core.contracts import MarketDataCatalog


@dataclass(slots=True)
class _DatasetEntry:
    """一个数据集在批次内已加载的超集。"""

    start_date: date | None
    end_date: date | None
    columns: tuple[str, ...] | None
    frame: pl.DataFrame


@dataclass(slots=True)
class DatasetFrameCache:
    """按数据源和数据集复用一次物理读取结果。

    批量运行时将 end_date 固定为本批次最大观测日。后续请求只返回
    已加载投影的日期切片，避免每个观测日再次读取同一批 Parquet 分区。
    不同列投影分别缓存，避免后续宽投影替换窄投影并长期持有不必要的列。
    """

    end_date: date | None = None
    _entries: dict[tuple[str, str, tuple[str, ...] | None], _DatasetEntry] = field(
        default_factory=dict
    )
    _watermarks: dict[tuple[str, str, str | None, str | None], tuple[date, ...]] = field(
        default_factory=dict
    )

    @property
    def dataset_count(self) -> int:
        """返回当前缓存的数据集数量，便于运行统计和测试。"""
        return len({(source, dataset) for source, dataset, _ in self._entries})

    def load(
        self,
        catalog: MarketDataCatalog,
        dataset: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        columns: Sequence[str] | None = None,
    ) -> pl.DataFrame:
        """加载数据集并复用批次内已经读取的超集。"""
        source = str(getattr(catalog, "data_source", ""))
        requested_columns = tuple(dict.fromkeys(columns)) if columns is not None else None
        requested_end = self.end_date if end_date is None else _max_date(self.end_date, end_date)
        entry_key, entry = self._find_covering_entry(
            source,
            dataset,
            start_date=start_date,
            end_date=requested_end,
            columns=requested_columns,
        )
        if entry is None:
            projection_key = (source, dataset, requested_columns)
            entry = self._entries.get(projection_key)
            entry = self._load_superset(
                catalog,
                dataset,
                entry,
                start_date=start_date,
                end_date=requested_end,
                columns=requested_columns,
            )
            entry_key = projection_key
            self._entries[entry_key] = entry

        return self._select(entry, start_date=start_date, end_date=end_date, columns=columns)

    def latest_trade_dates(
        self,
        catalog: MarketDataCatalog,
        dataset: str,
        *,
        market: str | None = None,
        n: int = 1,
        date_column: str | None = None,
    ) -> Sequence[date]:
        """缓存批次内的水位扫描结果。

        水位查询只返回日期序列，本身没有必要在同一批次反复扫描 Parquet
        分区。请求更大的 ``n`` 时只扩展该缓存项，后续历史日期查询复用已有结果。
        """
        if n <= 0:
            return ()
        source = str(getattr(catalog, "data_source", ""))
        key = (source, dataset, market, date_column)
        cached = self._watermarks.get(key)
        if cached is None or (cached and len(cached) < n):
            latest = _catalog_latest_trade_dates(
                catalog,
                dataset,
                market=market,
                n=n,
                date_column=date_column,
            )
            cached = tuple(latest)
            self._watermarks[key] = cached
        return cached[:n]

    def _find_covering_entry(
        self,
        source: str,
        dataset: str,
        *,
        start_date: date | None,
        end_date: date | None,
        columns: tuple[str, ...] | None,
    ) -> tuple[tuple[str, str, tuple[str, ...] | None] | None, _DatasetEntry | None]:
        candidates = [
            (key, entry)
            for key, entry in self._entries.items()
            if key[0] == source
            and key[1] == dataset
            and self._covers(
                entry,
                start_date=start_date,
                end_date=end_date,
                columns=columns,
            )
        ]
        if not candidates:
            return None, None
        candidates.sort(key=lambda item: len(item[0][2] or ()))
        return candidates[0]

    @staticmethod
    def _covers(
        entry: _DatasetEntry,
        *,
        start_date: date | None,
        end_date: date | None,
        columns: tuple[str, ...] | None,
    ) -> bool:
        if columns is None:
            columns_ok = entry.columns is None
        else:
            columns_ok = entry.columns is None or set(columns).issubset(entry.columns)
        if not columns_ok:
            return False

        start_ok = entry.start_date is None or (
            start_date is not None and entry.start_date <= start_date
        )
        end_ok = entry.end_date is None or (end_date is not None and end_date <= entry.end_date)
        return start_ok and end_ok

    def _load_superset(
        self,
        catalog: MarketDataCatalog,
        dataset: str,
        entry: _DatasetEntry | None,
        *,
        start_date: date | None,
        end_date: date | None,
        columns: tuple[str, ...] | None,
    ) -> _DatasetEntry:
        if entry is None:
            load_start = start_date
            load_end = end_date
        else:
            load_start = (
                None if entry.start_date is None else _min_date(entry.start_date, start_date)
            )
            load_end = (
                None
                if entry.end_date is None or end_date is None
                else _max_date(entry.end_date, end_date)
            )
        frame = load_dataset_compat(
            catalog,
            dataset,
            start_date=load_start,
            end_date=load_end,
            columns=columns,
        )
        return _DatasetEntry(
            start_date=load_start,
            end_date=load_end,
            columns=columns,
            frame=frame,
        )

    @staticmethod
    def _select(
        entry: _DatasetEntry,
        *,
        start_date: date | None,
        end_date: date | None,
        columns: Sequence[str] | None,
    ) -> pl.DataFrame:
        frame = entry.frame
        if "trade_date" in frame.columns:
            if start_date is not None:
                frame = frame.filter(pl.col("trade_date") >= start_date)
            if end_date is not None:
                frame = frame.filter(pl.col("trade_date") <= end_date)
        if columns is not None:
            frame = frame.select([column for column in columns if column in frame.columns])
        return frame


@dataclass(slots=True)
class CachedCatalog:
    """给已有 DataCatalog 增加批次级数据帧与水位缓存。"""

    catalog: MarketDataCatalog
    cache: DatasetFrameCache

    @property
    def data_source(self) -> str:
        """返回底层数据源名称。"""
        return str(getattr(self.catalog, "data_source", ""))

    def load_dataset(
        self,
        dataset: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        market: str | None = None,
        symbols: list[str] | None = None,
        columns: Sequence[str] | None = None,
        dedup: bool = True,
    ) -> pl.DataFrame:
        """按原 DataCatalog 契约加载数据集，并复用批次缓存。"""
        if market is not None or symbols is not None or not dedup:
            return self.catalog.load_dataset(
                dataset,
                start_date=start_date,
                end_date=end_date,
                market=market,
                symbols=symbols,
                columns=columns,
                dedup=dedup,
            )
        return self.cache.load(
            self.catalog,
            dataset,
            start_date=start_date,
            end_date=end_date,
            columns=columns,
        )

    def load_bars(
        self,
        symbol: str | None = None,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        symbols: list[str] | None = None,
        columns: Sequence[str] | None = None,
        dataset: str = "stock_daily_bar",
        market: str | None = None,
        adjustment: str | None = None,
        dedup: bool = True,
        validate: bool = True,
    ) -> pl.DataFrame:
        """转发行情读取，保持目录协议完整。"""
        return self.catalog.load_bars(
            symbol,
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
            columns=columns,
            dataset=dataset,
            market=market,
            adjustment=adjustment,
            dedup=dedup,
            validate=validate,
        )

    def latest_trade_dates(
        self,
        dataset: str = "stock_daily_bar",
        market: str | None = None,
        n: int = 1,
        date_column: str | None = None,
    ) -> Sequence[date]:
        """读取批次缓存中的交易日水位。"""
        return self.cache.latest_trade_dates(
            self.catalog,
            dataset,
            market=market,
            n=n,
            date_column=date_column,
        )

    def latest_refresh_dates(
        self,
        dataset: str,
        market: str | None = None,
        n: int = 1,
        symbols: list[str] | None = None,
    ) -> Sequence[date]:
        """转发刷新水位查询。"""
        return self.catalog.latest_refresh_dates(
            dataset=dataset,
            market=market,
            n=n,
            symbols=symbols,
        )

    def __getattr__(self, name: str) -> object:
        """转发 latest_trade_dates、storage_dir 等只读属性。"""
        return getattr(self.catalog, name)


def _min_date(left: date | None, right: date | None) -> date | None:
    if left is None:
        return right
    if right is None:
        return None
    return min(left, right)


def _max_date(left: date | None, right: date | None) -> date | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def _catalog_latest_trade_dates(
    catalog: MarketDataCatalog,
    dataset: str,
    *,
    market: str | None,
    n: int,
    date_column: str | None,
) -> Sequence[date]:
    """兼容旧测试目录与完整 DataCatalog 的水位接口。"""
    try:
        return catalog.latest_trade_dates(
            dataset=dataset,
            market=market,
            n=n,
            date_column=date_column,
        )
    except TypeError:
        try:
            return catalog.latest_trade_dates(dataset=dataset, market=market, n=n)
        except TypeError:
            return catalog.latest_trade_dates(dataset=dataset, n=n)


__all__ = ["CachedCatalog", "DatasetFrameCache"]
