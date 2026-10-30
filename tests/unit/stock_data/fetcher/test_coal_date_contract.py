"""煤炭 Curated 日期契约测试。"""

from datetime import date
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.coal.models import CoalMarketRecord
from stock_data.fetcher.industry.coal.transforms import records_to_coal_market_frame
from stock_data.fetcher.industry.common import save_curated_fact


def test_coal_curated_date_contract_migrates_existing_string_key(tmp_path: Path) -> None:
    record = CoalMarketRecord(
        report_date="2020-01-03",
        trade_date=date(2020, 1, 3),
        q5500_fob_price_cny=558.0,
    )
    incoming = records_to_coal_market_frame([record])
    legacy = incoming.with_columns(pl.col("report_date").cast(pl.String))
    target = tmp_path / "coal_market.parquet"
    legacy.write_parquet(target)

    assert save_curated_fact(incoming, target, primary_keys=["report_date"]) == 1

    loaded = pl.read_parquet(target)
    assert loaded.schema["report_date"] == pl.Date
    assert loaded["report_date"].to_list() == [date(2020, 1, 3)]
