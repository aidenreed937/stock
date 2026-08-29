from unittest.mock import MagicMock, patch

import polars as pl

from stock_cli.main import main


def test_main_execution_flow():
    """测试 main 主流程执行。"""
    mock_df = pl.DataFrame(
        {
            "symbol": ["000001.SZ"],
            "trade_date": ["2026-08-10"],
            "open": [10.0],
            "high": [10.5],
            "low": [9.8],
            "close": [10.2],
            "volume": [1000.0],
            "data_source": ["tushare"],
        }
    )

    with (
        patch("stock_cli.main.settings") as mock_settings,
        patch("stock_strategy.application.data_settings") as mock_data_settings,
        patch("stock_strategy.application.load_data_config") as mock_load_data_config,
        patch("stock_strategy.application.load_strategy_config") as mock_load_config,
        patch("stock_strategy.application.DataCatalog") as mock_catalog_cls,
        patch("stock_strategy.application.StrategyRunner") as mock_runner_cls,
    ):
        mock_settings.app_name = "StockApp"
        mock_settings.environment = "test"
        mock_data_settings.data_source_mode = "tushare"
        mock_data_config = MagicMock()
        mock_data_config.default_source_mode = "tushare"
        mock_data_config.backfill.default_start_date = "today-30d"
        mock_data_config.backfill.default_end_date = "today"
        mock_load_data_config.return_value = mock_data_config

        mock_config = MagicMock()
        mock_config.name = "TestStrategy"
        mock_config.version = "1.0"
        mock_config.universe.all_symbols = ["000001.SZ"]
        mock_load_config.return_value = mock_config

        mock_catalog_inst = MagicMock()
        mock_catalog_inst.data_source = "tushare"
        mock_catalog_inst.load_bars.return_value = mock_df
        mock_catalog_cls.return_value = mock_catalog_inst

        mock_runner_inst = MagicMock()
        mock_report = MagicMock()
        mock_report.to_dict.return_value = {"signals": 1}
        mock_runner_inst.run.return_value = mock_report
        mock_runner_cls.return_value = mock_runner_inst

        main()

        mock_catalog_cls.assert_called_once_with(data_source="tushare")
        mock_runner_inst.run.assert_called_once()
