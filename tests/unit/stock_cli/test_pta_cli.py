"""PTA 命令行工具 (stock_cli.pta) 单元测试。"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from stock_cli.pta import _build_parser, main


def test_pta_cli_parser_defaults() -> None:
    """测试 PTA CLI 解析器参数默认值。"""
    parser = _build_parser()
    args = parser.parse_args([])
    assert args.as_of_date is None
    assert args.save is False
    assert args.format == "markdown"
    assert args.project is False
    assert args.scenario == "all"
    assert args.symbol == "all"


def test_pta_cli_project_mode_json(capsys: pytest.CaptureFixture[str]) -> None:
    """测试 --project -f json 模式输出结构化数据。"""
    test_args = ["stock_cli.pta", "--project", "-f", "json", "--scenario", "mid_cycle"]
    with patch("sys.argv", test_args):
        main()

    captured = capsys.readouterr()
    assert captured.out != ""
    payload = json.loads(captured.out)
    assert "projections" in payload
    assert len(payload["projections"]) == 2  # 恒力石化 + 桐昆股份

    symbols = [r["symbol"] for r in payload["projections"]]
    assert "600346.SH" in symbols
    assert "601233.SH" in symbols


def test_pta_cli_project_mode_markdown(capsys: pytest.CaptureFixture[str]) -> None:
    """测试 --project 模式输出 Markdown SOTP 表。"""
    test_args = ["stock_cli.pta", "--project", "--symbol", "600346.SH"]
    with patch("sys.argv", test_args):
        main()

    captured = capsys.readouterr()
    assert "恒力石化" in captured.out
    assert "PTA 核心双雄" in captured.out
    assert "敏感性矩阵" in captured.out
