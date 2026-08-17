from datetime import date

import polars as pl

from stock_data.cleaner.date_utils import parse_mixed_date


def test_parse_mixed_date_formats() -> None:
    df_str = pl.DataFrame(
        {
            "raw_date": [
                "2026-08-14",
                "2026/08/14",
                "20260814",
                "20140801.0",
                "2026-08-14 09:30:00",
            ]
        }
    )
    result_str = df_str.with_columns(parse_mixed_date("raw_date").alias("parsed_date"))
    expected_str = [
        date(2026, 8, 14),
        date(2026, 8, 14),
        date(2026, 8, 14),
        date(2014, 8, 1),
        date(2026, 8, 14),
    ]
    assert result_str["parsed_date"].to_list() == expected_str

    df_int = pl.DataFrame({"raw_date": [20260814, 20140801]})
    result_int = df_int.with_columns(parse_mixed_date("raw_date").alias("parsed_date"))
    assert result_int["parsed_date"].to_list() == [date(2026, 8, 14), date(2014, 8, 1)]
