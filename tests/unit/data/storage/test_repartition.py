from datetime import date
import polars as pl

from stock.data.ops.repartition import repartition_all_curated, repartition_dataset


def test_repartition_all_curated(tmp_path):
    # 1. Non-existent directory
    repartition_all_curated(str(tmp_path / "non_existent"))

    # 2. Empty directory
    curated_dir = tmp_path / "curated"
    curated_dir.mkdir()
    repartition_all_curated(str(curated_dir))


def test_repartition_dataset_uses_report_end_date_and_preserves_backup(tmp_path) -> None:
    curated_dir = tmp_path / "curated"
    legacy_path = (
        curated_dir
        / "tushare"
        / "market=CN"
        / "income"
        / "year=2026"
        / "month=08"
        / "data.parquet"
    )
    legacy_path.parent.mkdir(parents=True)
    pl.DataFrame(
        {
            "symbol": ["600519.SH", "600519.SH"],
            "end_date": ["20240331", "20240630"],
            "revenue": [1.0, 2.0],
            "data_source": ["tushare", "tushare"],
            "market": ["CN", "CN"],
        }
    ).write_parquet(legacy_path)

    result = repartition_dataset(str(curated_dir), "tushare", "income")

    assert result == {
        "source_files": 1,
        "source_rows": 2,
        "output_files": 2,
        "output_rows": 2,
    }
    assert legacy_path.with_suffix(".bak.parquet").exists()
    assert not legacy_path.exists()
    march_path = (
        curated_dir
        / "tushare"
        / "market=CN"
        / "income"
        / "year=2024"
        / "month=03"
        / "data.parquet"
    )
    june_path = march_path.with_name("data.parquet").parents[1] / "month=06" / "data.parquet"
    assert pl.read_parquet(march_path)["end_date"].to_list() == ["20240331"]
    assert pl.read_parquet(june_path)["end_date"].to_list() == ["20240630"]

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
