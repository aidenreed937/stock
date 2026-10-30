"""海关贸易 CLI 命令行管理入口单元测试。"""

from unittest.mock import patch

from stock_cli.customs import main


def test_customs_cli_catalog() -> None:
    """测试 catalog 子命令正常执行。"""
    exit_code = main(["catalog"])
    assert exit_code == 0


def test_customs_cli_tariffline() -> None:
    """测试 Tariffline 原始采集命令的参数转换。"""
    with patch("stock_cli.customs.ComtradeCollector") as mock_cls:
        mock_instance = mock_cls.return_value
        mock_instance.fetch_tariffline_api.return_value = [{"cmdCode": "25041010"}]

        exit_code = main(
            [
                "tariffline",
                "--period",
                "2024-01,2024-02",
                "--cmd-codes",
                "250410,300490",
                "--flow",
                "both",
            ]
        )
        assert exit_code == 0
        mock_instance.fetch_tariffline_api.assert_called_once_with(
            period="202401,202402",
            flow_code="M,X",
            cmd_codes=["250410", "300490"],
            max_records=100000,
        )


def test_customs_cli_gacc_import() -> None:
    """测试 GACC 人工导出 CSV 导入命令将参数委托给采集器。"""
    with (
        patch("stock_cli.customs.GaccCollector") as mock_cls,
        patch("stock_cli.customs.records_to_customs_trade_frame"),
        patch("stock_cli.customs.save_curated_fact") as mock_save,
    ):
        mock_instance = mock_cls.return_value
        mock_instance.import_csv.return_value = type(
            "Collection",
            (),
            {"records": [object()], "status": "SUCCESS", "errors": ()},
        )()
        mock_save.return_value = 1

        exit_code = main(
            [
                "gacc-import",
                "--file",
                "manual.csv",
                "--period",
                "2025-01",
                "--flow",
                "export",
                "--force",
            ]
        )

        assert exit_code == 0
        mock_instance.import_csv.assert_called_once_with(
            "manual.csv",
            start_month="2025-01",
            end_month=None,
            flow_type="export",
            currency="USD",
            force=True,
        )
