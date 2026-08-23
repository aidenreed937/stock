"""个股诊断 CLI 单元测试。"""

import json
from io import StringIO
from unittest.mock import MagicMock

import pytest

from stock_analytics.pipelines.stock_diagnostics.types import (
    CapitalFlowSnapshot,
    FinancialsSnapshot,
    MarketContextSnapshot,
    ScreenSnapshot,
    StockDiagnosticsResult,
    TechnicalsSnapshot,
    ValuationSnapshot,
)
from stock_cli import diagnose


@pytest.fixture
def dummy_result() -> StockDiagnosticsResult:
    return StockDiagnosticsResult(
        symbol="600519.SH",
        name="贵州茅台",
        as_of_date="2026-08-20",
        industry="白酒",
        area="贵州",
        market="主板",
        technicals=TechnicalsSnapshot(close=1432.5),
        valuation=ValuationSnapshot(pe_ttm=21.8, dividend_spread_10y=1.97, treasury_10y_yield=1.68),
        financials=FinancialsSnapshot(roe=27.4),
        capital_flow=CapitalFlowSnapshot(
            main_net_inflow_20d_billion=3.5, northbound_hold_ratio=6.8
        ),
        screen=ScreenSnapshot(status="passed"),
        market_context=MarketContextSnapshot(as_of_date="2026-08-20"),
    )


def test_diagnose_cli_parser() -> None:
    parser = diagnose._build_parser()
    args = parser.parse_args(["--symbol", "600519", "--format", "json"])
    assert args.symbol == "600519"
    assert args.output_format == "json"


def test_diagnose_cli_main_json(
    monkeypatch: pytest.MonkeyPatch, dummy_result: StockDiagnosticsResult
) -> None:
    monkeypatch.setattr(diagnose, "run_stock_diagnostics", MagicMock(return_value=dummy_result))
    monkeypatch.setattr(
        "sys.argv",
        ["stock_cli.diagnose", "--symbol", "600519", "--format", "json"],
    )

    out = StringIO()
    monkeypatch.setattr("sys.stdout", out)

    diagnose.main()
    output_str = out.getvalue()
    parsed = json.loads(output_str)
    assert parsed["symbol"] == "600519.SH"
    assert parsed["technicals"]["close"] == 1432.5
    assert parsed["capital_flow"]["main_net_inflow_20d_billion"] == 3.5


def test_diagnose_cli_main_markdown(
    monkeypatch: pytest.MonkeyPatch, dummy_result: StockDiagnosticsResult
) -> None:
    monkeypatch.setattr(diagnose, "run_stock_diagnostics", MagicMock(return_value=dummy_result))
    monkeypatch.setattr(
        "sys.argv",
        ["stock_cli.diagnose", "--symbol", "600519", "--format", "markdown"],
    )

    out = StringIO()
    monkeypatch.setattr("sys.stdout", out)

    diagnose.main()
    output_str = out.getvalue()
    assert "# 个股量化全景体检报告" in output_str
    assert "贵州茅台" in output_str
    assert "股息利差安全垫" in output_str
