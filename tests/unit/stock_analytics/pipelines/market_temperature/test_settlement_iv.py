"""市场温度计期权结算价 IV 代理派生温度测试。"""

from datetime import date, timedelta
from pathlib import Path

import polars as pl

from stock_analytics.features.store import FeatureStore
from stock_analytics.pipelines.market_temperature.derived import (
    _metric_row,
    _percentile_metric_row,
)
from stock_analytics.pipelines.market_temperature.derived_settlement_iv import settlement_iv_rows


def _write_iv_mart(tmp_path: Path, days: list[date]) -> None:
    store = FeatureStore(mart_dir=tmp_path / "mart")
    records = []
    for day in days:
        for underlying in ("000300.SH", "510050.SH"):
            records.append(
                {
                    "trade_date": day,
                    "underlying_symbol": underlying,
                    "settlement_iv_proxy_median": 0.18 + (day - days[0]).days * 0.02,
                    "settlement_iv_proxy_put_call_skew": -0.01 + (day - days[0]).days * 0.01,
                    "settlement_iv_proxy_valid_count": 80,
                }
            )
    store.save_domain_mart(
        "settlement_iv_proxy_daily",
        pl.DataFrame(records),
        keys=["trade_date", "underlying_symbol"],
        date_column="trade_date",
    )


def test_settlement_iv_rows_outputs_inverse_iv_and_skew_temperatures(tmp_path: Path) -> None:
    days = [date(2026, 8, 10) + timedelta(days=offset) for offset in range(5)]
    _write_iv_mart(tmp_path, days)

    rows = settlement_iv_rows(date(2026, 8, 14), tmp_path, _metric_row, _percentile_metric_row)

    iv = next(row for row in rows if row["metric_id"] == "settlement_iv_proxy_temperature")
    skew = next(row for row in rows if row["metric_id"] == "settlement_iv_proxy_skew_temperature")
    assert iv["status"] == "ok"
    assert skew["status"] == "ok"
    assert iv["dimension"] == "sentiment"
    assert iv["unit"] == "temperature"
    assert iv["value_float"] == 0.0
    assert skew["value_float"] == 0.0
    assert "反" in iv["note"]
    assert "非标准" in iv["note"]


def test_settlement_iv_rows_does_not_use_future_rows(tmp_path: Path) -> None:
    days = [date(2026, 8, 10) + timedelta(days=offset) for offset in range(5)]
    _write_iv_mart(tmp_path, days)

    rows = settlement_iv_rows(date(2026, 8, 11), tmp_path, _metric_row, _percentile_metric_row)

    iv = next(row for row in rows if row["metric_id"] == "settlement_iv_proxy_temperature")
    skew = next(row for row in rows if row["metric_id"] == "settlement_iv_proxy_skew_temperature")
    assert iv["status"] == "ok"
    assert iv["value_float"] == 0.0
    assert skew["status"] == "ok"


def test_settlement_iv_rows_returns_insufficient_when_mart_missing(tmp_path: Path) -> None:
    rows = settlement_iv_rows(date(2026, 8, 14), tmp_path, _metric_row, _percentile_metric_row)

    assert len(rows) >= 1
    iv = next(row for row in rows if row["metric_id"] == "settlement_iv_proxy_temperature")
    assert iv["status"] == "insufficient"
    assert iv["value_float"] is None
    assert "不可用" in iv["note"]


def test_settlement_iv_rows_returns_insufficient_when_fields_missing(tmp_path: Path) -> None:
    store = FeatureStore(mart_dir=tmp_path / "mart")
    store.save_domain_mart(
        "settlement_iv_proxy_daily",
        pl.DataFrame(
            {
                "trade_date": [date(2026, 8, 14)],
                "underlying_symbol": ["000300.SH"],
                "settlement_iv_proxy_median": [0.22],
                "settlement_iv_proxy_valid_count": [80],
            }
        ),
        keys=["trade_date", "underlying_symbol"],
        date_column="trade_date",
    )

    rows = settlement_iv_rows(date(2026, 8, 14), tmp_path, _metric_row, _percentile_metric_row)

    iv = next(row for row in rows if row["metric_id"] == "settlement_iv_proxy_temperature")
    assert iv["status"] == "insufficient"
    assert "字段" in iv["note"]
