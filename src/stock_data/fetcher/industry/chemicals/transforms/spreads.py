"""化工产业链价差 RAW/Curated 转换。"""

from __future__ import annotations

import polars as pl

from stock_data.fetcher.industry.chemicals.quality import validate_spread_raw_rows
from stock_data.fetcher.industry.chemicals.schemas import SPREAD_RAW_SCHEMA, SPREAD_SCHEMA


def build_spread_raw_frame(df: pl.DataFrame) -> pl.DataFrame:
    """校正并返回价差 RAW 表。"""
    return df if not df.is_empty() else pl.DataFrame(schema=SPREAD_RAW_SCHEMA)


def build_spread_curated_frame(df: pl.DataFrame) -> pl.DataFrame:
    """从价差 RAW 源值构建 Curated 表。"""
    if df.is_empty():
        return pl.DataFrame(schema=SPREAD_SCHEMA)
    valid_indices, _errors = validate_spread_raw_rows(df)
    valid_index_set = set(valid_indices)
    records: list[dict[str, object]] = []
    for index, row in enumerate(df.to_dicts()):
        if index not in valid_index_set:
            continue
        records.append(
            {
                "trade_date": row.get("trade_date"),
                "product_name": str(row.get("product_name") or ""),
                "symbol": str(row.get("symbol") or ""),
                "process_type": str(row.get("process_type") or ""),
                "product_price_cny": _safe_float(row.get("product_price_cny_raw")),
                "byproduct_price_cny": _safe_float(row.get("byproduct_price_cny_raw")),
                "raw_material_cost_cny": _safe_float(row.get("raw_material_cost_cny_raw")),
                "spread_margin_cny": _safe_float(row.get("spread_margin_cny_raw")),
                "cash_breakeven_cost_cny": _safe_float(row.get("cash_breakeven_cost_cny_raw")),
                "margin_regime": str(row.get("margin_regime_raw") or ""),
                "source": str(row.get("source") or ""),
                "release_date": row.get("release_date"),
                "collected_at": str(row.get("collected_at") or ""),
            }
        )
    return pl.DataFrame(records, schema=SPREAD_SCHEMA).sort(["product_name", "trade_date"])


def _safe_float(value: object) -> float | None:
    text = str(value or "").strip()
    if not text or text in {"nan", "None"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


__all__ = ["build_spread_curated_frame", "build_spread_raw_frame"]
