"""可转债、公司行为与领域 Mart 的专用质量断言。"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from stock_core.utils.logger import logger

DOMAIN_MART_RULES: dict[str, tuple[str, tuple[str, ...]]] = {
    "convertible_bond_daily": ("trade_date", ("trade_date",)),
    "insider_activity_daily": ("announcement_date", ("announcement_date",)),
    "repurchase_daily": ("announcement_date", ("announcement_date",)),
    "block_trade_daily": ("trade_date", ("trade_date",)),
    "settlement_iv_proxy_daily": (
        "trade_date",
        ("trade_date", "underlying_symbol"),
    ),
}

DOMAIN_INPUT_REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "cb_basic": ("symbol", "bond_short_name", "stk_code", "list_date", "exchange"),
    "cb_daily": ("symbol", "trade_date", "close"),
    "stk_holdertrade": ("symbol", "ann_date", "holder_name", "in_de", "change_vol"),
    "repurchase": ("symbol", "ann_date", "proc"),
    "block_trade": ("symbol", "trade_date", "price", "volume", "amount"),
}

DOMAIN_INPUT_DATE_COLUMNS: dict[str, tuple[str, ...]] = {
    "cb_basic": ("list_date", "delist_date"),
    "cb_daily": ("trade_date",),
    "stk_holdertrade": ("ann_date",),
    "repurchase": ("ann_date",),
    "block_trade": ("trade_date",),
}

DOMAIN_INPUT_NON_NEGATIVE_COLUMNS: dict[str, tuple[str, ...]] = {
    "cb_daily": ("close", "volume", "amount"),
    "repurchase": ("volume", "amount"),
    "block_trade": ("price", "volume", "amount"),
}


def _dataset_name_from_path(file: Path) -> str:
    dataset_name = file.parent.name
    if dataset_name.startswith("month="):
        return file.parent.parent.parent.name
    return dataset_name


def assert_domain_mart_quality(_gate: object, files: list[Path]) -> bool:
    """校验领域 Mart 的日期、主键唯一性与数值有限性。"""
    for file in files:
        if file.parent.name != "mart" or file.stem not in DOMAIN_MART_RULES:
            continue
        mart_name = file.stem
        date_column, keys = DOMAIN_MART_RULES[mart_name]
        try:
            frame = pl.read_parquet(file)
            if frame.is_empty():
                continue
            if date_column not in frame.columns or frame[date_column].dtype != pl.Date:
                logger.error(f"领域 Mart [{file}] 日期列缺失或不是 pl.Date: {date_column}")
                return False
            if any(key not in frame.columns for key in keys):
                logger.error(f"领域 Mart [{file}] 缺少主键列: {keys}")
                return False
            if frame.height != frame.unique(subset=list(keys)).height:
                logger.error(f"领域 Mart [{file}] 存在重复主键: {keys}")
                return False
            float_columns = [
                column
                for column, dtype in frame.schema.items()
                if dtype in (pl.Float32, pl.Float64)
            ]
            if float_columns:
                invalid = frame.filter(
                    pl.any_horizontal(
                        [
                            pl.col(column).is_not_null() & ~pl.col(column).is_finite()
                            for column in float_columns
                        ]
                    )
                )
                if not invalid.is_empty():
                    logger.error(f"领域 Mart [{file}] 存在非有限数值")
                    return False
        except Exception as exc:
            logger.error(f"领域 Mart [{file}] 质量校验异常: {exc}")
            return False
    return True


def assert_domain_input_quality(_gate: object, files: list[Path]) -> bool:
    """校验可转债与公司行为 Curated 输入的字段、日期和数值契约。"""
    for file in files:
        dataset_name = _dataset_name_from_path(file)
        if dataset_name not in DOMAIN_INPUT_REQUIRED_COLUMNS:
            continue
        try:
            frame = pl.read_parquet(file)
            if frame.is_empty():
                continue
            required = DOMAIN_INPUT_REQUIRED_COLUMNS[dataset_name]
            missing = [column for column in required if column not in frame.columns]
            if missing:
                logger.error(f"输入数据集 [{file}] 缺少必需列: {missing}")
                return False
            for column in DOMAIN_INPUT_DATE_COLUMNS.get(dataset_name, ()):
                if column not in frame.columns:
                    continue
                if frame[column].dtype != pl.Date:
                    logger.error(f"输入数据集 [{file}] 日期列不是 pl.Date: {column}")
                    return False
            numeric_columns = [
                column
                for column in DOMAIN_INPUT_NON_NEGATIVE_COLUMNS.get(dataset_name, ())
                if column in frame.columns
            ]
            if numeric_columns:
                invalid = frame.filter(
                    pl.any_horizontal(
                        [
                            pl.col(column).is_not_null()
                            & (
                                ~pl.col(column).cast(pl.Float64, strict=False).is_finite()
                                | (pl.col(column).cast(pl.Float64, strict=False) < 0)
                            )
                            for column in numeric_columns
                        ]
                    )
                )
                if not invalid.is_empty():
                    logger.error(f"输入数据集 [{file}] 存在负值或非有限数值")
                    return False
        except Exception as exc:
            logger.error(f"输入数据集 [{file}] 质量校验异常: {exc}")
            return False
    return True


__all__ = [
    "DOMAIN_INPUT_DATE_COLUMNS",
    "DOMAIN_INPUT_NON_NEGATIVE_COLUMNS",
    "DOMAIN_INPUT_REQUIRED_COLUMNS",
    "DOMAIN_MART_RULES",
    "assert_domain_input_quality",
    "assert_domain_mart_quality",
]
