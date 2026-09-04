"""SEMI WWSEMS 黄金事实转换器。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import polars as pl

from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.semiconductor.schemas import (
    SEMI_EQUIPMENT_CURATED_SCHEMA,
    SEMI_EQUIPMENT_RAW_SCHEMA,
)
from stock_data.fetcher.industry.semiconductor.transforms.release_date import (
    require_raw_release_dates,
)


def build_semi_equipment_raw_frame(
    items: Sequence[dict[str, Any]] | pl.DataFrame,
    collected_at: str | None = None,
) -> pl.DataFrame:
    """将 SEMI 新闻稿解析结果整理为源端字段/字符串值优先的 RAW 帧。"""
    if isinstance(items, pl.DataFrame):
        if items.is_empty() and not items.columns:
            return pl.DataFrame(schema=SEMI_EQUIPMENT_RAW_SCHEMA)
        items = _normalise_raw_frame(items)
        return require_raw_release_dates(
            (
                items.select(list(SEMI_EQUIPMENT_RAW_SCHEMA))
                .with_columns(
                    [
                        pl.col(name).cast(dtype).alias(name)
                        for name, dtype in SEMI_EQUIPMENT_RAW_SCHEMA.items()
                    ]
                )
                .sort("trade_date")
            ),
            "semiconductor_equipment_semi",
        )
    if not items:
        return pl.DataFrame(schema=SEMI_EQUIPMENT_RAW_SCHEMA)

    now_iso = collected_at or now_utc_iso()
    rows: list[dict[str, Any]] = []
    for item in items:
        rows.append(
            {
                "report_quarter": item["report_quarter"],
                "trade_date": item["trade_date"],
                "source_record_type": item.get("source_record_type") or "quarterly_actual",
                "report_year": _item_raw_string(item, "report_year", ""),
                "global_billings_raw": _item_raw_string(
                    item, "global_billings_raw", "global_billings_billion_usd"
                ),
                "china_billings_raw": _item_raw_string(
                    item, "china_billings_raw", "china_billings_billion_usd"
                ),
                "annual_billings_raw": _item_raw_string(
                    item, "annual_billings_raw", "annual_billings_billion_usd"
                ),
                "yoy_growth_raw": _item_raw_string(item, "yoy_growth_raw", "yoy_growth"),
                "qoq_growth_raw": _item_raw_string(item, "qoq_growth_raw", "qoq_growth"),
                "source": item.get("source") or "SEMI_WWSEMS",
                "source_url": item.get("source_url")
                or "https://www.semi.org/en/news-media/press-releases",
                "release_date": item.get("release_date"),
                "data_status": item.get("data_status") or "actual",
                "collected_at": item.get("collected_at") or now_iso,
                "raw_content_sha256": item.get("raw_content_sha256") or "",
                "raw_snapshot_path": item.get("raw_snapshot_path") or "",
            }
        )
    return require_raw_release_dates(
        pl.DataFrame(rows, schema=SEMI_EQUIPMENT_RAW_SCHEMA).sort("trade_date"),
        "semiconductor_equipment_semi",
    )


def _normalise_raw_frame(df: pl.DataFrame) -> pl.DataFrame:
    additions: list[pl.Expr] = []
    if "source_record_type" not in df.columns:
        additions.append(pl.lit("quarterly_actual").alias("source_record_type"))
    if "report_year" not in df.columns:
        additions.append(
            pl.col("report_quarter").cast(pl.String).str.extract(r"^(\d{4})").alias("report_year")
        )
    if "global_billings_raw" not in df.columns:
        additions.append(
            _string_expr_from_available(df, "global_billings_billion_usd").alias(
                "global_billings_raw"
            )
        )
    if "china_billings_raw" not in df.columns:
        additions.append(
            _string_expr_from_available(df, "china_billings_billion_usd").alias(
                "china_billings_raw"
            )
        )
    if "annual_billings_raw" not in df.columns:
        additions.append(
            _string_expr_from_available(df, "annual_billings_billion_usd").alias(
                "annual_billings_raw"
            )
        )
    if "yoy_growth_raw" not in df.columns:
        additions.append(_string_expr_from_available(df, "yoy_growth").alias("yoy_growth_raw"))
    if "qoq_growth_raw" not in df.columns:
        additions.append(_string_expr_from_available(df, "qoq_growth").alias("qoq_growth_raw"))
    df = df.with_columns(additions) if additions else df
    return _with_missing_columns(df, list(SEMI_EQUIPMENT_RAW_SCHEMA))


def _with_missing_columns(df: pl.DataFrame, schema_columns: list[str]) -> pl.DataFrame:
    additions: list[pl.Expr] = []
    for column in schema_columns:
        if column not in df.columns:
            additions.append(pl.lit("").alias(column))
    return df.with_columns(additions) if additions else df


def _item_raw_string(item: dict[str, Any], raw_key: str, fallback_key: str) -> str | None:
    value = item.get(raw_key)
    if value is None:
        value = item.get(fallback_key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_expr_from_available(df: pl.DataFrame, column: str) -> pl.Expr:
    if column not in df.columns:
        return pl.lit(None, dtype=pl.String)
    return pl.col(column).cast(pl.String)


def build_semi_equipment_curated_frame(df_raw: pl.DataFrame) -> pl.DataFrame:
    """补齐 SEMI 设备出货事实表的同比、环比与中国区占比。"""
    if df_raw.is_empty():
        return pl.DataFrame(schema=SEMI_EQUIPMENT_CURATED_SCHEMA)

    df = _normalise_curated_inputs(df_raw).sort("trade_date")
    missing_columns: list[pl.Expr] = []
    if "yoy_growth" not in df.columns:
        missing_columns.append(pl.lit(None, dtype=pl.Float64).alias("yoy_growth"))
    if "qoq_growth" not in df.columns:
        missing_columns.append(pl.lit(None, dtype=pl.Float64).alias("qoq_growth"))
    if "china_share_pct" not in df.columns:
        missing_columns.append(pl.lit(None, dtype=pl.Float64).alias("china_share_pct"))
    if missing_columns:
        df = df.with_columns(missing_columns)
    df = _append_derived_q4_from_annual_sources(df)
    df = df.filter(pl.col("source_record_type") != "annual_source").sort("trade_date")

    df = (
        df.with_columns(
            pl.col("global_billings_billion_usd").pct_change(4).round(4).alias("_yoy"),
            pl.col("global_billings_billion_usd").pct_change(1).round(4).alias("_qoq"),
        )
        .with_columns(
            pl.when(pl.col("yoy_growth").is_null())
            .then(pl.col("_yoy"))
            .otherwise(pl.col("yoy_growth"))
            .alias("yoy_growth"),
            pl.when(pl.col("qoq_growth").is_null())
            .then(pl.col("_qoq"))
            .otherwise(pl.col("qoq_growth"))
            .alias("qoq_growth"),
            pl.when(
                pl.col("china_share_pct").is_null()
                & pl.col("china_billings_billion_usd").is_not_null()
                & (pl.col("global_billings_billion_usd") > 0)
            )
            .then(
                (
                    pl.col("china_billings_billion_usd")
                    / pl.col("global_billings_billion_usd")
                    * 100.0
                ).round(2)
            )
            .otherwise(pl.col("china_share_pct"))
            .alias("china_share_pct"),
        )
        .drop(["_yoy", "_qoq"])
    )
    return df.select(list(SEMI_EQUIPMENT_CURATED_SCHEMA)).with_columns(
        [
            pl.col(name).cast(dtype).alias(name)
            for name, dtype in SEMI_EQUIPMENT_CURATED_SCHEMA.items()
        ]
    )


def _normalise_curated_inputs(df_raw: pl.DataFrame) -> pl.DataFrame:
    df = df_raw
    additions: list[pl.Expr] = []
    if "source_record_type" not in df.columns:
        additions.append(pl.lit("quarterly_actual").alias("source_record_type"))
    if "report_year" not in df.columns:
        additions.append(
            pl.col("report_quarter").cast(pl.String).str.extract(r"^(\d{4})").alias("report_year")
        )
    if "global_billings_billion_usd" not in df.columns:
        additions.append(
            _numeric_expr_from_available(df, "global_billings_raw").alias(
                "global_billings_billion_usd"
            )
        )
    else:
        additions.append(pl.col("global_billings_billion_usd").cast(pl.Float64, strict=False))
    if "china_billings_billion_usd" not in df.columns:
        additions.append(
            _numeric_expr_from_available(df, "china_billings_raw").alias(
                "china_billings_billion_usd"
            )
        )
    else:
        additions.append(pl.col("china_billings_billion_usd").cast(pl.Float64, strict=False))
    if "annual_billings_billion_usd" not in df.columns:
        additions.append(
            _numeric_expr_from_available(df, "annual_billings_raw").alias(
                "annual_billings_billion_usd"
            )
        )
    else:
        additions.append(pl.col("annual_billings_billion_usd").cast(pl.Float64, strict=False))

    raw_yoy = _percent_expr_from_available(df, "yoy_growth_raw")
    raw_qoq = _percent_expr_from_available(df, "qoq_growth_raw")
    if "yoy_growth" not in df.columns:
        additions.append(raw_yoy.alias("yoy_growth"))
    else:
        additions.append(pl.col("yoy_growth").cast(pl.Float64, strict=False).fill_null(raw_yoy))
    if "qoq_growth" not in df.columns:
        additions.append(raw_qoq.alias("qoq_growth"))
    else:
        additions.append(pl.col("qoq_growth").cast(pl.Float64, strict=False).fill_null(raw_qoq))

    defaults: dict[str, str] = {
        "unit": "billion_usd",
        "source": "SEMI_WWSEMS",
        "source_url": "",
        "data_status": "actual",
        "collected_at": "",
    }
    for column, value in defaults.items():
        if column not in df.columns:
            additions.append(pl.lit(value).alias(column))
    return df.with_columns(additions)


def _append_derived_q4_from_annual_sources(df: pl.DataFrame) -> pl.DataFrame:
    annual_rows = [row for row in df.to_dicts() if row.get("source_record_type") == "annual_source"]
    if not annual_rows:
        return df

    quarterly_rows = [
        row for row in df.to_dicts() if row.get("source_record_type") != "annual_source"
    ]
    existing_quarters = {str(row.get("report_quarter")) for row in quarterly_rows}
    quarterly_by_key = {str(row.get("report_quarter")): row for row in quarterly_rows}
    derived_rows: list[dict[str, Any]] = []
    for annual_row in annual_rows:
        year = _annual_row_year(annual_row)
        if year is None:
            continue
        report_quarter = f"{year}-Q4"
        if report_quarter in existing_quarters:
            continue
        first_three = [quarterly_by_key.get(f"{year}-Q{quarter}") for quarter in (1, 2, 3)]
        if any(row is None for row in first_three):
            continue
        first_three_values = [
            _float_value(row.get("global_billings_billion_usd"))
            for row in first_three
            if row is not None
        ]
        annual_total = _float_value(annual_row.get("annual_billings_billion_usd"))
        if annual_total is None or any(value is None for value in first_three_values):
            continue
        q4_billings = round(
            annual_total - sum(value for value in first_three_values if value is not None),
            2,
        )
        if q4_billings <= 0:
            continue
        first_three_china = [
            _float_value(row.get("china_billings_billion_usd"))
            for row in first_three
            if row is not None
        ]
        annual_china = _float_value(annual_row.get("china_billings_billion_usd"))
        q4_china = None
        if annual_china is not None and not any(value is None for value in first_three_china):
            q4_china = round(
                annual_china - sum(value for value in first_three_china if value is not None),
                2,
            )
            if q4_china <= 0:
                q4_china = None
        derived_row = dict.fromkeys(df.columns)
        derived_row.update(
            {
                "report_quarter": report_quarter,
                "trade_date": date(year, 12, 31),
                "source_record_type": "derived_quarter",
                "report_year": str(year),
                "global_billings_billion_usd": q4_billings,
                "china_billings_billion_usd": q4_china,
                "unit": "billion_usd",
                "source": annual_row.get("source") or "SEMI_WWSEMS",
                "source_url": annual_row.get("source_url") or "",
                "release_date": annual_row.get("release_date"),
                "data_status": "derived_from_annual",
                "collected_at": annual_row.get("collected_at") or "",
                "yoy_growth": None,
                "qoq_growth": None,
                "china_share_pct": None,
            }
        )
        derived_rows.append(derived_row)
        existing_quarters.add(report_quarter)
    if not derived_rows:
        return df
    derived_df = pl.DataFrame(derived_rows, schema=df.schema)
    return pl.concat([df, derived_df], how="vertical_relaxed")


def _annual_row_year(row: dict[str, Any]) -> int | None:
    value = row.get("report_year")
    if value not in (None, ""):
        try:
            return int(str(value))
        except (TypeError, ValueError):
            return None
    trade_date = row.get("trade_date")
    if isinstance(trade_date, date):
        return trade_date.year
    return None


def _float_value(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _numeric_expr_from_available(df: pl.DataFrame, column: str) -> pl.Expr:
    if column not in df.columns:
        return pl.lit(None, dtype=pl.Float64)
    return _numeric_expr_from_raw(column)


def _numeric_expr_from_raw(column: str) -> pl.Expr:
    return (
        pl.col(column)
        .cast(pl.String)
        .str.replace_all(r"[^\d.-]", "")
        .cast(pl.Float64, strict=False)
    )


def _percent_expr_from_available(df: pl.DataFrame, column: str) -> pl.Expr:
    if column not in df.columns:
        return pl.lit(None, dtype=pl.Float64)
    return _percent_expr_from_raw(column)


def _percent_expr_from_raw(column: str) -> pl.Expr:
    numeric = _numeric_expr_from_raw(column)
    raw_text = pl.col(column).cast(pl.String)
    return (
        pl.when(numeric.is_null())
        .then(None)
        .when(raw_text.str.contains("%") | (numeric.abs() > 2.0))
        .then((numeric / 100.0).round(4))
        .otherwise(numeric.round(4))
    )
