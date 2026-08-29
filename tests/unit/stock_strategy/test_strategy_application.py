"""测试 stock_strategy.application 经典单策略运行 Facade。"""

from datetime import date
from unittest.mock import MagicMock, patch

import polars as pl

from stock_strategy.application import parse_config_date, run_strategy_application


def test_parse_config_date() -> None:
    today = date(2026, 8, 29)
    assert parse_config_date("today", today) == date(2026, 8, 29)
    assert parse_config_date("today-30d", today) == date(2026, 7, 30)
    assert parse_config_date("2026-01-01", today) == date(2026, 1, 1)
    assert parse_config_date("", today) is None


@patch("stock_strategy.application.DataCatalog")
@patch("stock_strategy.application.load_data_config")
@patch("stock_strategy.application.load_strategy_config")
def test_run_strategy_application_mock(
    mock_load_strat: MagicMock,
    mock_load_data: MagicMock,
    mock_catalog_cls: MagicMock,
) -> None:
    strat_cfg = MagicMock()
    strat_cfg.name = "test_strat"
    strat_cfg.version = "1.0"
    strat_cfg.universe.all_symbols = ["000001.SZ"]
    mock_load_strat.return_value = strat_cfg

    data_cfg = MagicMock()
    data_cfg.default_source_mode = "mock"
    data_cfg.backfill.default_start_date = "today-10d"
    data_cfg.backfill.default_end_date = "today"
    mock_load_data.return_value = data_cfg

    mock_catalog = MagicMock()
    mock_catalog.data_source = "mock"
    mock_catalog.load_bars.return_value = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 29)],
            "symbol": ["000001.SZ"],
            "close": [10.0],
        }
    )
    mock_catalog_cls.return_value = mock_catalog

    with patch("stock_strategy.application.StrategyRunner") as mock_runner_cls:
        mock_runner = MagicMock()
        mock_report = MagicMock()
        mock_runner.run.return_value = mock_report
        mock_runner_cls.return_value = mock_runner

        res = run_strategy_application()
        assert res.strategy_name == "test_strat"
        assert res.strategy_version == "1.0"
        assert res.query_rows == 1
        assert res.report == mock_report
