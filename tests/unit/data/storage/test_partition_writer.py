"""Parquet 分区写入器单元测试。"""

from datetime import date
from pathlib import Path

import polars as pl

from stock.data.storage.partition_writer import ParquetPartitionWriter


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
