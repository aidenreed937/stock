"""全库 Curated 数据质量门禁与断言校验系统 (Quality Gate)。"""

from pathlib import Path

import polars as pl

from stock_core.constants import BAR_DATASETS
from stock_core.contracts import get_contract_for_dataset
from stock_core.exceptions import DataValidationError
from stock_core.utils.logger import logger
from stock_data.core.settings import data_settings
from stock_data.core.task_registry import resolve_task
from stock_data.governance.quality.domain_quality import (
    assert_domain_input_quality as _assert_domain_input_quality,
)
from stock_data.governance.quality.domain_quality import (
    assert_domain_mart_quality as _assert_domain_mart_quality,
)
from stock_data.governance.quality.margin_coverage import margin_coverage_issues
from stock_data.governance.quality.margin_quality import (
    margin_quality_issues,
    margin_quality_report,
)
from stock_data.storage.compat import StorageCompat
from stock_data.storage.compat_rules import _KNOWN_DATE_COLUMNS, numeric_columns_for_dataset

_BAR_REQUIRED_COLUMNS = {
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
}

_NUMERIC_DTYPES = frozenset(
    {
        pl.Int8,
        pl.Int16,
        pl.Int32,
        pl.Int64,
        pl.UInt8,
        pl.UInt16,
        pl.UInt32,
        pl.UInt64,
        pl.Float32,
        pl.Float64,
    }
)
_DATE_COLUMN_ALIASES = {"Date": "trade_date", "date": "trade_date", "asOfDate": "as_of_date"}


def _dataset_name_from_path(file: Path) -> str:
    dataset_name = file.parent.name
    if dataset_name.startswith("month="):
        return file.parent.parent.parent.name
    return dataset_name


def _is_quality_bar_file(file: Path) -> bool:
    dataset_name = _dataset_name_from_path(file)
    return dataset_name in BAR_DATASETS and not (
        dataset_name == "stock_daily_bar" and "fred" in file.parts
    )


def _data_source_from_path(file: Path, curated_dir: Path) -> str:
    """从 Curated 相对路径解析数据源，供注册表主键查询使用。"""
    try:
        relative = file.resolve().relative_to(curated_dir.resolve())
    except ValueError:
        return "unknown"
    return relative.parts[0] if relative.parts else "unknown"


def _validate_generic_bar_frame(df: pl.DataFrame, dataset_name: str, file: Path) -> bool:
    missing = sorted(_BAR_REQUIRED_COLUMNS - set(df.columns))
    if missing:
        logger.error(f"文件 [{file}] 行情数据集 [{dataset_name}] 缺少必需列: {missing}")
        return False

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
        logger.error(f"文件 [{file}] 行情 OHLC 物理异常 {len(physical_errors)} 行")
        return False
    return True


def _assert_schema_contracts(files: list[Path], curated_dir: Path) -> bool:
    """断言 parquet 文件契约、日期类型与 UTC 更新时间。"""
    for file in files:
        try:
            df = pl.read_parquet(file)
            if df.is_empty():
                continue

            dataset_name = _dataset_name_from_path(file)
            data_source = _data_source_from_path(file, curated_dir)

            if "trade_date" in df.columns and df["trade_date"].dtype != pl.Date:
                logger.error(f"文件 [{file}] trade_date 不是 pl.Date 类型")
                return False

            for column in sorted(_KNOWN_DATE_COLUMNS - {"month", "quarter"}):
                if column in df.columns and df.schema[column] != pl.Date:
                    logger.error(
                        f"文件 [{file}] 业务日期列不是 pl.Date 类型: {column} ({df.schema[column]})"
                    )
                    return False

            if "updated_at" in df.columns:
                dtype = df["updated_at"].dtype
                if not isinstance(dtype, pl.Datetime) or dtype.time_zone != "UTC":
                    logger.error(f"文件 [{file}] updated_at 不是 Datetime[us, UTC] 类型: {dtype}")
                    return False

            if "raw_row_count" in df.columns or "clean_row_count" in df.columns:
                logger.error(f"文件 [{file}] 包含废弃的明细统计列")
                return False

            if "schema_version" in df.columns:
                versions = {
                    str(value)
                    for value in df.get_column("schema_version")
                    .cast(pl.Utf8, strict=False)
                    .drop_nulls()
                    .unique()
                    .to_list()
                }
                if versions - {"v2"}:
                    logger.error(f"文件 [{file}] schema_version 不是 v2: {sorted(versions)}")
                    return False

            try:
                task = resolve_task(data_source, dataset_name)
            except Exception:
                task = None
            if task is not None:
                for declared_column in task.date_columns:
                    if declared_column in {"month", "quarter"}:
                        continue
                    column = _DATE_COLUMN_ALIASES.get(declared_column, declared_column)
                    if column not in df.columns:
                        if (
                            declared_column in task.required_columns
                            or column in task.required_columns
                        ):
                            logger.error(f"文件 [{file}] 缺少注册契约日期列: {column}")
                            return False
                        continue
                    if df.schema[column] != pl.Date:
                        logger.error(
                            f"文件 [{file}] 注册契约日期列不是 pl.Date: {column} ({df.schema[column]})"
                        )
                        return False

            numeric_columns = numeric_columns_for_dataset(dataset_name, df.columns)
            non_numeric = [
                column for column in numeric_columns if df.schema[column] not in _NUMERIC_DTYPES
            ]
            if non_numeric:
                logger.error(f"文件 [{file}] 数值契约列类型异常: {non_numeric}")
                return False

            if _is_quality_bar_file(file):
                contract = get_contract_for_dataset(dataset_name)
                if contract is not None:
                    contract.validate(df)
                elif not _validate_generic_bar_frame(df, dataset_name, file):
                    return False
        except Exception as e:
            logger.error(f"文件 [{file}] 契约校验失败: {e}")
            return False
    return True


class QualityGate:
    """全库离线 Curated 数据质量门禁。"""

    def __init__(self, curated_dir: Path | str | None = None) -> None:
        self.curated_dir = (
            Path(curated_dir) if curated_dir is not None else data_settings.curated_data_dir
        )

    def _active_parquet_files(self) -> list[Path]:
        """按有效扩展名扫描非备份 parquet 文件。"""
        if not self.curated_dir.exists():
            return []
        return [
            f
            for f in self.curated_dir.rglob("*.parquet")
            if not f.name.endswith((".bak.parquet", ".tmp.parquet"))
        ]

    assert_domain_mart_quality = _assert_domain_mart_quality
    assert_domain_input_quality = _assert_domain_input_quality

    def validate_all(self) -> dict[str, bool]:
        """运行全库质量门禁所有断言。

        Returns:
            dict[str, bool]: 每一项检查的通过状态。
        """
        files = self._active_parquet_files()
        if not files:
            logger.warning(f"门禁扫描目录 [{self.curated_dir}] 为空，跳过断言")
            return {"empty_dir": True}

        results = {
            "schema_contract": self.assert_schema_contracts(files),
            "stock_daily_bar_units": self.assert_stock_daily_bar_units(files),
            "no_mixed_adjustment": self.assert_no_mixed_adjustment(files),
            "no_duplicate_keys": self.assert_no_duplicate_keys(files),
            "margin_quality": self.assert_margin_quality(files),
            "domain_input_quality": self.assert_domain_input_quality(files),
            "domain_mart_quality": self.assert_domain_mart_quality(files),
        }

        all_passed = all(results.values())
        if not all_passed:
            failed_keys = [k for k, v in results.items() if not v]
            raise DataValidationError(f"全库质量门禁检测失败! 未通过断言项: {failed_keys}")

        logger.info("全库质量门禁 (Quality Gate) 所有断言 100% 校验通过!")
        return results

    def assert_schema_contracts(self, files: list[Path]) -> bool:
        return _assert_schema_contracts(files, self.curated_dir)

    def assert_margin_quality(self, files: list[Path]) -> bool:
        """断言两融数值关系和交易所覆盖符合质量规则。"""
        margin_files = [f for f in files if _dataset_name_from_path(f) == "margin"]
        for file in margin_files:
            try:
                df = pl.read_parquet(file)
                if df.is_empty():
                    continue
                value_issues = margin_quality_issues(df)
                coverage_issues = margin_coverage_issues(df)
                for warning in margin_quality_report(df).warnings:
                    logger.warning(f"文件 [{file}] 两融时间序列质量告警: {warning}")
                if value_issues or coverage_issues:
                    issues = [*coverage_issues, *value_issues]
                    logger.error(f"文件 [{file}] 两融质量校验失败: {'; '.join(issues)}")
                    return False
            except Exception as e:
                logger.error(f"文件 [{file}] 两融质量校验异常: {e}")
                return False
        return True

    def assert_stock_daily_bar_units(self, files: list[Path]) -> bool:
        """断言行情表成交额与成交量中位数比例接近 1 (amount / (volume * close) ~ 1)。"""
        bar_files = [f for f in files if _dataset_name_from_path(f) == "stock_daily_bar"]
        if not bar_files:
            return True

        for file in bar_files:
            try:
                df = pl.read_parquet(file)
                if df.is_empty() or len(df) < 10:
                    continue

                if not {"amount", "volume", "close"}.issubset(df.columns):
                    logger.error(f"文件 [{file}] 缺少 amount/volume/close 列")
                    return False

                # 计算比率: amount / (volume * close)
                valid = df.filter(
                    (pl.col("volume") > 0) & (pl.col("close") > 0) & (pl.col("amount") > 0)
                )
                if valid.is_empty():
                    continue

                ratio_df = valid.with_columns(
                    (pl.col("amount") / (pl.col("volume") * pl.col("close"))).alias("ratio")
                )
                if "trade_date" in ratio_df.columns:
                    # 逐日计算中位数，确保无任何单日 1000 倍比率异常
                    daily_medians = ratio_df.group_by("trade_date").agg(
                        pl.col("ratio").median().alias("day_ratio")
                    )
                    for row in daily_medians.iter_rows(named=True):
                        d_val = row["day_ratio"]
                        if d_val is not None:
                            d_ratio = float(str(d_val))
                            if not (0.7 <= d_ratio <= 1.3):
                                t_date = row["trade_date"]
                                logger.error(
                                    f"文件 [{file}] 在日期 [{t_date}] 单位断言失败! "
                                    f"比率中位数为 {d_ratio:.2f} (期望 0.7~1.3)"
                                )
                                return False
                else:
                    raw_median = ratio_df["ratio"].median()
                    if raw_median is not None:
                        median_ratio = float(str(raw_median))
                        if not (0.7 <= median_ratio <= 1.3):
                            logger.error(
                                f"文件 [{file}] 单位断言失败! "
                                f"比率中位数为 {median_ratio:.2f} (期望 0.7~1.3)"
                            )
                            return False
            except Exception as e:
                logger.error(f"文件 [{file}] 单位断言异常: {e}")
                return False
        return True

    def assert_no_mixed_adjustment(self, files: list[Path]) -> bool:
        """断言全库行情 adjustment 统一为 raw，无 normal 或混合复权。"""
        bar_files = [f for f in files if _is_quality_bar_file(f)]
        for file in bar_files:
            try:
                df = pl.read_parquet(file)
                if df.is_empty() or "adjustment" not in df.columns:
                    continue

                adjustments = set(df.get_column("adjustment").drop_nulls().unique().to_list())
                if adjustments and adjustments != {"raw"}:
                    logger.error(f"文件 [{file}] 存在非法或混合复权标记: {adjustments}")
                    return False
            except Exception as e:
                logger.error(f"检查复权标记发生异常 [{file}]: {e}")
                return False
        return True

    def assert_no_duplicate_keys(self, files: list[Path]) -> bool:
        """按数据源注册表主键断言所有 Parquet 文件没有重复记录。"""
        for file in files:
            try:
                df = pl.read_parquet(file)
                if df.is_empty():
                    continue
                dataset_name = _dataset_name_from_path(file)
                data_source = _data_source_from_path(file, self.curated_dir)
                keys = StorageCompat.resolve_dedup_keys(
                    dataset_name,
                    data_source,
                    data_source,
                    df,
                )
                if len(keys) >= 2:
                    dups = len(df) - len(df.unique(subset=keys))
                    if dups > 0:
                        logger.error(f"文件 [{file}] 包含 {dups} 条重复主键记录: {keys}")
                        return False
            except Exception as e:
                logger.error(f"检查主键重复发生异常 [{file}]: {e}")
                return False
        return True


def run_quality_gate(curated_dir: str | None = None) -> bool:
    """质量门禁一键校验入口。"""
    gate = QualityGate(curated_dir)
    try:
        gate.validate_all()
        return True
    except DataValidationError as e:
        logger.error(f"质量门禁未通过: {e}")
        return False


if __name__ == "__main__":
    import sys

    success = run_quality_gate()
    sys.exit(0 if success else 1)
