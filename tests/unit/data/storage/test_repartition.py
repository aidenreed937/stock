from datetime import date
import polars as pl

from stock.data.storage.repartition_tool import repartition_all_curated


def test_repartition_all_curated(tmp_path):
    # 1. Non-existent directory
    repartition_all_curated(str(tmp_path / "non_existent"))

    # 2. Empty directory
    curated_dir = tmp_path / "curated"
    curated_dir.mkdir()
    repartition_all_curated(str(curated_dir))

    # 3. Create dummy file
    file_dir = curated_dir / "tushare" / "market=CN" / "daily_bar"
    file_dir.mkdir(parents=True)
    df = pl.DataFrame({
        "symbol": ["TEST.SH"],
        "trade_date": [date(2026, 1, 1)],
        "open": [10.0],
        "high": [10.0],
        "low": [10.0],
        "close": [10.0],
        "volume": [100.0],
        "amount": [1000.0],
        "data_source": ["tushare"],
        "market": ["CN"],
        "exchange": ["SSE"],
        "currency": ["CNY"],
        "adjustment": ["raw"],
        "schema_version": ["v1"],
    })
    df.write_parquet(file_dir / "data.parquet")

    repartition_all_curated(str(curated_dir))
