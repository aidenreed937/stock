from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from stock.main import main


def test_main_with_mock_data_source():
    """测试 mock 数据源下的 main 主流程执行。"""
    mock_df = pl.DataFrame(
        {
            "symbol": ["000001.SZ"],
            "trade_date": ["2026-08-10"],
            "open": [10.0],
            "high": [10.5],
            "low": [9.8],
            "close": [10.2],
            "volume": [1000.0],
            "data_source": ["mock"],
        }
    )

    with (
        patch("stock.main.settings") as mock_settings,
        patch("stock.main.load_strategy_config") as mock_load_config,
        patch("stock.main.MarketDataPipeline") as mock_pipeline_cls,
        patch("stock.main.StrategyRunner") as mock_runner_cls,
    ):
        mock_settings.app_name = "StockApp"
        mock_settings.environment = "test"
        mock_settings.data_source_mode = "mock"

        mock_config = MagicMock()
        mock_config.name = "TestStrategy"
        mock_config.version = "1.0"
        mock_config.universe.all_symbols = ["000001.SZ"]
        mock_load_config.return_value = mock_config

        mock_pipeline_inst = MagicMock()
        mock_pipeline_inst.data_source = "mock"
        mock_pipeline_inst.sync_daily_bars.return_value = mock_df
        mock_pipeline_inst.store.query_history.return_value = mock_df
        mock_pipeline_cls.return_value = mock_pipeline_inst

        mock_runner_inst = MagicMock()
        mock_report = MagicMock()
        mock_report.to_dict.return_value = {"signals": 1}
        mock_runner_inst.run.return_value = mock_report
        mock_runner_cls.return_value = mock_runner_inst

        main()

        mock_pipeline_inst.sync_daily_bars.assert_called_once()
        mock_runner_inst.run.assert_called_once()


def test_main_with_tushare_data_source():
    """测试 tushare 数据源下的 main 主流程执行。"""
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
        patch("stock.main.settings") as mock_settings,
        patch("stock.main.load_strategy_config") as mock_load_config,
        patch("stock.data.fetcher.tushare.factory.create_tushare_pipeline") as mock_create_pipeline,
        patch("stock.main.StrategyRunner") as mock_runner_cls,
    ):
        mock_settings.app_name = "StockApp"
        mock_settings.environment = "test"
        mock_settings.data_source_mode = "tushare"

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

        mock_create_pipeline.assert_called_once_with(endpoint="daily")


def test_main_with_yfinance_data_source():
    """测试 yfinance 数据源下的 main 主流程执行。"""
    mock_df = pl.DataFrame(
        {
            "symbol": ["AAPL"],
            "trade_date": ["2026-08-10"],
            "open": [150.0],
            "high": [155.0],
            "low": [149.0],
            "close": [152.0],
            "volume": [10000.0],
            "data_source": ["yfinance"],
        }
    )

    with (
        patch("stock.main.settings") as mock_settings,
        patch("stock.main.load_strategy_config") as mock_load_config,
        patch(
            "stock.data.fetcher.yfinance.factory.create_yfinance_pipeline"
        ) as mock_create_pipeline,
        patch("stock.main.StrategyRunner") as mock_runner_cls,
    ):
        mock_settings.app_name = "StockApp"
        mock_settings.environment = "test"
        mock_settings.data_source_mode = "yfinance"
        mock_settings.yfinance_proxy = "http://127.0.0.1:7890"

        mock_config = MagicMock()
        mock_config.name = "TestStrategy"
        mock_config.version = "1.0"
        mock_config.universe.all_symbols = ["AAPL"]
        mock_load_config.return_value = mock_config

        mock_pipeline_inst = MagicMock()
        mock_pipeline_inst.data_source = "yfinance"
        mock_pipeline_inst.sync_daily_bars.return_value = mock_df
        mock_pipeline_inst.store.query_history.return_value = mock_df
        mock_create_pipeline.return_value = mock_pipeline_inst

        mock_runner_inst = MagicMock()
        mock_report = MagicMock()
        mock_report.to_dict.return_value = {"signals": 1}
        mock_runner_inst.run.return_value = mock_report
        mock_runner_cls.return_value = mock_runner_inst

        main()

        mock_create_pipeline.assert_called_once_with(proxy="http://127.0.0.1:7890")


def test_main_with_invalid_data_source():
    """测试不支持的数据源模式抛出 ValueError。"""
    with (
        patch("stock.main.settings") as mock_settings,
        patch("stock.main.load_strategy_config") as mock_load_config,
    ):
        mock_settings.data_source_mode = "unsupported_mode"
        mock_config = MagicMock()
        mock_config.universe.all_symbols = ["000001.SZ"]
        mock_load_config.return_value = mock_config

        with pytest.raises(ValueError, match="不支持的数据源模式"):
            main()
