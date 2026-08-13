"""QualityGate 单元测试。"""

from datetime import date, datetime, timezone
import polars as pl

from stock.data.quality.gate import QualityGate, run_quality_gate


def test_quality_gate_on_valid_data(tmp_path) -> None:
    now_utc = datetime.now(timezone.utc)
    target_dir = tmp_path / "tushare" / "market=CN" / "stock_daily_bar" / "year=2026" / "month=08"
    target_dir.mkdir(parents=True, exist_ok=True)

    # 构造标准合格数据: volume为股 (1000.0), amount为元 (10500.0), close为10.5
    # amount / (volume * close) = 10500 / 10500 = 1.0
    valid_df = pl.DataFrame(
        {
            "symbol": ["000001.SZ"],
            "trade_date": [date(2026, 8, 1)],
            "open": [10.0],
            "high": [11.0],
            "low": [9.5],
            "close": [10.5],
            "volume": [1000.0],
            "amount": [10500.0],
            "data_source": ["tushare"],
            "source_endpoint": ["stock_daily_bar"],
            "market": ["CN"],
            "exchange": ["SZSE"],
            "currency": ["CNY"],
            "adjustment": ["raw"],
            "schema_version": ["v2"],
            "updated_at": [now_utc],
        }
    )
    valid_df.write_parquet(target_dir / "data.parquet")

    gate = QualityGate(tmp_path)
    results = gate.validate_all()
    assert all(results.values())
    assert run_quality_gate(tmp_path)


def test_quality_gate_fails_on_unit_mismatch(tmp_path) -> None:
    now_utc = datetime.now(timezone.utc)
    target_dir = tmp_path / "tushare" / "market=CN" / "stock_daily_bar" / "year=2026" / "month=08"
    target_dir.mkdir(parents=True, exist_ok=True)

    # 构造单位错配数据: volume 还是手 (10.0), amount 为元 (10500.0), ratio = 100.0
    bad_df = pl.DataFrame(
        {
            "symbol": ["000001.SZ"] * 12,
            "trade_date": [date(2026, 8, 1)] * 12,
            "open": [10.0] * 12,
            "high": [11.0] * 12,
            "low": [9.5] * 12,
            "close": [10.5] * 12,
            "volume": [10.0] * 12,
            "amount": [10500.0] * 12,
            "data_source": ["tushare"] * 12,
            "source_endpoint": ["stock_daily_bar"] * 12,
            "market": ["CN"] * 12,
            "exchange": ["SZSE"] * 12,
            "currency": ["CNY"] * 12,
            "adjustment": ["raw"] * 12,
            "schema_version": ["v2"] * 12,
            "updated_at": [now_utc] * 12,
        }
    )
    bad_df.write_parquet(target_dir / "data.parquet")

    gate = QualityGate(tmp_path)
    assert not gate.assert_stock_daily_bar_units(gate._active_parquet_files())
    assert not run_quality_gate(tmp_path)
