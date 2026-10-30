"""Tariffline HS8/HS6 黄金记录构建。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.customs.models import CustomsTradeRecord
from stock_data.fetcher.industry.customs.parsers.catalog import load_hs_catalog
from stock_data.fetcher.industry.customs.transforms.tariffline_gold_loader import (
    _normalize_code,
    _parse_float,
    load_tariffline_records_with_stats,
)


def _merge_lineage(records: Iterable[CustomsTradeRecord], field_name: str) -> str:
    values: set[str] = set()
    for record in records:
        values.update(value for value in getattr(record, field_name).split(";") if value)
    return ";".join(sorted(values))


def build_hs6_records(
    hs8_records: Sequence[CustomsTradeRecord],
    catalog_map: dict[str, dict[str, str]],
) -> list[CustomsTradeRecord]:
    """把 HS8 明细按父码、月份和方向汇总为 HS6 行。"""
    grouped: defaultdict[tuple[str, str, str, str], list[CustomsTradeRecord]] = defaultdict(list)
    for record in hs8_records:
        if len(record.hs_code) == 8:
            grouped[
                (
                    record.hs_parent_code or record.hs_code[:6],
                    record.report_month,
                    record.trade_direction,
                    record.trade_value_currency,
                )
            ].append(record)

    output: list[CustomsTradeRecord] = []
    for (parent, report_month, direction, currency), children in sorted(grouped.items()):
        first = children[0]
        info = catalog_map.get(parent, {})
        units = {record.quantity_unit for record in children if record.quantity_unit}
        quantity_complete = (
            bool(children)
            and all(record.export_volume is not None for record in children)
            and len(units) <= 1
        )
        quantity_unit = next(iter(units), info.get("quantity_unit", ""))
        if len(units) > 1:
            quantity_unit = "mixed"
        export_volume = (
            sum(record.export_volume or 0.0 for record in children) if quantity_complete else None
        )
        output.append(
            CustomsTradeRecord(
                category_key=info.get("category_key", first.category_key),
                category_name=info.get("category_name", first.category_name),
                product_key=f"hs6_{parent}",
                product_name=f"HS6 {parent} 汇总",
                hs_code=parent,
                hs_name=info.get("hs_name", f"HS6 {parent}"),
                report_month=report_month,
                trade_date=first.trade_date,
                trade_direction=direction,
                export_value_usd=sum(record.export_value_usd for record in children),
                export_volume=export_volume,
                quantity_unit=quantity_unit,
                target_l1_code=info.get("target_l1_code", first.target_l1_code),
                target_l1_name=info.get("target_l1_name", first.target_l1_name),
                target_l2_codes=info.get("target_l2_codes", first.target_l2_codes),
                target_l2_names=info.get("target_l2_names", first.target_l2_names),
                target_l3_codes=info.get("target_l3_codes", first.target_l3_codes),
                target_l3_names=info.get("target_l3_names", first.target_l3_names),
                source="UN_Comtrade",
                source_url=first.source_url,
                release_date=max(
                    (record.release_date for record in children if record.release_date),
                    default=None,
                ),
                data_status="derived_hs6",
                collected_at=now_utc_iso(),
                trade_value_currency=currency,
                raw_content_sha256=_merge_lineage(children, "raw_content_sha256"),
                raw_snapshot_path=_merge_lineage(children, "raw_snapshot_path"),
                hs_level="6",
                hs_parent_code=parent,
            )
        )
    return output


def build_tariffline_gold_records(
    hs8_records: Sequence[CustomsTradeRecord],
    catalog_path: Path | str = "config/data/customs/good_h8_codes.csv",
) -> list[CustomsTradeRecord]:
    """返回同一黄金表所需的 HS8 明细行和 HS6 汇总行。"""
    catalog_map = load_hs_catalog(catalog_path)
    records = list(hs8_records) + build_hs6_records(hs8_records, catalog_map)
    records.sort(key=lambda record: (record.report_month, record.hs_level, record.hs_code))
    return records


def load_tariffline_gold_records(
    raw_dir: Path | str,
    catalog_path: Path | str = "config/data/customs/good_h8_codes.csv",
) -> tuple[list[CustomsTradeRecord], int, int]:
    """从 Tariffline RAW 加载黄金表记录，并返回文件数与原始行数。"""
    hs8_records, raw_files, raw_rows = load_tariffline_records_with_stats(raw_dir, catalog_path)
    return build_tariffline_gold_records(hs8_records, catalog_path), raw_files, raw_rows


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _as_text(value: Any, default: str = "") -> str:
    return default if value is None else str(value)


def _record_from_curated_row(row: dict[str, Any]) -> CustomsTradeRecord | None:
    hs_code = _normalize_code(row.get("hs_code"))
    report_month = _as_text(row.get("report_month"))
    trade_date = _as_date(row.get("trade_date"))
    value = _parse_float(row.get("export_value_usd"))
    if not hs_code or not report_month or trade_date is None or value is None:
        return None
    return CustomsTradeRecord(
        category_key=_as_text(row.get("category_key"), "unknown"),
        category_name=_as_text(row.get("category_name"), "未知"),
        product_key=_as_text(row.get("product_key"), hs_code),
        product_name=_as_text(row.get("product_name"), hs_code),
        hs_code=hs_code,
        hs_name=_as_text(row.get("hs_name"), hs_code),
        report_month=report_month,
        trade_date=trade_date,
        trade_direction=_as_text(row.get("trade_direction"), "export"),
        export_value_usd=value,
        export_volume=_parse_float(row.get("export_volume")),
        quantity_unit=_as_text(row.get("quantity_unit")),
        export_asp_usd=_parse_float(row.get("export_asp_usd")),
        target_l1_code=_as_text(row.get("target_l1_code")),
        target_l1_name=_as_text(row.get("target_l1_name")),
        target_l2_codes=_as_text(row.get("target_l2_codes")),
        target_l2_names=_as_text(row.get("target_l2_names")),
        target_l3_codes=_as_text(row.get("target_l3_codes")),
        target_l3_names=_as_text(row.get("target_l3_names")),
        export_value_3mma=_parse_float(row.get("export_value_3mma")),
        yoy_growth_3mma=_parse_float(row.get("yoy_growth_3mma")),
        mom_growth_3mma=_parse_float(row.get("mom_growth_3mma")),
        source=_as_text(row.get("source"), "UN_Comtrade"),
        source_url=_as_text(row.get("source_url")),
        release_date=_as_date(row.get("release_date")),
        data_status=_as_text(row.get("data_status"), "actual"),
        collected_at=_as_text(row.get("collected_at")),
        trade_value_currency=_as_text(row.get("trade_value_currency"), "USD"),
        raw_content_sha256=_as_text(row.get("raw_content_sha256")),
        raw_snapshot_path=_as_text(row.get("raw_snapshot_path")),
        hs_level=_as_text(row.get("hs_level")),
        hs_parent_code=_as_text(row.get("hs_parent_code")),
    )


def load_existing_records(curated_path: Path) -> list[CustomsTradeRecord]:
    if not curated_path.exists():
        return []
    try:
        rows = pl.read_parquet(curated_path).to_dicts()
    except (OSError, pl.exceptions.PolarsError) as exc:
        raise ValueError(f"无法读取现有海关黄金表: {curated_path}: {exc}") from exc
    return [record for row in rows if (record := _record_from_curated_row(row)) is not None]


__all__ = [
    "_record_from_curated_row",
    "build_hs6_records",
    "build_tariffline_gold_records",
    "load_existing_records",
    "load_tariffline_gold_records",
]
