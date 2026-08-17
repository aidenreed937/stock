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
        patch("stock_cli.main.data_settings") as mock_data_settings,
        patch("stock_cli.main.load_strategy_config") as mock_load_config,
        patch("stock_cli.main.create_pipeline") as mock_create_pipeline,
        patch("stock_cli.main.StrategyRunner") as mock_runner_cls,
    ):
        mock_settings.app_name = "StockApp"
        mock_settings.environment = "test"
        mock_data_settings.data_source_mode = "tushare"

        mock_config = MagicMock()
        mock_config.name = "TestStrategy"
        mock_config.version = "1.0"
        mock_config.universe.all_symbols = ["000001.SZ"]
        mock_load_config.return_value = mock_config

        mock_pipeline_inst = MagicMock()
        mock_pipeline_inst.data_source = "tushare"
        mock_pipeline_inst.sync_daily_bars.return_value = mock_df
        mock_pipeline_inst.store.query_history.return_value = mock_df
        mock_create_pipeline.return_value = mock_pipeline_inst

        mock_runner_inst = MagicMock()
        mock_report = MagicMock()
        mock_report.to_dict.return_value = {"signals": 1}
        mock_runner_inst.run.return_value = mock_report
        mock_runner_cls.return_value = mock_runner_inst

        main()

        mock_create_pipeline.assert_called_once_with("tushare", endpoint="stock_daily_bar")
        mock_pipeline_inst.sync_daily_bars.assert_called_once()
        mock_runner_inst.run.assert_called_once()
