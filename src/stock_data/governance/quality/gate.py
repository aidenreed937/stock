"""全库 Curated 数据质量门禁与断言校验系统 (Quality Gate)。"""

from pathlib import Path

import polars as pl

from stock_core.constants import BAR_DATASETS
from stock_core.contracts import get_contract_for_dataset
from stock_core.exceptions import DataValidationError
from stock_core.utils.logger import logger
from stock_data.core.settings import data_settings
from stock_data.core.task_resolution import resolve_task
from stock_data.governance.quality.domain_quality import (
    assert_domain_input_quality as _assert_domain_input_quality,
)
from stock_data.governance.quality.domain_quality import (
    assert_domain_mart_quality as _assert_domain_mart_quality,
)
from stock_data.governance.quality.domain_quality import (
    assert_industry_growth_rate_sanity as _assert_industry_growth_rate_sanity,
)
from stock_data.governance.quality.margin_coverage import margin_coverage_issues
from stock_data.governance.quality.margin_quality import (
    margin_quality_issues,
    margin_quality_report,
)
from stock_data.storage.compat import StorageCompat
from stock_data.storage.compat_rules import _KNOWN_DATE_COLUMNS, numeric_columns_for_dataset

#: 半导体 IDM 库存季度级聚合（等权/加权 DOI 与相态）所需的最少主体数。
#:
#: 权威定义在 `stock_data.fetcher.industry.semiconductor.transforms.inventory`
#: 的 ``MIN_INVENTORY_CONSTITUENTS``（= 7 家面板的半数）。此处就地镜像而不 import，
#: 是为避免 `pipeline.normalizer → governance.quality → fetcher` 的循环导入；
#: regime 阈值（150/130/105）在本模块同样采用就地硬编码，口径一致。
#: 两处取值必须同步修改。
_MIN_INVENTORY_CONSTITUENTS = 4

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
    if "industry" in file.parts and file.suffix == ".parquet":
        return file.stem
    dataset_name = file.parent.name
    if dataset_name.startswith("month="):
        return file.parent.parent.parent.name
    return dataset_name


def _is_quality_bar_file(file: Path) -> bool:
    dataset_name = _dataset_name_from_path(file)
    return dataset_name in BAR_DATASETS and not (
        dataset_name == "stock_daily_bar" and "fred" in file.parts
    )


def _is_foundry_file(file: Path) -> bool:
    """识别产业端点直接落在 industry 目录下的 Foundry 黄金表。"""
    return file.name == "foundry_capacity_utilization.parquet"


def _is_inventory_file(file: Path) -> bool:
    """识别产业端点直接落在 industry 目录下的 IDM 库存黄金表。"""
    return file.name == "semiconductor_inventory_days.parquet"


def _is_tsmc_adv_pkg_revenue_file(file: Path) -> bool:
    """识别台积电官方先进封装财务拆解黄金表。"""
    return file.name == "tsmc_advanced_packaging_revenue.parquet"


def _is_cowos_capacity_estimates_file(file: Path) -> bool:
    """识别智库 CoWoS 产能预测黄金表。"""
    return file.name == "tsmc_cowos_capacity_estimates.parquet"


def _is_semiconductor_equipment_gm_file(file: Path) -> bool:
    """识别半导体设备商毛利率手工黄金表。"""
    return file.name in {
        "semiconductor_equipment_gm.parquet",
        "semiconductor_equipment_gm_multi.parquet",
        "tel_gm_quarterly.parquet",
    }


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
    assert_industry_growth_rate_sanity = _assert_industry_growth_rate_sanity

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
            "foundry_quality": self.assert_foundry_quality(files),
            "inventory_quality": self.assert_inventory_quality(files),
            "margin_quality": self.assert_margin_quality(files),
            "domain_input_quality": self.assert_domain_input_quality(files),
            "domain_mart_quality": self.assert_domain_mart_quality(files),
            "industry_growth_rate_sanity": self.assert_industry_growth_rate_sanity(files),
            "semiconductor_equipment_gm_quality": self.assert_semiconductor_equipment_gm_quality(
                files
            ),
            "semiconductor_ratio_scale": self.assert_semiconductor_ratio_scale(files),
            "tsmc_adv_pkg_revenue_quality": self.assert_tsmc_adv_pkg_revenue_quality(files),
            "cowos_capacity_estimates_quality": self.assert_cowos_capacity_estimates_quality(files),
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

    def assert_semiconductor_equipment_gm_quality(self, files: list[Path]) -> bool:
        """断言设备商毛利率手工黄金表的 schema、主键、日期和比例尺度。"""
        profiles = {
            "semiconductor_equipment_gm.parquet": {
                "keys": ("report_quarter",),
                "required": {
                    "report_quarter",
                    "trade_date",
                    "gross_margin_pct",
                    "release_date",
                    "source",
                    "data_status",
                },
            },
            "semiconductor_equipment_gm_multi.parquet": {
                "keys": ("company", "report_quarter"),
                "required": {
                    "company",
                    "report_quarter",
                    "gross_margin_pct",
                    "release_date",
                    "source",
                    "data_status",
                },
            },
            "tel_gm_quarterly.parquet": {
                "keys": ("report_quarter",),
                "required": {
                    "company",
                    "report_quarter",
                    "gross_margin_pct",
                    "release_date",
                    "file",
                },
            },
        }
        target_files = [file for file in files if _is_semiconductor_equipment_gm_file(file)]
        for file in target_files:
            profile = profiles[file.name]
            try:
                df = pl.read_parquet(file)
                missing = set(profile["required"]) - set(df.columns)
                if missing:
                    logger.error(f"文件 [{file}] 设备商毛利率表缺少列: {sorted(missing)}")
                    return False
                keys = profile["keys"]
                if df.height != df.unique(subset=list(keys)).height:
                    logger.error(f"文件 [{file}] 设备商毛利率表主键重复: {keys}")
                    return False
                for column in ("release_date", "trade_date"):
                    if column in df.columns and (
                        df.schema[column] != pl.Date or df[column].null_count()
                    ):
                        logger.error(f"文件 [{file}] 设备商毛利率表日期列无效: {column}")
                        return False
                for column in ("company", "report_quarter", "source", "data_status", "file"):
                    if column not in df.columns:
                        continue
                    values = df[column].cast(pl.String, strict=False)
                    if values.is_null().any() or (values.str.strip_chars() == "").any():
                        logger.error(f"文件 [{file}] 设备商毛利率表身份列为空: {column}")
                        return False
                for column in (
                    "net_sales_eur_m",
                    "gross_profit_eur_m",
                    "net_income_eur_m",
                    "ibm_sales_eur_m",
                    "net_bookings_eur_m",
                    "systems_backlog_eur_m",
                    "net_sales_guidance_next_eur_m",
                    "net_sales_jpy_m",
                    "gross_profit_jpy_m",
                ):
                    if column not in df.columns:
                        continue
                    invalid = df.filter(
                        pl.col(column).is_not_null()
                        & (~pl.col(column).is_finite() | (pl.col(column) < 0.0))
                    )
                    if not invalid.is_empty():
                        logger.error(f"文件 [{file}] 设备商毛利率表金额列异常: {column}")
                        return False
                for column in ("gross_margin_pct", "gm_guidance_next_pct", "services_share_pct"):
                    if column not in df.columns:
                        continue
                    invalid = df.filter(
                        pl.col(column).is_not_null()
                        & (
                            ~pl.col(column).is_finite()
                            | (pl.col(column) < 0.0)
                            | (pl.col(column) > 100.0)
                        )
                    )
                    if not invalid.is_empty():
                        logger.error(f"文件 [{file}] 设备商毛利率表比例列超出百分点评分: {column}")
                        return False
            except Exception as exc:  # noqa: BLE001
                logger.error(f"文件 [{file}] 设备商毛利率表质量校验异常: {exc}")
                return False
        return True

    def assert_semiconductor_ratio_scale(self, files: list[Path]) -> bool:
        """断言半导体占比字段使用显式 ratio / percent_points 数值尺度。"""
        ratio_share_columns = (
            "advanced_wafer_pct",
            "hpc_platform_pct",
            "packaging_testing_others_pct",
        )
        percent_point_columns = (
            "tsmc_utilization_pct",
            "smic_utilization_pct",
            "foundry_proxy_utilization_pct",
            "foundry_weighted_utilization_pct",
            "china_share_pct",
            "gross_margin_pct",
            "gm_guidance_next_pct",
            "services_share_pct",
        )
        semiconductor_files = [
            file for file in files if "industry" in file.parts and "semiconductor" in file.parts
        ]
        for file in semiconductor_files:
            try:
                df = pl.read_parquet(file)
                for column in ratio_share_columns:
                    if column not in df.columns:
                        continue
                    invalid = df.filter(
                        pl.col(column).is_not_null()
                        & (
                            ~pl.col(column).is_finite()
                            | (pl.col(column) < 0.0)
                            | (pl.col(column) > 1.0)
                        )
                    )
                    if not invalid.is_empty():
                        logger.error(f"文件 [{file}] ratio 字段 [{column}] 未使用 0~1 小数尺度")
                        return False
                for column in percent_point_columns:
                    if column not in df.columns:
                        continue
                    invalid = df.filter(
                        pl.col(column).is_not_null()
                        & (
                            ~pl.col(column).is_finite()
                            | (pl.col(column) < 0.0)
                            | (pl.col(column) > 110.0)
                        )
                    )
                    if not invalid.is_empty():
                        logger.error(
                            f"文件 [{file}] percent_points 字段 [{column}] 未使用百分点评分尺度"
                        )
                        return False
            except Exception as exc:  # noqa: BLE001
                logger.error(f"文件 [{file}] 半导体比例尺度校验异常: {exc}")
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

    def assert_foundry_quality(self, files: list[Path]) -> bool:
        """断言 Foundry 利用率、单位和代理状态保持可解释且无量纲。"""
        foundry_files = [file for file in files if _is_foundry_file(file)]
        for file in foundry_files:
            try:
                df = pl.read_parquet(file)
                if df.is_empty():
                    continue

                if "report_quarter" not in df.columns or "trade_date" not in df.columns:
                    logger.error(f"文件 [{file}] Foundry 缺少 report_quarter/trade_date")
                    return False
                required_columns = {
                    "tsmc_utilization_status",
                    "smic_utilization_status",
                    "proxy_method",
                    "proxy_status",
                }
                missing_columns = required_columns - set(df.columns)
                if missing_columns:
                    logger.error(
                        f"文件 [{file}] Foundry 缺少新 Schema 列: {sorted(missing_columns)}"
                    )
                    return False
                if df.height != df.unique(subset=["report_quarter"]).height:
                    logger.error(f"文件 [{file}] Foundry 存在重复 report_quarter")
                    return False

                utilization_columns = [
                    column
                    for column in (
                        "tsmc_utilization_pct",
                        "smic_utilization_pct",
                        "foundry_proxy_utilization_pct",
                        "foundry_weighted_utilization_pct",
                    )
                    if column in df.columns
                ]
                for column in utilization_columns:
                    numeric = pl.col(column).cast(pl.Float64, strict=False)
                    invalid = df.filter(
                        numeric.is_not_null()
                        & (~numeric.is_finite() | (numeric < 0.0) | (numeric > 110.0))
                    )
                    if not invalid.is_empty():
                        logger.error(
                            f"文件 [{file}] Foundry 字段 [{column}] 存在非有限或超过 110% 的利用率"
                        )
                        return False

                quantity_ranges = {
                    "tsmc_wafer_shipments_12in_kpcs": (1.0, 100_000.0),
                    "tsmc_capacity_12in_kpcs": (1.0, 100_000.0),
                    "smic_monthly_capacity_8inch_kw": (1.0, 10_000.0),
                    "smic_wafer_shipment_kw": (1.0, 10_000.0),
                }
                for quantity_column, (lower, upper) in quantity_ranges.items():
                    if quantity_column not in df.columns:
                        continue
                    numeric = pl.col(quantity_column).cast(pl.Float64, strict=False)
                    invalid = df.filter(
                        numeric.is_not_null()
                        & (~numeric.is_finite() | (numeric < lower) | (numeric > upper))
                    )
                    if not invalid.is_empty():
                        logger.error(
                            f"文件 [{file}] Foundry 字段 [{quantity_column}] 超出千片口径尺度"
                        )
                        return False

                status_rules = (
                    ("tsmc_utilization_pct", "tsmc_utilization_status"),
                    ("smic_utilization_pct", "smic_utilization_status"),
                )
                for value_column, status_column in status_rules:
                    if status_column not in df.columns:
                        continue
                    if value_column not in df.columns:
                        logger.error(
                            f"文件 [{file}] Foundry 状态列 [{status_column}] 缺少对应数值列"
                        )
                        return False
                    selected_columns = [value_column, status_column]
                    if value_column == "tsmc_utilization_pct":
                        selected_columns.extend(
                            column
                            for column in (
                                "tsmc_wafer_shipments_12in_kpcs",
                                "tsmc_capacity_12in_kpcs",
                            )
                            if column in df.columns
                        )
                    for row in df.select(selected_columns).to_dicts():
                        status = str(row[status_column] or "")
                        value = row[value_column]
                        if status not in {"reported", "derived", "unavailable", "legacy_baseline"}:
                            logger.error(f"文件 [{file}] Foundry 存在未知利用率状态 [{status}]")
                            return False
                        if status == "unavailable" and value is not None:
                            logger.error(
                                f"文件 [{file}] Foundry unavailable 状态却存在数值 [{value_column}]"
                            )
                            return False
                        if status in {"reported", "derived", "legacy_baseline"} and value is None:
                            logger.error(f"文件 [{file}] Foundry {status} 状态缺少数值")
                            return False
                        if value_column == "tsmc_utilization_pct" and status == "derived":
                            shipments = row.get("tsmc_wafer_shipments_12in_kpcs")
                            capacity = row.get("tsmc_capacity_12in_kpcs")
                            if (
                                shipments is None
                                or capacity is None
                                or float(capacity) <= 0
                                or abs(float(value) - float(shipments) / float(capacity) * 100.0)
                                > 0.02
                            ):
                                logger.error(f"文件 [{file}] Foundry derived 利用率公式不一致")
                                return False

                lineage_rules = (
                    (
                        "tsmc",
                        ("tsmc_utilization_pct", "tsmc_wafer_shipments_12in_kpcs"),
                    ),
                    (
                        "smic",
                        (
                            "smic_utilization_pct",
                            "smic_monthly_capacity_8inch_kw",
                            "smic_wafer_shipment_kw",
                        ),
                    ),
                )
                for prefix, value_columns in lineage_rules:
                    url_column = f"{prefix}_source_url"
                    date_column = f"{prefix}_release_date"
                    if url_column not in df.columns or date_column not in df.columns:
                        continue
                    for row in df.select([*value_columns, url_column, date_column]).to_dicts():
                        has_value = any(row.get(column) is not None for column in value_columns)
                        if has_value and (not row.get(url_column) or row.get(date_column) is None):
                            logger.error(f"文件 [{file}] Foundry {prefix} 有值但缺少公司级血缘")
                            return False

                if "proxy_status" in df.columns:
                    proxy_columns = {
                        "foundry_proxy_utilization_pct",
                        "foundry_weighted_utilization_pct",
                        "tsmc_utilization_pct",
                        "smic_utilization_pct",
                        "proxy_method",
                    }
                    if not proxy_columns.issubset(df.columns):
                        logger.error(f"文件 [{file}] Foundry 代理字段不完整")
                        return False
                    shipment_columns = {
                        "tsmc_wafer_shipments_12in_kpcs",
                        "smic_wafer_shipment_kw",
                    }
                    has_shipment_columns = shipment_columns.issubset(df.columns)
                    select_columns = list(proxy_columns)
                    if has_shipment_columns:
                        select_columns.extend(sorted(shipment_columns))
                    for row in df.select(select_columns + ["proxy_status"]).to_dicts():
                        status = str(row["proxy_status"] or "")
                        proxy = row["foundry_proxy_utilization_pct"]
                        tsmc = row["tsmc_utilization_pct"]
                        smic = row["smic_utilization_pct"]
                        if status == "proxy":
                            if tsmc is None or smic is None or proxy is None:
                                logger.error(f"文件 [{file}] Foundry proxy 状态缺少两家公司利用率")
                                return False
                            method = str(row["proxy_method"] or "")
                            if method == "equal_company_mean":
                                expected = round((float(tsmc) + float(smic)) / 2.0, 2)
                                if abs(float(proxy) - expected) > 1e-9:
                                    logger.error(f"文件 [{file}] Foundry 等权代理公式不一致")
                                    return False
                            elif method == "shipment_weighted_mean":
                                # 出货面积加权：TSMC 12 寸 / SMIC 8 寸，面积比 2.25:1
                                if not has_shipment_columns:
                                    logger.error(f"文件 [{file}] Foundry 出货加权代理缺出货列")
                                    return False
                                tsmc_ship = row.get("tsmc_wafer_shipments_12in_kpcs")
                                smic_ship = row.get("smic_wafer_shipment_kw")
                                if (
                                    tsmc_ship is None
                                    or smic_ship is None
                                    or float(tsmc_ship) <= 0
                                    or float(smic_ship) <= 0
                                ):
                                    logger.error(f"文件 [{file}] Foundry 出货加权代理缺出货量")
                                    return False
                                tsmc_weight = float(tsmc_ship) * 2.25
                                smic_weight = float(smic_ship)
                                expected = round(
                                    (float(tsmc) * tsmc_weight + float(smic) * smic_weight)
                                    / (tsmc_weight + smic_weight),
                                    2,
                                )
                                if abs(float(proxy) - expected) > 1e-9:
                                    logger.error(f"文件 [{file}] Foundry 出货加权代理公式不一致")
                                    return False
                        elif status in {"partial", "unavailable"} and proxy is not None:
                            logger.error(f"文件 [{file}] Foundry {status} 状态不应有代理值")
                            return False
                        elif status not in {"proxy", "partial", "unavailable"}:
                            logger.error(f"文件 [{file}] Foundry 存在未知代理状态 [{status}]")
                            return False

                    if "foundry_weighted_utilization_pct" in df.columns:
                        aliases = df.select(
                            [
                                "foundry_proxy_utilization_pct",
                                "foundry_weighted_utilization_pct",
                            ]
                        ).to_dicts()
                        if any(
                            (left is None) != (right is None)
                            or (
                                left is not None
                                and right is not None
                                and abs(float(left) - float(right)) > 1e-9
                            )
                            for left, right in (
                                (
                                    row["foundry_proxy_utilization_pct"],
                                    row["foundry_weighted_utilization_pct"],
                                )
                                for row in aliases
                            )
                        ):
                            logger.error(f"文件 [{file}] Foundry 兼容代理字段与正式字段不一致")
                            return False
            except Exception as exc:  # noqa: BLE001
                logger.error(f"文件 [{file}] Foundry 质量校验异常: {exc}")
                return False
        return True

    def assert_inventory_quality(self, files: list[Path]) -> bool:
        """断言 IDM 存货、营业成本与 DOI 派生关系保持可解释。"""
        inventory_files = [file for file in files if _is_inventory_file(file)]
        required_columns = {
            "symbol",
            "report_quarter",
            "trade_date",
            "inventory_usd_million",
            "cost_of_revenue_usd_million",
            "release_date",
            "unit",
            "data_status",
            "doi_days",
            "total_inventory_usd_million",
            "total_cost_of_revenue_usd_million",
            "idm_equal_doi_days",
            "idm_weighted_doi_days",
            "inventory_regime",
        }
        numeric_columns = (
            "inventory_usd_million",
            "cost_of_revenue_usd_million",
            "doi_days",
            "total_inventory_usd_million",
            "total_cost_of_revenue_usd_million",
            "idm_equal_doi_days",
            "idm_weighted_doi_days",
        )
        regimes = {
            "high_overstocked",
            "elevated_destocking",
            "normal_balanced",
            "tight_restocking",
        }

        for file in inventory_files:
            try:
                df = pl.read_parquet(file)
                if df.is_empty():
                    continue
                missing_columns = required_columns - set(df.columns)
                if missing_columns:
                    logger.error(f"文件 [{file}] Inventory 缺少必需列: {sorted(missing_columns)}")
                    return False
                if df.height != df.unique(subset=["report_quarter", "symbol"]).height:
                    logger.error(f"文件 [{file}] Inventory 存在重复 report_quarter/symbol")
                    return False

                for column in ("trade_date", "release_date"):
                    if df.schema[column] != pl.Date or df[column].null_count():
                        logger.error(f"文件 [{file}] Inventory 日期列无效: {column}")
                        return False
                for column in ("symbol", "report_quarter", "unit", "data_status"):
                    values = df[column].cast(pl.String, strict=False)
                    if values.is_null().any() or (values.str.strip_chars() == "").any():
                        logger.error(f"文件 [{file}] Inventory 身份列存在空值: {column}")
                        return False
                if set(df["unit"].unique().to_list()) != {"days"}:
                    logger.error(f"文件 [{file}] Inventory unit 必须为 days")
                    return False
                if set(df["inventory_regime"].drop_nulls().unique().to_list()) - regimes:
                    logger.error(f"文件 [{file}] Inventory 存在未知 inventory_regime")
                    return False

                for column in numeric_columns:
                    invalid = df.filter(
                        pl.col(column).is_not_null()
                        & (~pl.col(column).is_finite() | (pl.col(column) < 0.0))
                    )
                    if not invalid.is_empty():
                        logger.error(f"文件 [{file}] Inventory 数值列 [{column}] 非有限或为负")
                        return False

                for row in df.select(
                    [
                        "inventory_usd_million",
                        "cost_of_revenue_usd_million",
                        "doi_days",
                    ]
                ).to_dicts():
                    inventory = row["inventory_usd_million"]
                    cost = row["cost_of_revenue_usd_million"]
                    doi = row["doi_days"]
                    if cost is not None and float(cost) > 0.0:
                        expected = (
                            round(float(inventory) / float(cost) * 90.0, 1)
                            if inventory is not None
                            else None
                        )
                        if expected is not None and (
                            doi is None or abs(float(doi) - expected) > 0.1
                        ):
                            logger.error(f"文件 [{file}] Inventory DOI 公式不一致")
                            return False
                    elif doi is not None:
                        logger.error(f"文件 [{file}] Inventory 成本非正却存在 DOI")
                        return False

                for quarter in df["report_quarter"].unique().to_list():
                    quarter_df = df.filter(pl.col("report_quarter") == quarter)
                    totals = quarter_df.select(
                        [
                            pl.col("inventory_usd_million").sum().alias("inventory"),
                            pl.col("cost_of_revenue_usd_million").sum().alias("cost"),
                            pl.col("doi_days").mean().round(1).alias("equal_doi"),
                        ]
                    ).to_dicts()[0]
                    for column in (
                        "total_inventory_usd_million",
                        "total_cost_of_revenue_usd_million",
                        "idm_equal_doi_days",
                        "idm_weighted_doi_days",
                        "inventory_regime",
                    ):
                        if quarter_df[column].drop_nulls().unique().len() > 1:
                            logger.error(f"文件 [{file}] Inventory 季度派生字段不一致: {column}")
                            return False
                    actual_inventory = quarter_df["total_inventory_usd_million"][0]
                    actual_cost = quarter_df["total_cost_of_revenue_usd_million"][0]
                    actual_equal = quarter_df["idm_equal_doi_days"][0]
                    actual_weighted = quarter_df["idm_weighted_doi_days"][0]
                    if (
                        actual_inventory is None
                        or totals["inventory"] is None
                        or abs(float(actual_inventory) - float(totals["inventory"])) > 1e-6
                        or actual_cost is None
                        or totals["cost"] is None
                        or abs(float(actual_cost) - float(totals["cost"])) > 1e-6
                    ):
                        logger.error(f"文件 [{file}] Inventory 季度合计不一致: {quarter}")
                        return False
                    if (
                        actual_equal is not None
                        and totals["equal_doi"] is not None
                        and (abs(float(actual_equal) - float(totals["equal_doi"])) > 0.1)
                    ):
                        logger.error(f"文件 [{file}] Inventory 等权 DOI 不一致: {quarter}")
                        return False
                    if quarter_df.height < _MIN_INVENTORY_CONSTITUENTS:
                        # 季度主体数不足：按设计季度级 DOI 聚合与相态留空
                        # （权威定义见 transforms/inventory.py 的 MIN_INVENTORY_CONSTITUENTS）
                        if (
                            actual_equal is not None
                            or actual_weighted is not None
                            or quarter_df["inventory_regime"][0] is not None
                        ):
                            logger.error(
                                f"文件 [{file}] Inventory 季度 [{quarter}] 主体数不足"
                                f"（<{_MIN_INVENTORY_CONSTITUENTS}）却存在季度级聚合值或相态"
                            )
                            return False
                        continue
                    if float(actual_cost) > 0.0:
                        expected_weighted = round(
                            float(actual_inventory) / float(actual_cost) * 90.0, 1
                        )
                        if actual_weighted is None or (
                            abs(float(actual_weighted) - expected_weighted) > 0.1
                        ):
                            logger.error(f"文件 [{file}] Inventory 加权 DOI 不一致: {quarter}")
                            return False
                        expected_regime = (
                            "high_overstocked"
                            if expected_weighted >= 150.0
                            else "elevated_destocking"
                            if expected_weighted >= 130.0
                            else "normal_balanced"
                            if expected_weighted >= 105.0
                            else "tight_restocking"
                        )
                        if quarter_df["inventory_regime"][0] != expected_regime:
                            logger.error(f"文件 [{file}] Inventory 相态不一致: {quarter}")
                            return False
            except Exception as exc:  # noqa: BLE001
                logger.error(f"文件 [{file}] Inventory 质量校验异常: {exc}")
                return False
        return True

    def assert_tsmc_adv_pkg_revenue_quality(self, files: list[Path]) -> bool:
        """断言台积电官方先进封装财务拆解保持 actual 状态与财务合理性。"""
        target_files = [file for file in files if _is_tsmc_adv_pkg_revenue_file(file)]
        required_columns = {
            "symbol",
            "report_quarter",
            "trade_date",
            "release_date",
            "net_revenue_ntd_bn",
            "net_revenue_usd_bn",
            "packaging_testing_others_ntd_bn",
            "advanced_wafer_pct",
            "hpc_platform_pct",
            "packaging_testing_others_pct",
            "revenue_yoy",
            "revenue_qoq",
            "unit",
            "source",
            "source_url",
            "data_status",
            "collected_at",
        }
        for file in target_files:
            try:
                df = pl.read_parquet(file)
                if df.is_empty():
                    continue
                missing_columns = required_columns - set(df.columns)
                if missing_columns:
                    logger.error(
                        f"文件 [{file}] 台积电官方财务缺少必需列: {sorted(missing_columns)}"
                    )
                    return False

                # 主键唯一性
                if df.height != df.unique(subset=["symbol", "report_quarter"]).height:
                    logger.error(f"文件 [{file}] 存在重复的 (symbol, report_quarter)")
                    return False

                # 绝不允许未来或预测状态，全部必须为 actual
                non_actual = df.filter(pl.col("data_status") != "actual")
                if not non_actual.is_empty():
                    logger.error(
                        f"文件 [{file}] 包含非 actual 状态数据 {len(non_actual)} 行! 违背真实性原则"
                    )
                    return False

                # 数值合理性
                invalid_rev = df.filter(
                    (pl.col("net_revenue_ntd_bn") <= 0) | (pl.col("net_revenue_ntd_bn") > 5000.0)
                )
                if not invalid_rev.is_empty():
                    logger.error(f"文件 [{file}] 台积电季度营收数值超出正常范围 [0, 5000] NT$ B")
                    return False

                # 检查 packaging_testing_others_pct 在 [0.02, 0.25] 区间
                invalid_pkg = df.filter(
                    pl.col("packaging_testing_others_pct").is_not_null()
                    & (
                        (pl.col("packaging_testing_others_pct") < 0.02)
                        | (pl.col("packaging_testing_others_pct") > 0.25)
                    )
                )
                if not invalid_pkg.is_empty():
                    logger.error(
                        f"文件 [{file}] packaging_testing_others_pct 超出合理范围 [0.02, 0.25]"
                    )
                    return False

                # 检查同比与环比（非空时在 [-0.8, 3.0] 区间内）
                for growth_col in ("revenue_yoy", "revenue_qoq"):
                    invalid_growth = df.filter(
                        pl.col(growth_col).is_not_null()
                        & ((pl.col(growth_col) < -0.8) | (pl.col(growth_col) > 3.0))
                    )
                    if not invalid_growth.is_empty():
                        logger.error(f"文件 [{file}] {growth_col} 增速超出合理范围 [-0.8, 3.0]")
                        return False
            except Exception as exc:  # noqa: BLE001
                logger.error(f"文件 [{file}] 台积电官方财务校验异常: {exc}")
                return False
        return True

    def assert_cowos_capacity_estimates_quality(self, files: list[Path]) -> bool:
        """断言智库 CoWoS 产能测算时态隔离、相态合规，绝对禁止 actual 状态。"""
        target_files = [file for file in files if _is_cowos_capacity_estimates_file(file)]
        required_columns = {
            "symbol",
            "report_quarter",
            "trade_date",
            "agency",
            "published_date",
            "monthly_capacity_kwpm",
            "lead_time_months",
            "capacity_yoy",
            "capacity_qoq",
            "bottleneck_regime",
            "unit",
            "source",
            "source_url",
            "data_status",
            "collected_at",
        }
        allowed_regimes = {
            "severe_bottleneck_expansion",
            "moderate_expansion",
            "balanced_or_mature",
        }
        for file in target_files:
            try:
                df = pl.read_parquet(file)
                if df.is_empty():
                    continue
                missing_columns = required_columns - set(df.columns)
                if missing_columns:
                    logger.error(
                        f"文件 [{file}] CoWoS 智库测算缺少必需列: {sorted(missing_columns)}"
                    )
                    return False

                # 主键唯一性
                if (
                    df.height
                    != df.unique(
                        subset=["symbol", "agency", "published_date", "report_quarter"]
                    ).height
                ):
                    logger.error(f"文件 [{file}] 存在重复的智库测算主键")
                    return False

                # 绝对禁止 actual 状态！
                actual_rows = df.filter(pl.col("data_status") == "actual")
                if not actual_rows.is_empty():
                    logger.error(f"文件 [{file}] 绝对禁止将智库预测标记为 actual! 违背双轨物理隔离")
                    return False

                # 时态隔离：凡 trade_date > published_date 必须为 forecast
                temporal_violations = df.filter(
                    (pl.col("trade_date") > pl.col("published_date"))
                    & (pl.col("data_status") != "forecast")
                )
                if not temporal_violations.is_empty():
                    logger.error(
                        f"文件 [{file}] 存在未按时态标记为 forecast 的未来记录: "
                        f"{len(temporal_violations)} 行"
                    )
                    return False

                # 产能千片合理范围 [1.0, 500.0] kwpm
                invalid_cap = df.filter(
                    (pl.col("monthly_capacity_kwpm") < 1.0)
                    | (pl.col("monthly_capacity_kwpm") > 500.0)
                )
                if not invalid_cap.is_empty():
                    logger.error(f"文件 [{file}] CoWoS 月产能超出正常范围 [1.0, 500.0] kwpm")
                    return False

                # 相态枚举校验
                invalid_regimes = df.filter(~pl.col("bottleneck_regime").is_in(allowed_regimes))
                if not invalid_regimes.is_empty():
                    logger.error(f"文件 [{file}] 包含非法的供需瓶颈相态: {invalid_regimes}")
                    return False
            except Exception as exc:  # noqa: BLE001
                logger.error(f"文件 [{file}] CoWoS 智库测算校验异常: {exc}")
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
