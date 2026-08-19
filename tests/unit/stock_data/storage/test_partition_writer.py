"""Parquet 分区写入器单元测试。"""

import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_data.storage.partition_writer import ParquetPartitionWriter


class TrackingLock:
    def __init__(self) -> None:
        self.entered = 0

    def __enter__(self) -> "TrackingLock":
        self.entered += 1
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


def _hold_file_lock(path: str, ready: Any, release: Any) -> None:
    from stock_data.storage.parquet_merge import _shared_file_lock

    with _shared_file_lock(Path(path)):
        ready.set()
        release.wait(10)


def _acquire_file_lock(path: str, acquired: Any) -> None:
    from stock_data.storage.parquet_merge import _shared_file_lock

    with _shared_file_lock(Path(path)):
        acquired.set()


def test_partition_writer_batch_buffer_append_uses_file_lock(tmp_path: Path) -> None:
    writer = ParquetPartitionWriter(data_source="tushare")
    lock = TrackingLock()
    writer._file_lock = lock
    writer.enable_batch_mode()
    df = pl.DataFrame({"symbol": ["000001.SZ"], "data_source": ["tushare"]})

    saved_path = writer.save_partitioned(
        df=df,
        dataset_name="stock_basic",
        fallback_date=date(2026, 8, 10),
        market_code="CN",
        source="tushare",
        storage_dir=tmp_path,
        path_resolver=lambda dataset, target_date, market: tmp_path / "unused.parquet",
    )

    assert lock.entered == 1
    assert saved_path in writer._write_buffer
    assert len(writer._write_buffer[saved_path]) == 1


def test_partition_writer_serializes_cross_instance_writes_to_same_file(tmp_path: Path) -> None:
    path = tmp_path / "market=CN" / "margin_detail" / "year=2026" / "month=08" / "data.parquet"
    frames = [
        pl.DataFrame(
            {
                "symbol": [symbol],
                "trade_date": [date(2026, 8, day)],
                "rzye": [1.0],
                "data_source": ["tushare"],
                "schema_version": ["v2"],
            }
        )
        for symbol, day in (("000001.SZ", 17), ("600519.SH", 18))
    ]

    def write_frame(frame: pl.DataFrame) -> None:
        ParquetPartitionWriter(data_source="tushare").merge_and_save_parquet(
            path, [frame], source="tushare"
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(write_frame, frames))

    merged = pl.read_parquet(path)
    assert set(merged.get_column("symbol")) == {"000001.SZ", "600519.SH"}
    assert not list(path.parent.glob("*.tmp.parquet"))


def test_partition_writer_file_lock_serializes_across_processes(tmp_path: Path) -> None:
    path = tmp_path / "market=CN" / "stock_daily_bar" / "data.parquet"
    context = multiprocessing.get_context("fork")
    ready = context.Event()
    release = context.Event()
    acquired = context.Event()
    first = context.Process(target=_hold_file_lock, args=(str(path), ready, release))
    second = context.Process(target=_acquire_file_lock, args=(str(path), acquired))
    first.start()
    second_started = False
    try:
        assert ready.wait(5)
        second.start()
        second_started = True
        assert not acquired.wait(0.2)
        release.set()
        assert acquired.wait(5)
    finally:
        release.set()
        first.join(5)
        if second_started:
            second.join(5)
        if first.is_alive():
            first.terminate()
            first.join(5)
        if second_started and second.is_alive():
            second.terminate()
            second.join(5)
    assert first.exitcode == 0
    assert second.exitcode == 0


def test_partition_writer_preserves_optional_legacy_bar_columns(tmp_path: Path) -> None:
    writer = ParquetPartitionWriter(data_source="lixinger")
    path = tmp_path / "market=CN" / "stock_daily_bar" / "data.parquet"
    existing = pl.DataFrame(
        {
            "symbol": ["600519"],
            "trade_date": [date(2026, 8, 13)],
            "close": [1500.0],
            "backwardComplexFactor": [1.0],
            "complexFactor": [1.0],
            "data_source": ["lixinger"],
            "schema_version": ["v2"],
        }
    )
    incoming = existing.drop(["backwardComplexFactor", "complexFactor"]).with_columns(
        pl.lit(date(2026, 8, 14)).alias("trade_date"),
        pl.lit(1510.0).alias("close"),
    )
    path.parent.mkdir(parents=True)
    existing.write_parquet(path)

    merged = writer.merge_and_save_parquet(path, [incoming], source="lixinger")

    assert set(merged["trade_date"].to_list()) == {date(2026, 8, 13), date(2026, 8, 14)}
    assert merged.filter(pl.col("trade_date") == date(2026, 8, 13))["complexFactor"].item() == 1.0
    assert merged.filter(pl.col("trade_date") == date(2026, 8, 14))["complexFactor"].item() is None


def test_partition_writer_aligns_sw_daily_classification_columns(tmp_path: Path) -> None:
    writer = ParquetPartitionWriter(data_source="tushare")
    path = tmp_path / "market=CN" / "sw_daily" / "year=2026" / "month=08" / "data.parquet"
    existing = pl.DataFrame(
        {
            "symbol": ["801010.SI"],
            "trade_date": [date(2026, 8, 13)],
            "close": [1500.0],
            "data_source": ["tushare"],
            "schema_version": ["v2"],
        }
    )
    incoming = existing.drop("trade_date").with_columns(
        pl.lit(date(2026, 8, 14)).alias("trade_date"),
        pl.lit("SW2021").alias("classification"),
        pl.lit("L1").alias("industry_level"),
    )
    path.parent.mkdir(parents=True)
    existing.write_parquet(path)

    merged = writer.merge_and_save_parquet(path, [incoming], source="tushare")

    assert merged.height == 2
    assert merged.filter(pl.col("trade_date") == date(2026, 8, 13))["classification"].item() is None
    assert (
        merged.filter(pl.col("trade_date") == date(2026, 8, 14))["classification"].item()
        == "SW2021"
    )


def test_partition_writer_aligns_empty_nested_struct_to_existing_schema(tmp_path: Path) -> None:
    writer = ParquetPartitionWriter(data_source="lixinger")
    path = tmp_path / "market=CN" / "fs_bank" / "data.parquet"
    existing = pl.DataFrame(
        {
            "symbol": ["600519"],
            "trade_date": [date(2026, 8, 13)],
            "q": [{"metrics": {"roe": 1.0}}],
            "data_source": ["lixinger"],
            "schema_version": ["v2"],
        }
    )
    incoming = pl.DataFrame(
        {
            "symbol": ["000001"],
            "trade_date": [date(2026, 8, 14)],
            "q": [{"metrics": {}}],
            "data_source": ["lixinger"],
            "schema_version": ["v2"],
        }
    )
    path.parent.mkdir(parents=True)
    existing.write_parquet(path)

    merged = writer.merge_and_save_parquet(path, [incoming], source="lixinger")

    assert merged.schema["q"] == existing.schema["q"]
    assert merged.filter(pl.col("symbol") == "000001")["q"].item() == {"metrics": {"roe": None}}


def test_partition_writer_aligns_missing_macro_identity_to_existing_schema(
    tmp_path: Path,
) -> None:
    writer = ParquetPartitionWriter(data_source="tushare")
    path = tmp_path / "market=CN" / "cn_m" / "data.parquet"
    existing = pl.DataFrame(
        {
            "symbol": ["cn_m"],
            "month": ["202606"],
            "m2": [299000.0],
            "data_source": ["tushare"],
            "schema_version": ["v2"],
        }
    )
    incoming = pl.DataFrame(
        {
            "month": ["202607"],
            "m2": [300000.0],
            "data_source": ["tushare"],
            "schema_version": ["v2"],
        }
    )
    path.parent.mkdir(parents=True)
    existing.write_parquet(path)

    merged = writer.merge_and_save_parquet(path, [incoming], source="tushare")

    assert merged["month"].to_list() == ["202606", "202607"]
    assert merged["symbol"].to_list() == ["cn_m", "cn_m"]


def test_partition_writer_allows_index_fundamental_metric_expansion(tmp_path: Path) -> None:
    writer = ParquetPartitionWriter(data_source="lixinger")
    path = tmp_path / "market=CN" / "index_fundamental" / "data.parquet"
    existing = pl.DataFrame(
        {
            "symbol": ["000300"],
            "trade_date": [date(2026, 8, 13)],
            "pe_ttm.ew": [12.0],
            "pb.ew": [1.5],
            "ps_ttm.ew": [1.2],
            "dyr.ew": [0.03],
            "mc": [100.0],
            "data_source": ["lixinger"],
            "schema_version": ["v2"],
        }
    )
    incoming = pl.DataFrame(
        {
            "symbol": ["000300"],
            "trade_date": [date(2026, 8, 14)],
            "pe_ttm.ew": [12.5],
            "pe_ttm.mcw": [11.8],
            "pb.ew": [1.6],
            "pb.mcw": [1.4],
            "ps_ttm.ew": [1.3],
            "ps_ttm.mcw": [1.1],
            "dyr.ew": [0.031],
            "dyr.mcw": [0.029],
            "mc": [101.0],
            "data_source": ["lixinger"],
            "schema_version": ["v2"],
        }
    )
    path.parent.mkdir(parents=True)
    existing.write_parquet(path)

    merged = writer.merge_and_save_parquet(path, [incoming], source="lixinger")

    assert set(merged["trade_date"].to_list()) == {date(2026, 8, 13), date(2026, 8, 14)}
    assert merged.filter(pl.col("trade_date") == date(2026, 8, 13))["pe_ttm.mcw"].item() is None
    assert merged.filter(pl.col("trade_date") == date(2026, 8, 14))["pe_ttm.mcw"].item() == 11.8


def test_partition_writer_normalizes_legacy_index_valuation_assets_column(
    tmp_path: Path,
) -> None:
    writer = ParquetPartitionWriter(data_source="yfinance")
    path = tmp_path / "market=US" / "index_valuation" / "data.parquet"
    existing = pl.DataFrame(
        {
            "symbol": ["SPY"],
            "target_index": ["^GSPC"],
            "trade_date": [date(2026, 8, 12)],
            "trailing_pe": [22.0],
            "forward_pe": [None],
            "price_to_book": [4.0],
            "price_to_sales": [None],
            "dividend_yield": [1.2],
            "total_assets": [500.0],
            "market": ["US"],
            "exchange": ["US_EXCHANGE"],
            "currency": ["USD"],
            "data_source": ["yfinance"],
            "schema_version": ["v2"],
        }
    )
    incoming = existing.drop("total_assets").with_columns(
        pl.lit(date(2026, 8, 13)).alias("trade_date"),
        pl.lit(510.0).alias("market_cap"),
    )
    path.parent.mkdir(parents=True)
    existing.write_parquet(path)

    merged = writer.merge_and_save_parquet(path, [incoming], source="yfinance")

    assert "total_assets" not in merged.columns
    assert merged["market_cap"].to_list() == [500.0, 510.0]


def test_partition_writer_drops_retired_interest_rate_columns_before_schema_check(
    tmp_path: Path,
) -> None:
    writer = ParquetPartitionWriter(data_source="lixinger")
    path = tmp_path / "market=CN" / "interest_rates" / "data.parquet"
    existing = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 13)],
            "areaCode": ["cn"],
            "shibor_on": [1.0],
            "lpr_y1": [3.0],
            "lpr_y5": [3.5],
            "data_source": ["lixinger"],
            "schema_version": ["v2"],
        }
    )
    incoming = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 14)],
            "areaCode": ["cn"],
            "shibor_on": [1.1],
            "data_source": ["lixinger"],
            "schema_version": ["v2"],
        }
    )
    path.parent.mkdir(parents=True)
    existing.write_parquet(path)

    merged = writer.merge_and_save_parquet(path, [incoming], source="lixinger")

    assert "lpr_y1" not in merged.columns
    assert "lpr_y5" not in merged.columns
    assert merged["shibor_on"].to_list() == [1.0, 1.1]


def test_partition_writer_aligns_yfinance_financial_statement_column_union(
    tmp_path: Path,
) -> None:
    writer = ParquetPartitionWriter(data_source="yfinance")
    path = tmp_path / "market=US" / "financials" / "data.parquet"
    existing = pl.DataFrame(
        {
            "symbol": ["AAPL"],
            "as_of_date": [date(2026, 3, 31)],
            "total_revenue": [100.0],
            "data_source": ["yfinance"],
            "schema_version": ["v2"],
        }
    )
    incoming = pl.DataFrame(
        {
            "symbol": ["AAPL"],
            "asOfDate": ["2026-06-30"],
            "total_revenue": [110.0],
            "net_income": [20.0],
            "data_source": ["yfinance"],
            "schema_version": ["v2"],
        }
    )
    path.parent.mkdir(parents=True)
    existing.write_parquet(path)

    merged = writer.merge_and_save_parquet(path, [incoming], source="yfinance")

    assert merged.schema["as_of_date"] == pl.Date
    assert merged["as_of_date"].to_list() == [date(2026, 3, 31), date(2026, 6, 30)]
    assert merged["net_income"].to_list() == [None, 20.0]


def test_partition_writer_replaces_same_yfinance_statement_period(
    tmp_path: Path,
) -> None:
    writer = ParquetPartitionWriter(data_source="yfinance")
    path = tmp_path / "market=US" / "financials" / "data.parquet"
    existing = pl.DataFrame(
        {
            "symbol": ["AAPL"],
            "as_of_date": [date(2026, 6, 30)],
            "total_revenue": [100.0],
            "data_source": ["yfinance"],
            "schema_version": ["v2"],
        }
    )
    incoming = pl.DataFrame(
        {
            "symbol": ["AAPL"],
            "as_of_date": [date(2026, 6, 30)],
            "total_revenue": [110.0],
            "data_source": ["yfinance"],
            "schema_version": ["v2"],
        }
    )
    path.parent.mkdir(parents=True)
    existing.write_parquet(path)

    merged = writer.merge_and_save_parquet(path, [incoming], source="yfinance")

    assert len(merged) == 1
    assert merged["total_revenue"].item() == 110.0
