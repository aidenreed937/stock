"""Parquet 分区写入器单元测试。"""

from datetime import date
from pathlib import Path

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
