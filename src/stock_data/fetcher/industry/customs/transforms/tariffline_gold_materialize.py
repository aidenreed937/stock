"""Tariffline 黄金表物化与质量校验。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from stock_data.fetcher.industry.common import save_curated_fact
from stock_data.fetcher.industry.customs.models import CustomsTradeRecord
from stock_data.fetcher.industry.customs.transforms.customs_trade import (
    records_to_customs_trade_frame,
)
from stock_data.fetcher.industry.customs.transforms.tariffline_gold_builder import (
    load_existing_records,
    load_tariffline_gold_records,
)
from stock_data.fetcher.industry.customs.transforms.tariffline_gold_loader import (
    _normalize_period,
)

_GOLDEN_PRIMARY_KEYS = [
    "product_key",
    "hs_code",
    "report_month",
    "trade_direction",
    "trade_value_currency",
]
_GOLDEN_CODE_KEYS = [
    "hs_code",
    "report_month",
    "trade_direction",
    "trade_value_currency",
]


@dataclass(frozen=True)
class TarifflineGoldSummary:
    """Tariffline 黄金表物化与校验摘要。"""

    raw_files: int
    raw_rows: int
    hs8_rows: int
    hs6_rows: int
    curated_rows: int
    product_count: int


def materialize_tariffline_gold(
    *,
    raw_dir: Path | str,
    catalog_path: Path | str = "config/data/customs/hs_codes_catalog.csv",
    curated_path: Path | str = "data/curated/industry/customs_trade.parquet",
) -> Any:
    """把所有有效 Tariffline RAW 合并到统一海关黄金表。"""
    new_records, raw_files, raw_rows = load_tariffline_gold_records(raw_dir, catalog_path)
    if not new_records:
        raise ValueError("Tariffline RAW 没有可物化的有效记录")

    merged: dict[tuple[str, str, str, str], CustomsTradeRecord] = {}
    for record in load_existing_records(Path(curated_path)):
        merged[
            (
                record.hs_code,
                record.report_month,
                record.trade_direction,
                record.trade_value_currency,
            )
        ] = record
    for record in new_records:
        merged[
            (
                record.hs_code,
                record.report_month,
                record.trade_direction,
                record.trade_value_currency,
            )
        ] = record

    curated_rows = save_curated_fact(
        records_to_customs_trade_frame(list(merged.values())),
        curated_path,
        primary_keys=_GOLDEN_CODE_KEYS,
    )
    return TarifflineGoldSummary(
        raw_files=raw_files,
        raw_rows=raw_rows,
        hs8_rows=sum(1 for record in new_records if record.hs_level == "8"),
        hs6_rows=sum(1 for record in new_records if record.hs_level == "6"),
        curated_rows=curated_rows,
        product_count=len({record.product_key for record in new_records if record.hs_level == "8"}),
    )


def _month_range(start_month: str, end_month: str) -> list[str]:
    start = _normalize_period(start_month)
    end = _normalize_period(end_month)
    if not start or not end or start > end:
        raise ValueError(f"月份范围无效: {start_month} - {end_month}")
    year, month = int(start[:4]), int(start[4:])
    end_year, end_number = int(end[:4]), int(end[4:])
    months: list[str] = []
    while (year, month) <= (end_year, end_number):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return months


def validate_tariffline_gold(
    curated_path: Path | str,
    *,
    start_month: str | None = None,
    end_month: str | None = None,
) -> dict[str, Any]:
    """检查黄金表层级、主键、月份和 HS6/HS8 父子覆盖。"""
    path = Path(curated_path)
    if not path.exists():
        return {"errors": [f"黄金表不存在: {path}"]}
    frame = pl.read_parquet(path)
    required = {"hs_code", "hs_level", "hs_parent_code", "report_month", *_GOLDEN_PRIMARY_KEYS}
    missing = sorted(required - set(frame.columns))
    if missing:
        return {"errors": [f"黄金表缺少字段: {', '.join(missing)}"]}

    errors: list[str] = []
    rows = frame.select(["hs_code", "hs_level", "hs_parent_code"]).to_dicts()
    invalid_hierarchy = sum(
        1
        for row in rows
        if str(row["hs_level"] or "") not in {"6", "8"}
        or len(str(row["hs_code"] or "")) != int(str(row["hs_level"] or "0"))
        or str(row["hs_parent_code"] or "") != str(row["hs_code"] or "")[:6]
    )
    if invalid_hierarchy:
        errors.append(f"层级字段不一致: {invalid_hierarchy} 行")

    duplicate_rows = (
        frame.group_by(_GOLDEN_PRIMARY_KEYS)
        .agg(pl.len().alias("_n"))
        .filter(pl.col("_n") > 1)
        .height
    )
    if duplicate_rows:
        errors.append(f"主键重复: {duplicate_rows} 组")

    target = frame
    if start_month and end_month:
        target = frame.filter(pl.col("report_month").is_in(_month_range(start_month, end_month)))
        if target.is_empty():
            errors.append(f"目标月份无数据: {start_month} - {end_month}")

    hs8 = target.filter(pl.col("hs_level") == "8")
    hs6 = target.filter(pl.col("hs_level") == "6")
    hs8_parents = set(hs8["hs_parent_code"].drop_nulls().to_list())
    hs6_parents = set(hs6["hs_code"].drop_nulls().to_list())
    missing_parents = sorted(hs8_parents - hs6_parents)
    if missing_parents:
        errors.append(f"HS8 缺少对应 HS6 汇总行: {', '.join(missing_parents[:10])}")

    return {
        "errors": errors,
        "curated_rows": frame.height,
        "target_rows": target.height,
        "hs8_rows": hs8.height,
        "hs6_rows": hs6.height,
        "hs8_parent_count": len(hs8_parents),
        "hs6_parent_count": len(hs6_parents),
        "duplicate_groups": duplicate_rows,
        "invalid_hierarchy_rows": invalid_hierarchy,
    }


__all__ = ["TarifflineGoldSummary", "materialize_tariffline_gold", "validate_tariffline_gold"]
