import json
from datetime import date, datetime, timezone
from pathlib import Path

import polars as pl

from stock.data.audit.baseline import build_baseline
from stock.data.ops.migration import migrate_parquet
from stock.data.audit.backfill_acceptance import accept_backfill
from stock.data.cleaner.bar_cleaner import BarDataCleaner
from stock.data.quality.quarantine import QuarantineStore
from stock.data.pipeline import MarketDataPipeline
from stock.exceptions import DataValidationError


def test_baseline_empty_directory(tmp_path: Path) -> None:
    result = build_baseline(str(tmp_path))
    assert result["files"] == []


def test_baseline_records_schema_hash_and_dates(tmp_path: Path) -> None:
    path = tmp_path / "daily.parquet"
    pl.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["2026-08-01"]}).write_parquet(path)
    output = tmp_path / "baseline.json"
    result = build_baseline(str(tmp_path), str(output))
    item = next(row for row in result["files"] if row["path"].endswith("daily.parquet"))
    assert item["rows"] == 1
    assert item["date_column"] == "trade_date"
    assert len(item["sha256"]) == 64
    assert json.loads(output.read_text(encoding="utf-8"))["files"]


def test_migration_dry_run_does_not_write(tmp_path: Path) -> None:
    path = tmp_path / "fund_basic.parquet"
    pl.DataFrame({"ts_code": ["A", "A"], "name": ["old", "new"]}).write_parquet(path)
    result = migrate_parquet(str(tmp_path))
    assert result["files_changed"] == 1
    assert len(pl.read_parquet(path)) == 2
    assert not path.with_suffix(".bak.parquet").exists()


def test_migration_apply_uses_registered_key_and_backup(tmp_path: Path) -> None:
    path = tmp_path / "fund_basic.parquet"
    pl.DataFrame({"ts_code": ["A", "A"], "name": ["old", "new"]}).write_parquet(path)
    result = migrate_parquet(str(tmp_path), apply=True)
    assert result["applied"] == 1
    assert len(pl.read_parquet(path)) == 1
    assert path.with_suffix(".bak.parquet").exists()


def test_migration_uses_curated_symbol_alias_for_ts_code_key(tmp_path: Path) -> None:
    path = tmp_path / "index_daily" / "year=2026" / "month=08" / "data.parquet"
    path.parent.mkdir(parents=True)
    pl.DataFrame({
        "symbol": ["A", "A", "B"],
        "trade_date": ["2026-08-01", "2026-08-01", "2026-08-01"],
        "close": [1.0, 2.0, 3.0],
    }).write_parquet(path)

    result = migrate_parquet(str(tmp_path), apply=True)

    assert result["rows_removed"] == 1
    output = pl.read_parquet(path)
    assert output.sort("symbol")["close"].to_list() == [2.0, 3.0]


def test_migration_prefers_newer_and_more_complete_record(tmp_path: Path) -> None:
    path = tmp_path / "index_daily" / "year=2026" / "month=08" / "data.parquet"
    path.parent.mkdir(parents=True)
    pl.DataFrame({
        "symbol": ["A", "A"],
        "trade_date": ["2026-08-01", "2026-08-01"],
        "pre_close": [None, 9.0],
        "updated_at": [None, "2026-08-12 18:00:00"],
    }).write_parquet(path)

    migrate_parquet(str(tmp_path), apply=True)

    output = pl.read_parquet(path)
    assert output["pre_close"].to_list() == [9.0]
    assert output["updated_at"].is_not_null().all()


def test_migration_deduplicates_fund_daily_adjustment_variants(tmp_path: Path) -> None:
    path = tmp_path / "fund_daily" / "year=2026" / "month=07" / "data.parquet"
    path.parent.mkdir(parents=True)
    pl.DataFrame(
        {
            "market": ["CN", "CN"],
            "symbol": ["159017.SZ", "159017.SZ"],
            "trade_date": ["2026-07-28", "2026-07-28"],
            "open": [0.897, 0.897],
            "high": [0.889, 0.911],
            "low": [0.901, 0.889],
            "close": [0.858, 0.858],
            "adjustment": ["normal", "raw"],
            "updated_at": [None, "2026-08-13 12:00:00"],
        }
    ).write_parquet(path)

    result = migrate_parquet(str(tmp_path), apply=True)

    assert result["rows_removed"] == 1
    output = pl.read_parquet(path)
    assert len(output) == 1
    assert output["adjustment"].to_list() == ["raw"]
    assert output["high"].to_list() == [0.911]


def test_migration_repairs_invalid_bar_quality_and_quarantines_rows(tmp_path: Path) -> None:
    path = tmp_path / "stock_daily_bar" / "year=2026" / "month=08" / "data.parquet"
    path.parent.mkdir(parents=True)
    pl.DataFrame(
        {
            "market": ["CN", "CN"],
            "symbol": ["AAA.SZ", "BBB.SZ"],
            "trade_date": ["2026-08-01", "2026-08-01"],
            "open": [10.0, 0.0],
            "high": [11.0, 0.0],
            "low": [9.0, 0.0],
            "close": [10.5, 1.0],
            "adjustment": ["raw", "normal"],
        }
    ).write_parquet(path)

    result = migrate_parquet(
        str(tmp_path),
        apply=True,
        repair_bar_quality=True,
        quarantine_root=tmp_path / "quarantine",
    )

    assert result["quality_files_changed"] == 1
    assert result["quality_rows_removed"] == 1
    assert len(pl.read_parquet(path)) == 1
    quarantined = pl.read_parquet(tmp_path / "quarantine" / "endpoint=stock_daily_bar" / "records.parquet")
    assert len(quarantined) == 1
    assert quarantined["symbol"].to_list() == ["BBB.SZ"]


def test_migration_handles_timezone_aware_updated_at(tmp_path: Path) -> None:
    path = tmp_path / "index_weight" / "year=2026" / "month=08" / "data.parquet"
    path.parent.mkdir(parents=True)
    pl.DataFrame({
        "index_code": ["I", "I"],
        "con_code": ["A", "A"],
        "trade_date": ["2026-08-01", "2026-08-01"],
        "weight": [1.0, 2.0],
        "updated_at": [
            datetime(2026, 8, 1, tzinfo=timezone.utc),
            datetime(2026, 8, 2, tzinfo=timezone.utc),
        ],
    }).write_parquet(path)

    result = migrate_parquet(str(tmp_path))

    assert result["rows_removed"] == 1


def test_migration_normalizes_mixed_identity_columns(tmp_path: Path) -> None:
    path = tmp_path / "daily_basic" / "year=2026" / "month=07" / "data.parquet"
    path.parent.mkdir(parents=True)
    pl.DataFrame(
        {
            "symbol": ["A", None],
            "ts_code": [None, "B"],
            "trade_date": ["2026-07-30", "2026-07-31"],
            "data_source": ["tushare", "tushare"],
        }
    ).write_parquet(path)

    result = migrate_parquet(str(tmp_path))

    assert result["schema_files_changed"] == 1
    assert result["rows_removed"] == 0


def test_migration_repairs_data_source_from_path(tmp_path: Path) -> None:
    path = tmp_path / "tushare" / "adj_factor" / "year=2026" / "month=08" / "data.parquet"
    path.parent.mkdir(parents=True)
    pl.DataFrame({"symbol": ["A"], "trade_date": ["2026-08-01"]}).write_parquet(path)

    migrate_parquet(str(tmp_path), apply=True, repair_lineage=True)

    output = pl.read_parquet(path)
    assert output["data_source"].to_list() == ["tushare"]


def test_migration_repairs_missing_lineage_columns(tmp_path: Path) -> None:
    path = tmp_path / "index_daily" / "year=2026" / "month=08" / "data.parquet"
    path.parent.mkdir(parents=True)
    pl.DataFrame({
        "symbol": ["A"],
        "trade_date": ["2026-08-01"],
        "data_source": ["tushare"],
    }).write_parquet(path)

    result = migrate_parquet(str(tmp_path), apply=True, repair_lineage=True)

    output = pl.read_parquet(path)
    assert result["lineage_files_changed"] == 1
    assert output["source_endpoint"].to_list() == ["index_daily"]
    assert output["request_id"].to_list() == ["legacy:index_daily:year=2026/month=08"]
    assert "updated_at" in output.columns


def test_backfill_acceptance_uses_curated_symbol_alias_for_ts_code_key(tmp_path: Path) -> None:
    curated = tmp_path / "index_daily"
    curated.mkdir()
    frame = pl.DataFrame({
        "symbol": ["A", "A", "B"],
        "trade_date": ["2026-08-01", "2026-08-01", "2026-08-01"],
        "data_source": ["tushare"] * 3,
        "source_endpoint": ["index_daily"] * 3,
        "request_id": ["r"] * 3,
        "updated_at": ["2026-08-01"] * 3,
    })
    frame.write_parquet(curated / "data.parquet")

    report = accept_backfill(str(tmp_path), "index_daily")

    assert report["duplicate_keys"] == 1
    assert report["status"] == "FAILED"


def test_backfill_acceptance_normalizes_mixed_symbol_key_aliases(tmp_path: Path) -> None:
    curated = tmp_path / "daily_basic"
    curated.mkdir()
    lineage = {
        "data_source": ["tushare"],
        "source_endpoint": ["daily_basic"],
        "request_id": ["r"],
        "updated_at": ["2026-08-01"],
    }
    pl.DataFrame({"ts_code": ["A"], "trade_date": ["2026-08-01"], **lineage}).write_parquet(
        curated / "legacy.parquet"
    )
    pl.DataFrame({"symbol": ["A"], "trade_date": ["2026-08-01"], **lineage}).write_parquet(
        curated / "normalized.parquet"
    )

    report = accept_backfill(str(tmp_path), "daily_basic")

    assert report["duplicate_keys"] == 1
    assert report["status"] == "FAILED"


def test_backfill_acceptance_normalizes_compact_boundary_dates(tmp_path: Path) -> None:
    curated = tmp_path / "adj_factor"
    curated.mkdir()
    pl.DataFrame(
        {
            "symbol": ["A", "A"],
            "trade_date": ["20260812", "20260813"],
            "adj_factor": [1.0, 1.1],
            "data_source": ["tushare", "tushare"],
            "source_endpoint": ["adj_factor", "adj_factor"],
            "request_id": ["r1", "r2"],
            "updated_at": ["2026-08-01", "2026-08-12"],
        }
    ).write_parquet(curated / "data.parquet")

    report = accept_backfill(
        str(tmp_path), "adj_factor", date(2026, 8, 12), date(2026, 8, 13)
    )

    assert report["missing_boundary_dates"] == []
    assert report["status"] == "PASSED"


def test_backfill_acceptance_fails_on_internal_daily_gap(tmp_path: Path) -> None:
    curated = tmp_path / "adj_factor"
    curated.mkdir()
    pl.DataFrame(
        {
            "symbol": ["A", "A"],
            "trade_date": ["20260812", "20260814"],
            "adj_factor": [1.0, 1.1],
            "data_source": ["tushare", "tushare"],
            "source_endpoint": ["adj_factor", "adj_factor"],
            "request_id": ["r1", "r2"],
            "updated_at": ["2026-08-12", "2026-08-14"],
        }
    ).write_parquet(curated / "data.parquet")

    report = accept_backfill(
        str(tmp_path), "adj_factor", date(2026, 8, 12), date(2026, 8, 14)
    )

    assert report["missing_dates"] == ["2026-08-13"]
    assert report["status"] == "FAILED"


def test_backfill_acceptance_filters_by_data_source(tmp_path: Path) -> None:
    target = tmp_path / "yfinance" / "market=US" / "stock_daily_bar"
    target.mkdir(parents=True)
    pl.DataFrame(
        {
            "symbol": ["AAPL"],
            "trade_date": ["2026-08-12"],
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [1.0],
            "data_source": ["yfinance"],
            "source_endpoint": ["history"],
            "request_id": ["r"],
            "updated_at": ["2026-08-12"],
        }
    ).write_parquet(target / "data.parquet")

    tushare_report = accept_backfill(str(tmp_path), "stock_daily_bar", data_source="tushare")
    yfinance_report = accept_backfill(str(tmp_path), "stock_daily_bar", data_source="yfinance")

    assert tushare_report["status"] == "FAILED"
    assert tushare_report["files"] == 0
    assert yfinance_report["status"] == "PASSED"
    assert yfinance_report["files"] == 1


def test_backfill_acceptance_handles_quarterly_report_periods(tmp_path: Path) -> None:
    curated = tmp_path / "income"
    curated.mkdir()
    pl.DataFrame(
        {
            "symbol": ["A", "A"],
            "end_date": ["20140331", "20260331"],
            "report_type": ["1", "1"],
            "data_source": ["tushare", "tushare"],
            "source_endpoint": ["income", "income"],
            "request_id": ["r1", "r2"],
            "updated_at": ["2026-08-01", "2026-08-12"],
        }
    ).write_parquet(curated / "data.parquet")

    report = accept_backfill(
        str(tmp_path), "income", date(2014, 1, 1), date(2026, 8, 12)
    )

    assert report["missing_boundary_dates"] == []
    assert report["source_lag"] is True
    assert report["status"] == "PASSED"


def test_backfill_acceptance_ignores_migration_backups(tmp_path: Path) -> None:
    curated = tmp_path / "index_daily"
    curated.mkdir()
    frame = pl.DataFrame({
        "symbol": ["A"],
        "trade_date": ["2026-08-01"],
        "data_source": ["tushare"],
        "source_endpoint": ["index_daily"],
        "request_id": ["r"],
        "updated_at": ["2026-08-01"],
    })
    frame.write_parquet(curated / "data.parquet")
    frame.vstack(frame).write_parquet(curated / "data.parquet.bak.parquet")

    report = accept_backfill(str(tmp_path), "index_daily")

    assert report["files"] == 1
    assert report["duplicate_keys"] == 0


def test_backfill_acceptance_passes_and_reports_duplicates(tmp_path: Path) -> None:
    curated = tmp_path / "stock_daily_bar"
    curated.mkdir()
    pl.DataFrame({
        "ts_code": ["A"], "trade_date": ["2026-08-01"], "open": [1.0], "high": [1.0],
        "low": [1.0], "close": [1.0], "data_source": ["tushare"],
        "source_endpoint": ["daily"], "request_id": ["r"], "updated_at": ["2026-08-01"],
    }).write_parquet(curated / "stock_daily_bar.parquet")
    report = accept_backfill(str(tmp_path), "stock_daily_bar")
    assert report["status"] == "PASSED"
    assert report["rows"] == 1


def test_backfill_acceptance_maps_daily_storage_alias(tmp_path: Path) -> None:
    curated = tmp_path / "stock_daily_bar"
    curated.mkdir()
    pl.DataFrame({
        "ts_code": ["A"], "trade_date": ["2026-08-01"], "open": [1.0], "high": [1.0],
        "low": [1.0], "close": [1.0], "data_source": ["tushare"],
        "source_endpoint": ["daily"], "request_id": ["r"], "updated_at": ["2026-08-01"],
    }).write_parquet(curated / "data.parquet")
    report = accept_backfill(str(tmp_path), "stock_daily_bar")
    assert report["status"] == "PASSED"
    assert report["files"] == 1


def test_backfill_acceptance_maps_date_to_trade_date(tmp_path: Path) -> None:
    curated = tmp_path / "shibor_lpr"
    curated.mkdir()
    pl.DataFrame({
        "symbol": ["shibor_lpr"], "trade_date": ["2026-08-01"], "1y": [2.0],
        "5y": [2.5], "data_source": ["tushare"], "source_endpoint": ["shibor_lpr"],
        "request_id": ["r"], "updated_at": ["2026-08-01"],
    }).write_parquet(curated / "data.parquet")
    report = accept_backfill(str(tmp_path), "shibor_lpr")
    assert report["status"] == "PASSED"


def test_backfill_acceptance_fails_when_curated_rows_drop_below_raw_ratio(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw"
    curated_root = tmp_path / "curated"
    (raw_root / "stock_daily_bar").mkdir(parents=True)
    (curated_root / "stock_daily_bar").mkdir(parents=True)

    raw_frame = pl.DataFrame(
        {
            "ts_code": ["A", "B", "C", "D"],
            "trade_date": ["20260801"] * 4,
        }
    )
    curated_frame = pl.DataFrame(
        {
            "symbol": ["A", "B"],
            "trade_date": ["2026-08-01"] * 2,
            "open": [1.0, 1.0],
            "high": [1.0, 1.0],
            "low": [1.0, 1.0],
            "close": [1.0, 1.0],
            "data_source": ["tushare", "tushare"],
            "source_endpoint": ["daily", "daily"],
            "request_id": ["r1", "r2"],
            "updated_at": ["2026-08-01", "2026-08-01"],
        }
    )
    raw_frame.write_parquet(raw_root / "stock_daily_bar" / "data.parquet")
    curated_frame.write_parquet(curated_root / "stock_daily_bar" / "data.parquet")

    report = accept_backfill(
        str(curated_root),
        "stock_daily_bar",
        raw_root=str(raw_root),
        min_raw_ratio=0.75,
    )

    assert report["raw_rows"] == 4
    assert report["curated_raw_ratio"] == 0.5
    assert report["raw_ratio_passed"] is False
    assert report["status"] == "FAILED"


def test_bar_cleaner_quarantines_rejected_rows(tmp_path: Path) -> None:
    frame = pl.DataFrame({"symbol": ["A", "B"], "trade_date": ["2026-08-01"] * 2, "open": [1.0, 0.0], "high": [1.0, 0.0], "low": [1.0, 0.0], "close": [1.0, 0.0]})
    cleaned = BarDataCleaner().clean_with_quarantine(
        frame,
        endpoint="stock_daily_bar",
        request_id="req",
        data_source="tushare",
        quarantine=QuarantineStore(tmp_path),
    )
    assert len(cleaned) == 1
    quarantined = pl.read_parquet(tmp_path / "endpoint=stock_daily_bar" / "records.parquet")
    assert quarantined["quarantine_reason"].to_list() == ["bar_validation_rejected"]


def test_endpoint_contract_rejects_duplicate_primary_keys() -> None:
    pipeline = object.__new__(MarketDataPipeline)
    pipeline.data_source = "tushare"
    pipeline.endpoint = "stock_daily_bar"
    frame = pl.DataFrame({"ts_code": ["A", "A"], "trade_date": ["2026-08-01"] * 2})
    try:
        pipeline._validate_endpoint_frame(frame, __import__("datetime").date(2026, 8, 1), __import__("datetime").date(2026, 8, 1))
    except DataValidationError:
        return
    raise AssertionError("duplicate primary keys must fail closed")
