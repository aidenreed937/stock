from datetime import date

import polars as pl

from stock_data.catalog.lazy_read import _business_date_expr, finalize_dataset_frame


def test_business_date_expr_parses_quarter_column() -> None:
    df = pl.DataFrame({"quarter": ["2024Q1", "2024Q4", "2025Q3", "2026Q1"]})

    result = df.with_columns(_business_date_expr("quarter").alias("_date"))

    assert result["_date"].to_list() == [
        date(2024, 1, 1),
        date(2024, 10, 1),
        date(2025, 7, 1),
        date(2026, 1, 1),
    ]


def test_business_date_expr_parses_month_column() -> None:
    df = pl.DataFrame({"month": ["202401", "202512"]})

    result = df.with_columns(_business_date_expr("month").alias("_date"))

    assert result["_date"].to_list() == [date(2024, 1, 1), date(2025, 12, 1)]


def test_finalize_dataset_frame_filters_quarter_dated_frame() -> None:
    frame = pl.DataFrame(
        {
            "symbol": ["cn_gdp"] * 4,
            "quarter": ["2024Q1", "2024Q4", "2025Q3", "2026Q1"],
            "gdp": [1.0, 2.0, 3.0, 4.0],
        }
    )

    result = finalize_dataset_frame(
        frame,
        "cn_gdp",
        "tushare",
        date_candidates=("quarter",),
        start_date=date(2024, 4, 1),
        end_date=date(2025, 12, 31),
        symbols=None,
    )

    assert result["quarter"].to_list() == ["2024Q4", "2025Q3"]
