from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, mock_open, patch

import polars as pl
import pytest

from stock_cli.backfill import (
    main as backfill_main,
)
from stock_data.pipeline.backfill import (
    HistoricalBackfiller,
)


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
        patch("stock_data.pipeline.backfill.create_pipeline", return_value=mock_pipeline),
        patch(
            "stock_data.pipeline.backfill.DataUpdateScheduler.get_trading_days",
            return_value=(
                date(2026, 8, 1),
                date(2026, 8, 2),
                date(2026, 9, 1),
                date(2026, 9, 2),
            ),
        ),
        patch("stock_data.pipeline.backfill.DataUpdateScheduler.is_data_ready", return_value=True),
    ):
        backfiller = HistoricalBackfiller(data_source="tushare", endpoint="stock_daily_bar")
        summary = backfiller.backfill_range(date(2026, 8, 1), date(2026, 9, 2), max_workers=2)
        assert summary["open_days"] == 4
        assert summary["synced_days"] == 4


def test_backfill_non_daily_single_request():
    mock_pipeline = MagicMock()
    mock_pipeline.fetcher.fetch_trade_cal.return_value = [date(2026, 8, 1)]
    mock_pipeline.sync_daily_bars.return_value = pl.DataFrame(
        {"symbol": ["CPIAUCSL"], "trade_date": ["2026-08-01"], "value": [300.0]}
    )

    with (
        patch("stock_data.pipeline.backfill.create_pipeline", return_value=mock_pipeline),
        patch.object(HistoricalBackfiller, "frequency", new_callable=PropertyMock) as mock_freq,
    ):
        mock_freq.return_value = "monthly"

        backfiller = HistoricalBackfiller(data_source="tushare", endpoint="cn_cpi")
        summary = backfiller.backfill_range(date(2026, 1, 1), date(2026, 8, 1))

        assert summary["synced_days"] == 1
        mock_pipeline.sync_daily_bars.assert_called_once_with(
            symbol="cn_cpi",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 8, 1),
            use_raw_cache=True,
            force_refresh=False,
        )


def test_backfill_rejects_unknown_public_task() -> None:
    with pytest.raises(ValueError, match="不是已注册的项目任务名"):
        HistoricalBackfiller(data_source="tushare", endpoint="not_a_task")


def test_backfill_per_symbol_without_symbol_does_not_use_endpoint_as_symbol() -> None:
    mock_pipeline = MagicMock()
    mock_pipeline.sync_daily_bars.return_value = pl.DataFrame(
        {"symbol": ["000300.SH"], "trade_date": ["2026-08-01"], "close": [4000.0]}
    )

    with patch("stock_data.pipeline.backfill.create_pipeline", return_value=mock_pipeline):
        backfiller = HistoricalBackfiller(data_source="tushare", endpoint="index_daily_bar")
        summary = backfiller.backfill_range(date(2026, 8, 1), date(2026, 8, 1))

    assert summary["synced_days"] == 1
    mock_pipeline.sync_daily_bars.assert_called_once_with(
        symbol="",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 1),
        use_raw_cache=True,
        force_refresh=False,
    )


def test_backfill_financial_statement_ignores_symbol_and_uses_report_period() -> None:
    mock_pipeline = MagicMock()
    mock_pipeline.sync_daily_bars.return_value = pl.DataFrame(
        {"ts_code": ["000001.SZ"], "end_date": ["20260331"]}
    )

    with patch("stock_data.pipeline.backfill.create_pipeline", return_value=mock_pipeline):
        backfiller = HistoricalBackfiller(
            data_source="tushare",
            endpoint="income",
            symbol="000001.SZ",
        )
        summary = backfiller.backfill_range(date(2026, 1, 1), date(2026, 3, 31), max_workers=4)

    assert summary["synced_days"] == 1
    mock_pipeline.sync_daily_bars.assert_called_once_with(
        symbol="",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 3, 31),
        use_raw_cache=True,
        force_refresh=False,
        max_workers=4,
    )


def test_backfill_per_symbol_all_dates_skipped() -> None:
    mock_pipeline = MagicMock()
    mock_pipeline.fetcher.fetch_trade_cal.return_value = [
        date(2026, 8, 3),
        date(2026, 8, 4),
    ]
    mock_pipeline.store.has_curated.return_value = True
    mock_pipeline.raw_store.has_raw.return_value = True

    with patch("stock_data.pipeline.backfill.create_pipeline", return_value=mock_pipeline):
        backfiller = HistoricalBackfiller(
            data_source="yfinance",
            endpoint="stock_daily_bar",
            symbol="AAPL",
        )
        summary = backfiller.backfill_range(date(2026, 8, 3), date(2026, 8, 4))

    assert summary == {
        "total_days": 2,
        "open_days": 2,
        "synced_days": 0,
        "skipped_days": 2,
        "failed_days": 0,
    }
    mock_pipeline.sync_daily_bars.assert_not_called()


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
            "stock_daily_bar",
            "--symbol",
            "000001.SZ",
            "--max-workers",
            "2",
        ],
    )

    with patch("stock_data.pipeline.backfill.HistoricalBackfiller", return_value=mock_backfiller):
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
  default_endpoint: "stock_daily_bar"
  default_symbol: "000001.SZ"
  max_workers: 3
"""

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=yaml_content)),
        patch("stock_data.pipeline.backfill.HistoricalBackfiller", return_value=mock_backfiller),
    ):
        backfill_main()
        mock_backfiller.backfill_range.assert_called_once_with(
            date(2026, 8, 1), date(2026, 8, 10), force_refresh=False, max_workers=3
        )


def test_tushare_financial_backfill_plans_one_all_market_period_task() -> None:
    from stock_data.pipeline.planner import BackfillPlanner

    data_cfg = SimpleNamespace(watchlists=SimpleNamespace(tushare=SimpleNamespace()))
    tasks = BackfillPlanner.plan_tasks(
        data_source="tushare",
        endpoints=["income"],
        symbol="000001.SZ",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 6, 30),
        start_specified=True,
        data_cfg=data_cfg,
    )

    assert len(tasks) == 1
    assert tasks[0].symbol == ""
    assert tasks[0].fetch_mode == "per_period"


def test_load_curated_symbol_pool_with_ts_code_column() -> None:
    from stock_data.pipeline.backfill import _load_curated_symbol_pool

    mock_store = MagicMock()
    mock_store.query_dataset.return_value = pl.DataFrame(
        {
            "ts_code": ["000001.SZ", "600519.SH", None],
            "name": ["平安银行", "贵州茅台", "空值"],
        }
    )

    with patch("stock_data.storage.duckdb_store.DuckDBMarketStore", return_value=mock_store):
        symbols = _load_curated_symbol_pool("tushare", "stock_basic")
        assert symbols == ["000001.SZ", "600519.SH"]


def test_planner_watchlist_on_per_day_endpoint_preserves_full_market() -> None:
    from stock_data.pipeline.planner import BackfillPlanner

    data_cfg = MagicMock()
    data_cfg.watchlists.tushare.stocks = ["600519.SH", "000001.SZ"]
    data_cfg.watchlists.tushare.all_symbols = ["600519.SH", "000001.SZ"]
    data_cfg.source_endpoint_supports = {}

    tasks = BackfillPlanner.plan_tasks(
        data_source="tushare",
        endpoints=["stock_daily_bar", "fund_daily"],
        symbol="watchlist",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 10),
        start_specified=True,
        data_cfg=data_cfg,
    )

    stock_tasks = [t for t in tasks if t.endpoint == "stock_daily_bar"]
    fund_tasks = [t for t in tasks if t.endpoint == "fund_daily"]

    # stock_daily_bar 是 per_day 模式，应保持 symbol=""（全市场）
    assert len(stock_tasks) == 1
    assert stock_tasks[0].symbol == ""

    # fund_daily 是 per_symbol 模式，允许展开 watchlist 基金
    assert len(fund_tasks) >= 1


def test_planner_expands_single_sync_index_bar_watchlist() -> None:
    from stock_data.pipeline.planner import BackfillPlanner

    watchlist = SimpleNamespace(
        stocks=["600519.SH"],
        indices=["000300.SH", "399006.SZ"],
        funds=[],
        all_symbols=["600519.SH", "000300.SH", "399006.SZ"],
        get_base_date=lambda _symbol: None,
    )
    data_cfg = SimpleNamespace(watchlists=SimpleNamespace(tushare=watchlist))

    tasks = BackfillPlanner.plan_tasks(
        data_source="tushare",
        endpoints=["index_daily_bar"],
        symbol="watchlist",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 10),
        start_specified=True,
        data_cfg=data_cfg,
    )

    assert [task.symbol for task in tasks] == ["000300.SH", "399006.SZ"]
