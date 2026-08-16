"""stock_daily_bar RAW 重放器测试。"""

import json
from datetime import date
from pathlib import Path

import polars as pl

from stock.data.cleaner.bar_cleaner import BarDataCleaner
from stock.data.ops.rebuild_stock_daily_bar import rebuild_stock_daily_bar
from stock.data.pipeline import MarketDataPipeline
from stock.data.storage.duckdb_store import DuckDBMarketStore
from stock.data.storage.raw_store import RawDataStorage


def _write_inputs(root: Path, stock_basic: Path) -> tuple[Path, Path]:
    raw_root = root / "raw" / "tushare" / "market=CN" / "stock_daily_bar"
    curated_root = root / "curated" / "tushare" / "market=CN" / "stock_daily_bar"
    raw_partition = raw_root / "year=2026" / "month=08"
    raw_partition.mkdir(parents=True)
    curated_root.mkdir(parents=True)

    pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000001.SZ", "000002.SZ"],
            "trade_date": [date(2026, 8, 4), date(2026, 8, 5), date(2026, 8, 5)],
            "open": [10.0, 10.0, 20.0],
            "high": [10.5, 10.5, 20.5],
            "low": [9.5, 9.5, 19.5],
            "close": [10.0, 10.0, 20.0],
            "vol": [100.0, 100.0, 100.0],
            "amount": [100.0, 100.0, 200000.0],
            "source_unit_note": [
                "native unit: thousand yuan",
                "native unit: thousand yuan",
                "amount is normalized to yuan",
            ],
            "source_scope": ["legacy", "legacy", "legacy"],
        }
    ).write_parquet(raw_partition / "data.parquet")

    pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000002.SZ"],
            "list_date": ["20260805", "20200101"],
        }
    ).write_parquet(stock_basic)
    return raw_root, curated_root


def test_rebuild_stock_daily_bar_stages_and_validates_without_apply(tmp_path: Path) -> None:
    stock_basic = tmp_path / "stock_basic.parquet"
    raw_root, curated_root = _write_inputs(tmp_path, stock_basic)
    staging_root = tmp_path / "staging"
    quarantine_root = tmp_path / "quarantine"

    report = rebuild_stock_daily_bar(
        raw_root,
        curated_root,
        stock_basic_path=stock_basic,
        temp_root=staging_root,
        quarantine_root=quarantine_root,
    )

    assert report["accepted"] is True
    assert report["applied"] is False
    assert report["raw_rows"] == 3
    assert report["pre_listing_rows"] == 1
    assert report["output_rows"] == 2
    assert report["ratio_bad_days"] == 0
    assert not (curated_root / "year=2026" / "month=08" / "data.parquet").exists()
    assert Path(report["quarantine_path"]).exists()
    staged = pl.read_parquet(
        staging_root
        / "curated"
        / "tushare"
        / "market=CN"
        / "stock_daily_bar"
        / "year=2026"
        / "month=08"
        / "data.parquet"
    )
    assert staged["amount"].to_list() == [100000.0, 200000.0]
    assert "source_scope" not in staged.columns
    assert "scope_note" not in staged.columns


def test_rebuild_stock_daily_bar_apply_writes_backup_and_final_report(tmp_path: Path) -> None:
    stock_basic = tmp_path / "stock_basic.parquet"
    raw_root, curated_root = _write_inputs(tmp_path, stock_basic)
    old_partition = curated_root / "year=2026" / "month=08"
    old_partition.mkdir(parents=True)
    pl.DataFrame({"legacy": [1]}).write_parquet(old_partition / "data.parquet")
    staging_root = tmp_path / "staging"
    backup_root = tmp_path / "audit"
    quarantine_root = tmp_path / "quarantine"

    report = rebuild_stock_daily_bar(
        raw_root,
        curated_root,
        stock_basic_path=stock_basic,
        temp_root=staging_root,
        quarantine_root=quarantine_root,
        backup_root=backup_root,
        apply=True,
    )

    assert report["accepted"] is True
    assert report["applied"] is True
    assert Path(report["backup_root"]).exists()
    assert (curated_root / "year=2026" / "month=08" / "data.parquet").exists()
    report_data = json.loads((staging_root / "rebuild_report.json").read_text(encoding="utf-8"))
    assert report_data["applied"] is True
    assert report_data["backup_root"] == report["backup_root"]


def test_online_pipeline_and_rebuild_share_bar_normalization(tmp_path: Path) -> None:
    raw_frame = pl.DataFrame(
        {
            "ts_code": ["000001.SZ", "000001.SZ"],
            "trade_date": ["20260805", "20260806"],
            "open": [10.0, 10.0],
            "high": [10.5, 10.5],
            "low": [9.5, 9.5],
            "close": [10.0, 10.0],
            "vol": [100.0, 100.0],
            # 第一行是千元，第二行是元；两行都没有依赖月份的单位标记。
            "amount": [100.0, 100000.0],
        }
    )

    class StubFetcher:
        def fetch_daily_bars_df(self, symbol, start_date, end_date, endpoint="daily", **kwargs):
            return raw_frame

    stock_basic = tmp_path / "stock_basic.parquet"
    pl.DataFrame({"symbol": ["000001.SZ"], "list_date": ["20260805"]}).write_parquet(stock_basic)

    raw_storage = RawDataStorage(base_dir=tmp_path / "raw")
    online = MarketDataPipeline(
        fetcher=StubFetcher(),
        cleaner=BarDataCleaner({"000001.SZ": date(2026, 8, 5)}),
        store=DuckDBMarketStore(storage_dir=tmp_path / "online-curated"),
        raw_store=raw_storage,
        data_source="tushare",
        endpoint="stock_daily_bar",
    ).sync_daily_bars("000001.SZ", date(2026, 8, 5), date(2026, 8, 6))

    rebuild_curated = tmp_path / "rebuild-curated"
    report = rebuild_stock_daily_bar(
        tmp_path / "raw" / "tushare" / "market=CN" / "stock_daily_bar",
        rebuild_curated,
        stock_basic_path=stock_basic,
        temp_root=tmp_path / "staging",
    )

    assert report["accepted"] is True
    replayed = pl.read_parquet(
        Path(report["output_root"]) / "year=2026" / "month=08" / "data.parquet"
    )
    compare_columns = [
        "symbol",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "data_source",
        "source_endpoint",
        "market",
        "exchange",
        "currency",
        "adjustment",
        "schema_version",
    ]
    assert (
        replayed.select(compare_columns)
        .sort("trade_date")
        .equals(online.select(compare_columns).sort("trade_date"))
    )
    assert replayed["amount"].to_list() == [100000.0, 100000.0]
    assert replayed["volume"].to_list() == [10000.0, 10000.0]
