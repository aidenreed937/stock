"""能源命令行工具单元测试。"""

from __future__ import annotations

from unittest.mock import patch

from stock_cli.energy import main


def test_energy_cli_help() -> None:
    """测试无参数时输出 help 并返回 0。"""
    assert main([]) == 0


def test_energy_cli_inspect() -> None:
    """测试 inspect 命令正常执行。"""
    assert main(["inspect"]) == 0


def test_energy_cli_query() -> None:
    """测试 query 命令过滤查询。"""
    assert main(["query", "-g", "CHN", "--tech", "SOLAR_PV", "-n", "5"]) == 0
    assert main(["query", "-t", "generation", "-g", "CHN", "-n", "5"]) == 0


def test_energy_cli_sync() -> None:
    """测试 sync 命令调度 pipeline。"""
    with patch("stock_cli.energy.sync_all_energy_data") as mock_sync:
        mock_sync.return_value = {"global_renewable_capacity": 100}
        ret = main(["sync", "-s", "cn_nea"])
        assert ret == 0
        mock_sync.assert_called_once_with(sources=["cn_nea"])


def test_energy_cli_backfill() -> None:
    """测试 backfill 命令调度 pipeline。"""
    with patch("stock_cli.energy.sync_all_energy_data") as mock_sync:
        mock_sync.return_value = {"global_renewable_capacity": 32427}
        ret = main(["backfill", "-s", "all", "--force"])
        assert ret == 0
        mock_sync.assert_called_once_with(sources=None)
