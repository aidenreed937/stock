"""LiXinger 行业财报 TTM Curated 重建测试。"""

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from stock_data.governance.ops.rebuild_lixinger_industry_financial_ttm import (
    rebuild_lixinger_industry_financial_ttm,
)


def _financial_frame() -> pl.DataFrame:
    report_types = [
        "first_quarterly_report",
        "interim_report",
        "third_quarterly_report",
        "annual_report",
    ] * 2
    dates = [
        date(2021, 3, 31),
        date(2021, 6, 30),
        date(2021, 9, 30),
        date(2021, 12, 31),
        date(2022, 3, 31),
        date(2022, 6, 30),
        date(2022, 9, 30),
        date(2022, 12, 31),
    ]
    cumulative = [100, 220, 340, 480, 110, 250, 400, 560]
    return pl.DataFrame(
        {
            "symbol": ["110101"] * 8,
            "trade_date": dates,
            "standardDate": dates,
            "reportType": report_types,
            "q": [
                {
                    "ps": {
                        "toi": {"t": value, "c_y2y": None, "ttm_y2y": None},
                        "np": {"t": value, "c_y2y": None, "ttm_y2y": None},
                    },
                    "m": {"roe": {"ttm": None}},
                }
                for value in cumulative
            ],
            "data_source": ["lixinger"] * 8,
            "schema_version": ["v2"] * 8,
        }
    )


def test_rebuild_lixinger_industry_financial_ttm_dry_run_and_apply(tmp_path: Path) -> None:
    path = tmp_path / "lixinger" / "market=CN" / "sw_2021_l3_fs_bank" / "data.parquet"
    path.parent.mkdir(parents=True)
    _financial_frame().write_parquet(path)

    summaries = rebuild_lixinger_industry_financial_ttm(
        tmp_path,
        datasets=("sw_2021_l3_fs_bank",),
        apply=False,
    )
    assert summaries[0]["toi_derived_nonnull"] == 1
    assert "ttm_y2y_derived" not in {
        field.name for field in pl.read_parquet(path).schema["q"].fields[0].dtype.fields
    }

    applied = rebuild_lixinger_industry_financial_ttm(
        tmp_path,
        datasets=("sw_2021_l3_fs_bank",),
        apply=True,
    )
    assert applied[0]["np_derived_nonnull"] == 1
    output = pl.read_parquet(path)
    derived = output.select(
        pl.col("q").struct.field("ps").struct.field("toi").struct.field("ttm_y2y_derived")
    ).to_series()
    assert derived[7] == pytest.approx(560 / 480 - 1)
    assert path.with_name("data.pre_ttm.bak.parquet").exists()
