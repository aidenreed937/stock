"""海关贸易 CLI 命令行管理入口单元测试。"""

from unittest.mock import MagicMock, patch

from stock_cli.customs import main


def test_customs_cli_catalog() -> None:
    """测试 catalog 子命令正常执行。"""
    exit_code = main(["catalog"])
    assert exit_code == 0


def test_customs_cli_backfill() -> None:
    """测试 backfill 子命令参数解析与委托调用。"""
    with patch("stock_cli.customs.ComtradeCollector") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.backfill.return_value = 840
        mock_cls.return_value = mock_instance

        exit_code = main(["backfill", "--start-year", "2023", "--end-year", "2024", "--force"])
        assert exit_code == 0
        mock_instance.backfill.assert_called_once_with(
            start_year=2023,
            end_year=2024,
            force=True,
            curated_path="data/curated/industry/customs_trade.parquet",
        )


def test_customs_cli_sync() -> None:
    """测试 sync 子命令增量拉取与落盘。"""
    with (
        patch("stock_cli.customs.ComtradeCollector") as mock_cls,
        patch("stock_cli.customs.records_to_customs_trade_frame"),
        patch("stock_cli.customs.save_curated_fact") as mock_save,
    ):
        mock_instance = MagicMock()
        mock_instance.fetch_api.return_value = [{"cmdCode": "85042100"}]
        mock_instance.collect.return_value = [MagicMock()]
        mock_cls.return_value = mock_instance
        mock_save.return_value = 100

        exit_code = main(["sync", "-p", "2024-12"])
        assert exit_code == 0
        mock_instance.fetch_api.assert_called_once_with(period="2024-12")
