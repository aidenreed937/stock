from datetime import date
from unittest.mock import MagicMock, PropertyMock, mock_open, patch

import polars as pl
import pytest

from stock.data.backfill import HistoricalBackfiller, main as backfill_main


def test_backfill_daily_multi_worker():
    mock_pipeline = MagicMock()
    mock_pipeline.fetcher.fetch_trade_cal.return_value = [
        date(2026, 8, 1),
        date(2026, 8, 2),
        date(2026, 9, 1),
        date(2026, 9, 2),
    ]
    mock_pipeline.store.has_curated.return_value = False
    mock_pipeline.sync_daily_bars.return_value = pl.DataFrame(
        {"symbol": ["000001.SZ"], "trade_date": ["2026-08-01"], "close": [10.0]}
    )

    with (
        patch("stock.data.backfill.create_pipeline", return_value=mock_pipeline),
        patch("stock.data.backfill.DataUpdateScheduler.is_data_ready", return_value=True),
    ):
        backfiller = HistoricalBackfiller(data_source="tushare", endpoint="daily")
        summary = backfiller.backfill_range(
            date(2026, 8, 1), date(2026, 9, 2), max_workers=2
        )
        assert summary["open_days"] == 4
        assert summary["synced_days"] == 4


def test_backfill_non_daily_single_request():
    mock_pipeline = MagicMock()
    mock_pipeline.fetcher.fetch_trade_cal.return_value = [date(2026, 8, 1)]
    mock_pipeline.sync_daily_bars.return_value = pl.DataFrame(
        {"symbol": ["CPIAUCSL"], "trade_date": ["2026-08-01"], "value": [300.0]}
    )

    with (
        patch("stock.data.backfill.create_pipeline", return_value=mock_pipeline),
        patch.object(
            HistoricalBackfiller, "frequency", new_callable=PropertyMock
        ) as mock_freq,
    ):
        mock_freq.return_value = "monthly"

        backfiller = HistoricalBackfiller(data_source="tushare", endpoint="cpi")
        summary = backfiller.backfill_range(date(2026, 1, 1), date(2026, 8, 1))

        assert summary["synced_days"] == 1
        mock_pipeline.sync_daily_bars.assert_called_once_with(
            symbol="cpi",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 8, 1),
            use_raw_cache=True,
            force_refresh=False,
        )


def test_backfill_cli_main(monkeypatch):
    import sys

    mock_summary = {
        "total_days": 10,
        "open_days": 5,
        "synced_days": 5,
        "skipped_days": 0,
        "failed_days": 0,
    }

    mock_backfiller = MagicMock()
    mock_backfiller.backfill_range.return_value = mock_summary

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "backfill",
            "--start",
            "2026-08-01",
            "--end",
            "2026-08-10",
            "--data-source",
            "tushare",
            "--endpoint",
            "daily",
            "--symbol",
            "000001.SZ",
            "--max-workers",
            "2",
        ],
    )

    with patch("stock.data.backfill.HistoricalBackfiller", return_value=mock_backfiller):
        backfill_main()
        mock_backfiller.backfill_range.assert_called_once()


def test_backfill_cli_config_load(monkeypatch):
    import sys
    from datetime import date

    mock_summary = {
        "total_days": 10,
        "open_days": 5,
        "synced_days": 5,
        "skipped_days": 0,
        "failed_days": 0,
    }

    mock_backfiller = MagicMock()
    mock_backfiller.backfill_range.return_value = mock_summary

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "backfill",
            "--config",
            "dummy_config.yaml",
        ],
    )

    yaml_content = """
backfill:
  default_start_date: "2026-08-01"
  default_end_date: "2026-08-10"
  default_data_source: "tushare"
  default_endpoint: "daily"
  default_symbol: "000001.SZ"
  max_workers: 3
"""

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=yaml_content)),
        patch("stock.data.backfill.HistoricalBackfiller", return_value=mock_backfiller),
    ):
        backfill_main()
        mock_backfiller.backfill_range.assert_called_once_with(
            date(2026, 8, 1), date(2026, 8, 10), force_refresh=False, max_workers=3
        )
