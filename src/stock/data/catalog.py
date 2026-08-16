"""统一读取本地已落盘 Curated Parquet 数据的数据目录服务 (DataCatalog)。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import polars as pl

from stock.config.settings import settings
from stock.constants import BAR_DATASETS
from stock.data.catalog_ops import (
    normalize_identity_columns as _normalize_identity_columns,
)
from stock.data.catalog_ops import (
    path_intersects_range as _path_intersects_range,
)
from stock.data.catalog_ops import (
    scan_latest_trade_dates as _scan_latest_trade_dates,
)
from stock.data.catalog_ops import (
    validate_schema_version as _validate_schema_version,
)
from stock.data.quality.margin_coverage import filter_complete_margin_dates
from stock.data.storage.compat import StorageCompat
from stock.exceptions import DataValidationError
from stock.utils.logger import logger

_BAR_DATASETS = BAR_DATASETS
_ARTIFACT_SUFFIXES = (".bak.parquet", ".tmp.parquet", ".migration.tmp.parquet")


@dataclass(frozen=True)
class CatalogDataset:
    """数据目录中一个数据集的定位信息。"""

    data_source: str
    dataset: str
    files: tuple[Path, ...] = field(default_factory=tuple)

    @property
    def total_rows(self) -> int | None:
        if not self.files:
            return None
        try:
            return int(
                sum(pl.scan_parquet(path).select(pl.len()).collect().item() for path in self.files)
            )
        except Exception:
            return None


class DataCatalog:
    """按数据源隔离的本地落盘数据统一读取入口。"""

    def __init__(
        self,
        data_source: str | None = None,
        storage_dir: Path | str | None = None,
    ) -> None:
        self.data_source = data_source or settings.data_source_mode
        self.storage_dir = (
            Path(storage_dir) if storage_dir is not None else settings.curated_data_dir
        )
        if not self.storage_dir.exists():
            raise FileNotFoundError(f"Curated 数据目录不存在: {self.storage_dir}")

    def _parquet_files(self, dataset: str | None = None, market: str | None = None) -> list[Path]:
        return _list_parquet_files(
            self.storage_dir / self.data_source, dataset=dataset, market=market
        )

    def available_datasets(self, market: str | None = None) -> list[CatalogDataset]:
        """列出当前数据源下所有可用数据集。"""
        seen: dict[str, list[Path]] = {}
        for path in self._parquet_files(market=market):
            seen.setdefault(_dataset_name(path), []).append(path)
        return [
            CatalogDataset(data_source=self.data_source, dataset=name, files=tuple(sorted(paths)))
            for name, paths in sorted(seen.items())
        ]

    def load_dataset(
        self,
        dataset: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        market: str | None = None,
        symbols: list[str] | None = None,
        dedup: bool = True,
    ) -> pl.DataFrame:
        """读取标准数据集（非行情类也可用），可按标的与日期范围过滤。"""
        resolved = _resolve_dataset_alias(self.data_source, dataset)
        files = _list_parquet_files(
            self.storage_dir / self.data_source, dataset=resolved, market=market
        )
        df = _read_dataset_files(files, resolved, self.data_source, start_date, end_date, symbols)
        if dedup and (
            k := StorageCompat.resolve_dedup_keys(resolved, self.data_source, self.data_source, df)
        ):
            df = df.unique(subset=k, keep="last")
        return df

    def load_bars(
        self,
        symbol: str | None = None,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        symbols: list[str] | None = None,
        dataset: str = "stock_daily_bar",
        market: str | None = None,
        adjustment: str | None = None,
        dedup: bool = True,
        validate: bool = True,
    ) -> pl.DataFrame:
        """读取行情（K 线）数据并进行时序排序与有效性校验。"""
        resolved = _resolve_dataset_alias(self.data_source, dataset)
        if symbol is not None:
            symbols = [symbol]
        files = _list_parquet_files(
            self.storage_dir / self.data_source, dataset=resolved, market=market
        )
        df = _read_dataset_files(files, resolved, self.data_source, start_date, end_date, symbols)
        if df.is_empty():
            logger.warning(f"DataCatalog 未找到 [{resolved}] 行情数据 (数据源: {self.data_source})")
            return df

        if adjustment is not None and "adjustment" in df.columns:
            df = df.filter(pl.col("adjustment") == adjustment)

        if dedup and "symbol" in df.columns and "trade_date" in df.columns:
            dedup_cols = [c for c in ("market", "symbol", "trade_date") if c in df.columns]
            if dedup_cols:
                df = df.unique(subset=dedup_cols, keep="last")
        if "trade_date" in df.columns:
            df = df.sort(["trade_date", "symbol"])

        if validate:
            _validate_bars(df, resolved)
        return df

    def latest_trade_dates(
        self,
        dataset: str = "stock_daily_bar",
        market: str | None = None,
        n: int = 1,
    ) -> list[date]:
        """返回数据集中最近 N 个交易日（降序）。"""
        resolved = _resolve_dataset_alias(self.data_source, dataset)
        files = _list_parquet_files(
            self.storage_dir / self.data_source, dataset=resolved, market=market
        )
        return _scan_latest_trade_dates(files, n)

    def get_latest_trade_date(
        self,
        dataset: str,
        market: str | None = None,
        data_source: str | None = None,
    ) -> date | None:
        """返回指定数据集的全表最新落盘交易日（标量 date）。"""
        ds = data_source or self.data_source
        cat = (
            self
            if ds == self.data_source
            else DataCatalog(data_source=ds, storage_dir=self.storage_dir)
        )
        dates = cat.latest_trade_dates(dataset=dataset, market=market, n=1)
        return dates[0] if dates else None

    def list_datasets(self, data_source: str | None = None, market: str | None = None) -> list[str]:
        """返回指定数据源（或当前数据源，传入 'all' 时扫描全库）下已落盘的数据集名称列表。"""
        ds = data_source or self.data_source
        if ds == "all":
            all_names: set[str] = set()
            for source_dir in self.storage_dir.iterdir():
                if source_dir.is_dir() and not source_dir.name.startswith("."):
                    cat = DataCatalog(data_source=source_dir.name, storage_dir=self.storage_dir)
                    all_names.update(d.dataset for d in cat.available_datasets(market=market))
            return sorted(all_names)
        cat = (
            self
            if ds == self.data_source
            else DataCatalog(data_source=ds, storage_dir=self.storage_dir)
        )
        return [d.dataset for d in cat.available_datasets(market=market)]

    def summary(self, data_source: str | None = None, market: str | None = None) -> pl.DataFrame:
        """一键生成全库或指定数据源的落盘数据资产全景状态表格。"""
        return _build_catalog_summary(self, data_source, market)

    def describe(self, market: str | None = None) -> pl.DataFrame:
        """生成数据目录摘要（数据集、文件数、总行数）。"""
        rows = [
            {
                "data_source": self.data_source,
                "dataset": entry.dataset,
                "files": len(entry.files),
                "rows": entry.total_rows,
            }
            for entry in self.available_datasets(market=market)
        ]
        return (
            pl.DataFrame(rows)
            if rows
            else pl.DataFrame(
                schema={
                    "data_source": pl.Utf8,
                    "dataset": pl.Utf8,
                    "files": pl.Int64,
                    "rows": pl.Int64,
                }
            )
        )


def _list_parquet_files(
    base_dir: Path, dataset: str | None = None, market: str | None = None
) -> list[Path]:
    if not base_dir.exists():
        return []
    glob_pattern = "**/*.parquet" if dataset is None else f"**/{dataset}/**/*.parquet"
    files: list[Path] = []
    for path in base_dir.glob(glob_pattern):
        if path.name.endswith(_ARTIFACT_SUFFIXES):
            continue
        if dataset is not None and _dataset_name(path) != dataset:
            continue
        if market is not None and f"market={market.upper()}" not in path.parts:
            continue
        files.append(path)
    return sorted(files)


def _dataset_name(path: Path) -> str:
    parts = path.parts
    for i in range(len(parts) - 1, -1, -1):
        if parts[i].startswith("month=") and i >= 2 and parts[i - 1].startswith("year="):
            return parts[i - 2]
        if parts[i].startswith("year=") and i >= 1:
            return parts[i - 1]
    if not path.parent.name.startswith("market=") and not path.parent.name.startswith("year="):
        return path.parent.name
    return path.stem.split(".", 1)[0]


def _read_dataset_files(
    files: list[Path],
    dataset: str,
    data_source: str,
    start_date: date | None,
    end_date: date | None,
    symbols: list[str] | None,
) -> pl.DataFrame:
    if not files:
        logger.warning(
            f"DataCatalog 未找到数据集 [{dataset}] 的 Parquet 文件 (数据源: {data_source})"
        )
        return pl.DataFrame()

    candidate_files = files
    if start_date is not None or end_date is not None:
        start_ym = (start_date.year, start_date.month) if start_date else (date.min.year, 1)
        end_ym = (end_date.year, end_date.month) if end_date else (date.max.year, 12)
        candidate_files = [path for path in files if _path_intersects_range(path, start_ym, end_ym)]
        if not candidate_files:
            return pl.DataFrame()

    frames: list[pl.DataFrame] = []
    for path in candidate_files:
        try:
            frame = pl.read_parquet(path)
        except Exception as e:
            logger.error(f"DataCatalog 读取文件失败 [{path}]: {e}")
            continue
        frame = StorageCompat.safe_normalize_frame(frame)
        _validate_schema_version(frame, path)
        frames.append(frame)
    if not frames:
        return pl.DataFrame()
    try:
        df = pl.concat(frames, how="diagonal_relaxed")
    except Exception as e:
        logger.error(f"DataCatalog 合并数据集 [{dataset}] 失败: {e}")
        return pl.DataFrame()

    if df.is_empty():
        return df

    df = _normalize_identity_columns(df)
    if "trade_date" in df.columns:
        df = StorageCompat.safe_cast_date_col(df, "trade_date")
        if start_date is not None:
            df = df.filter(pl.col("trade_date") >= start_date)
        if end_date is not None:
            df = df.filter(pl.col("trade_date") <= end_date)

    if symbols:
        symbol_col = "symbol" if "symbol" in df.columns else None
        if symbol_col is not None:
            df = df.filter(pl.col(symbol_col).is_in(symbols))

    if data_source == "tushare" and dataset == "margin":
        df = filter_complete_margin_dates(df, start_date=start_date, end_date=end_date)

    return df


def _build_catalog_summary(
    catalog: DataCatalog, data_source: str | None, market: str | None
) -> pl.DataFrame:
    sources = (
        [d.name for d in catalog.storage_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
        if (data_source == "all" or data_source is None)
        else [data_source]
    )
    rows: list[dict[str, object]] = []
    for src in sorted(sources):
        try:
            cat = (
                catalog
                if src == catalog.data_source
                else DataCatalog(data_source=src, storage_dir=catalog.storage_dir)
            )
            for entry in cat.available_datasets(market=market):
                w_date = cat.get_latest_trade_date(entry.dataset, market=market)
                rows.append(
                    {
                        "data_source": src,
                        "dataset": entry.dataset,
                        "files": len(entry.files),
                        "total_rows": entry.total_rows,
                        "latest_date": str(w_date) if w_date else "N/A",
                    }
                )
        except Exception:
            continue
    if rows:
        return pl.DataFrame(rows).sort(["data_source", "dataset"])
    return pl.DataFrame(
        schema={
            "data_source": pl.Utf8,
            "dataset": pl.Utf8,
            "files": pl.Int64,
            "total_rows": pl.Int64,
            "latest_date": pl.Utf8,
        }
    )


def _resolve_dataset_alias(data_source: str, name: str) -> str:
    try:
        from stock.data.task_registry import resolve_task

        task = resolve_task(data_source, name)
        return task.dataset
    except Exception:
        return name


def _validate_bars(df: pl.DataFrame, dataset: str) -> None:
    if dataset not in _BAR_DATASETS or df.is_empty():
        return
    required = {"open", "high", "low", "close"}
    if not required.issubset(df.columns):
        return
    if any(df[column].null_count() > 0 for column in required):
        raise DataValidationError(f"数据集 [{dataset}] OHLC 包含空值")
    physical_errors = df.filter(
        (pl.col("open") <= 0)
        | (pl.col("high") <= 0)
        | (pl.col("low") <= 0)
        | (pl.col("close") <= 0)
        | (pl.col("high") < pl.col("low"))
        | (pl.col("high") < pl.col("open"))
        | (pl.col("high") < pl.col("close"))
        | (pl.col("low") > pl.col("open"))
        | (pl.col("low") > pl.col("close"))
    )
    if not physical_errors.is_empty():
        raise DataValidationError(
            f"数据集 [{dataset}] 存在 {len(physical_errors)} 条 OHLC 物理异常"
        )
