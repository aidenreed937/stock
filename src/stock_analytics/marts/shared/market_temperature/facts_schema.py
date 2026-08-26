"""市场温度计事实表 Schema。"""

from __future__ import annotations

from typing import Any

import polars as pl

FACT_SCHEMA: dict[str, Any] = {
    "fact_id": pl.Utf8,
    "category": pl.Utf8,
    "dimension": pl.Utf8,
    "data_source": pl.Utf8,
    "dataset": pl.Utf8,
    "as_of_date": pl.Date,
    "metric_date": pl.Date,
    "window": pl.Int64,
    "metric_id": pl.Utf8,
    "value_float": pl.Float64,
    "value_text": pl.Utf8,
    "unit": pl.Utf8,
    "sample_size": pl.Int64,
    "source": pl.Utf8,
    "status": pl.Utf8,
    "note": pl.Utf8,
}


def empty_facts() -> pl.DataFrame:
    """返回稳定 schema 的空事实表。"""
    return pl.DataFrame(schema=FACT_SCHEMA)


__all__ = ["FACT_SCHEMA", "empty_facts"]
