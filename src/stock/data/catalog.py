"""统一读取本地已落盘 Curated Parquet 数据的数据目录服务 (DataCatalog)。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import polars as pl

from stock.config.settings import settings
from stock.constants import BAR_DATASETS
from stock.core.contracts import DAILY_BAR_CONTRACT
from stock.data.storage.compat import StorageCompat
from stock.exceptions import DataValidationError
from stock.utils.logger import logger

#: 行情类数据集：读取时统一按 (market, symbol, trade_date) 去重并保留最新复权。
_BAR_DATASETS = BAR_DATASETS
#: 历史归档文件备份/临时文件一律跳过。
_ARTIFACT_SUFFIXES = (".bak.parquet", ".tmp.parquet", ".migration.tmp.parquet")
#: 身份列别名归一：源端 ts_code/stockCode/code 统一映射为 symbol。
_IDENTITY_ALIASES = ("ts_code", "stockCode", "code")
#: 交易日列别名归一：date 统一映射为 trade_date。
_DATE_ALIASES = ("date",)


def _dataset_name(path: Path) -> str:
    """从 Hive 分区路径或文件目录解析数据集名称。"""
    parts = path.parts
    for i in range(len(parts) - 1, -1, -1):
        if parts[i].startswith("month=") and i >= 2 and parts[i - 1].startswith("year="):
            return parts[i - 2]
        if parts[i].startswith("year=") and i >= 1:
            return parts[i - 1]
    if not path.parent.name.startswith("market=") and not path.parent.name.startswith("year="):
        return path.parent.name
    return path.stem.split(".", 1)[0]


@dataclass(frozen=True)
class CatalogDataset:
    """数据目录中一个数据集的定位信息。"""

    data_source: str
    dataset: str
    files: tuple[Path, ...] = field(default_factory=tuple)

    @property
    def total_rows(self) -> int | None:
        """尽力读取元数据返回总行数；失败时为 None（不加载全量数据）。"""
        if not self.files:
            return None
        try:
            return int(sum(pl.scan_parquet(f).count().collect().item() for f in self.files))
        except Exception:
            return None


class DataCatalog:
    """按数据源隔离的本地落盘数据统一读取入口。

    Args:
        data_source: 数据源标识，例如 ``tushare`` / ``yfinance`` / ``lixinger`` / ``fred``。
            默认取 ``settings.data_source_mode``。
        storage_dir: Curated 根目录，默认 ``settings.curated_data_dir``。
    """

    def __init__(
        self,
        data_source: str | None = None,
        storage_dir: Path | str | None = None,
    ) -> None:
        self.data_source = data_source or settings.data_source_mode
        self.storage_dir = Path(storage_dir) if storage_dir is not None else settings.curated_data_dir
        if not self.storage_dir.exists():
            raise FileNotFoundError(f"Curated 数据目录不存在: {self.storage_dir}")

    def _source_root(self) -> Path:
        """返回当前数据源专属的 Curated 根目录。"""
        return self.storage_dir / self.data_source

    def _parquet_files(self, dataset: str | None = None, market: str | None = None) -> list[Path]:
        """递归列出当前数据源下有效 Parquet，可按数据集目录名与市场精确过滤。"""
        base = self._source_root()
        if not base.exists():
            return []
        glob_pattern = "**/*.parquet" if dataset is None else f"**/{dataset}/**/*.parquet"
        files: list[Path] = []
        for path in base.glob(glob_pattern):
            if path.name.endswith(_ARTIFACT_SUFFIXES):
                continue
            if dataset is not None and _dataset_name(path) != dataset:
                continue
            if market is not None and f"market={market.upper()}" not in path.parts:
                continue
            files.append(path)
        return sorted(files)

    def available_datasets(self, market: str | None = None) -> list[CatalogDataset]:
        """列出当前数据源下所有可用数据集。"""
        seen: dict[str, list[Path]] = {}
        for path in self._parquet_files(market=market):
            seen.setdefault(_dataset_name(path), []).append(path)
        return [
            CatalogDataset(data_source=self.data_source, dataset=name, files=tuple(sorted(paths)))
            for name, paths in sorted(seen.items())
        ]

    def _read_dataset_files(
        self,
        dataset: str,
        *,
        start_date: date | None,
        end_date: date | None,
        market: str | None,
        symbols: list[str] | None,
    ) -> pl.DataFrame:
        """按分区裁剪读取数据集，并在读取后进行规范列归一。"""
        files = self._parquet_files(dataset=dataset, market=market)
        if not files:
            logger.warning(
                f"DataCatalog 未找到数据集 [{dataset}] 的 Parquet 文件 (数据源: {self.data_source})"
            )
            return pl.DataFrame()

        # Hive 年月分区下推：只读取与请求日期范围相交的月份目录。
        candidate_files = files
        if start_date is not None or end_date is not None:
            start_ym = (start_date.year, start_date.month) if start_date else (date.min.year, 1)
            end_ym = (end_date.year, end_date.month) if end_date else (date.max.year, 12)
            candidate_files = [
                path for path in files if _path_intersects_range(path, start_ym, end_ym)
            ]
            if not candidate_files:
                return pl.DataFrame()

        # 逐文件读取并统一 updated_at 时区，规避跨文件 SchemaError。
        frames: list[pl.DataFrame] = []
        for path in candidate_files:
            try:
                frame = pl.read_parquet(path)
            except Exception as e:
                logger.error(f"DataCatalog 读取文件失败 [{path}]: {e}")
                continue
            if "updated_at" in frame.columns:
                frame = frame.with_columns(
                    pl.col("updated_at").cast(pl.Datetime(time_unit="us", time_zone="UTC"), strict=False)
                )
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
            df = _coerce_trade_date(df)
            if start_date is not None:
                df = df.filter(pl.col("trade_date") >= start_date)
            if end_date is not None:
                df = df.filter(pl.col("trade_date") <= end_date)

        if symbols:
            symbol_col = "symbol" if "symbol" in df.columns else None
            if symbol_col is None:
                logger.warning(f"数据集 [{dataset}] 缺少 symbol 列，无法按标的过滤")
            else:
                df = df.filter(pl.col(symbol_col).is_in(symbols))

        return df

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
        df = self._read_dataset_files(
            dataset=dataset,
            start_date=start_date,
            end_date=end_date,
            market=market,
            symbols=symbols,
        )
        if df.is_empty():
            return df
        if dedup and "market" in df.columns and "symbol" in df.columns and "trade_date" in df.columns:
            df = df.unique(subset=["market", "symbol", "trade_date"], keep="last")
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
        """读取行情（K 线）数据。

        Args:
            symbol: 单个标的代码（与 ``symbols`` 二选一，优先单个）。
            start_date / end_date: 日期范围（含端点）。
            symbols: 多个标的代码列表。
            dataset: 行情数据集名，默认 ``stock_daily_bar``。
            market: 市场标识（如 ``CN``），缺省自动从已落盘数据推断。
            adjustment: 复权类型过滤（``raw`` / ``normal`` / ``hfq`` 等），
                缺省保留全部复权版本；若使用 ``dedup=True`` 则会按市场、标的、
                交易日去重并保留最新版本。
            validate: 是否对行情数据执行物理约束校验（默认 True）。
        """
        if symbol is not None:
            symbols = [symbol]
        df = self._read_dataset_files(
            dataset=dataset,
            start_date=start_date,
            end_date=end_date,
            market=market,
            symbols=symbols,
        )
        if df.is_empty():
            logger.warning(f"DataCatalog 未找到 [{dataset}] 行情数据 (数据源: {self.data_source})")
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
            _validate_bars(df, dataset)
        return df

    def latest_trade_dates(
        self,
        dataset: str = "stock_daily_bar",
        market: str | None = None,
        n: int = 1,
    ) -> list[date]:
        """返回数据集中最近 N 个交易日（降序），优先逆序扫描最新分区文件以保证秒级返回。"""
        return _scan_latest_trade_dates(self._parquet_files(dataset=dataset, market=market), n)

    def market_of_dataset(self, dataset: str, market: str | None = None) -> str | None:
        """推断数据集的实际市场标识（基于目录路径）。"""
        files = self._parquet_files(dataset=dataset, market=market)
        for path in files:
            for part in path.parts:
                if part.startswith("market="):
                    return part.removeprefix("market=")
        return None

    def describe(self, market: str | None = None) -> pl.DataFrame:
        """生成数据目录摘要（数据集、文件数、总行数），用于人工巡检与对账。"""
        rows: list[dict[str, object]] = []
        for entry in self.available_datasets(market=market):
            rows.append(
                {
                    "data_source": self.data_source,
                    "dataset": entry.dataset,
                    "files": len(entry.files),
                    "rows": entry.total_rows,
                }
            )
        if rows:
            return pl.DataFrame(rows)
        return pl.DataFrame(
            schema={"data_source": pl.Utf8, "dataset": pl.Utf8, "files": pl.Int64, "rows": pl.Int64}
        )


def _path_intersects_range(path: Path, start_ym: tuple[int, int], end_ym: tuple[int, int]) -> bool:
    """判断读写路径的 year=/month= 分区是否与请求的 (年, 月) 范围相交。

    非分区文件（如 lixinger/fred 免分区数据集）一律视为命中。
    """
    year_part = month_part = None
    for part in path.parts:
        if part.startswith("year="):
            try:
                year_part = int(part.removeprefix("year="))
            except ValueError:
                return True
        elif part.startswith("month="):
            try:
                month_part = int(part.removeprefix("month="))
            except ValueError:
                return True
    if year_part is None:
        return True  # 无分区信息，无法裁剪，保守读取。
    if month_part is None:
        return start_ym[0] <= year_part <= end_ym[0]
    return (start_ym[0], start_ym[1]) <= (year_part, month_part) <= (end_ym[0], end_ym[1])


def _normalize_identity_columns(df: pl.DataFrame) -> pl.DataFrame:
    """将源端标的/日期别名归一为 Curated 标准列。"""
    columns = set(df.columns)
    result = df
    for alias in _IDENTITY_ALIASES:
        if alias not in columns:
            continue
        if "symbol" not in columns:
            result = result.rename({alias: "symbol"})
        else:
            result = result.with_columns(
                pl.coalesce(
                    [
                        pl.col(alias).cast(pl.Utf8, strict=False),
                        pl.col("symbol").cast(pl.Utf8, strict=False),
                    ]
                ).alias("symbol")
            ).drop(alias)
        columns = set(result.columns)
    for alias in _DATE_ALIASES:
        if alias not in columns:
            continue
        if "trade_date" not in columns:
            result = result.rename({alias: "trade_date"})
        else:
            result = result.with_columns(
                pl.coalesce(
                    [
                        pl.col("trade_date").cast(pl.Utf8, strict=False),
                        pl.col("date").cast(pl.Utf8, strict=False),
                    ]
                ).alias("trade_date")
            ).drop(alias)
        columns = set(result.columns)
    return result


def _coerce_trade_date(df: pl.DataFrame) -> pl.DataFrame:
    """将 trade_date 统一为 ``date`` 类型，兼容日期字符串与时间戳。"""
    return StorageCompat.safe_cast_date_col(df, "trade_date")


def _scan_latest_trade_dates(files: list[Path], n: int = 1) -> list[date]:
    """逆序扫描 Parquet 分区提取最近 N 个交易日。"""
    if not files:
        return []
    found: set[date] = set()
    for path in reversed(files):
        try:
            df_lazy = pl.scan_parquet(path)
            cols = df_lazy.collect_schema().names()
            date_col = next((c for c in ("trade_date", "date", "Date") if c in cols), None)
            if not date_col:
                continue
            distinct_df = StorageCompat.safe_cast_date_col(
                df_lazy.select(pl.col(date_col).drop_nulls().unique()).collect(), date_col
            )
            for d in distinct_df[date_col].to_list():
                if isinstance(d, date):
                    found.add(d)
            if len(found) >= max(n * 3, 10):
                break
        except Exception:
            continue
    return sorted(found, reverse=True)[:n]


def _validate_bars(df: pl.DataFrame, dataset: str) -> None:
    """对行情数据执行物理约束校验（OHLC 非空且有序）。"""
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
        raise DataValidationError(f"数据集 [{dataset}] 存在 {len(physical_errors)} 条 OHLC 物理异常")
