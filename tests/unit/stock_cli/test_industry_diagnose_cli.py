"""行业诊断 CLI 单元测试。"""

import json
from io import StringIO
from unittest.mock import MagicMock

import pytest

from stock_analytics.pipelines.industry_diagnostics.types import (
    IndustryConstituentsSnapshot,
    IndustryDiagnosticsResult,
    IndustryFinancialsSnapshot,
    IndustryTechnicalsSnapshot,
    IndustryValuationSnapshot,
    IndustryValueChainSnapshot,
)
from stock_cli import industry_diagnose


@pytest.fixture
def dummy_industry_result() -> IndustryDiagnosticsResult:
    return IndustryDiagnosticsResult(
        industry_code="801120.SI",
        industry_name="食品饮料",
        level="申万一级",
        as_of_date="2026-08-21",
        technicals=IndustryTechnicalsSnapshot(close=13788.89, pct_chg=-1.36),
        valuation=IndustryValuationSnapshot(pe_ttm=19.76, pe_percentile_5y=12.5),
        financials=IndustryFinancialsSnapshot(report_date="2026-06-30"),
        constituents=IndustryConstituentsSnapshot(
            total_count=120,
            top_market_cap_leaders=[
                {"symbol": "600519.SH", "name": "贵州茅台", "total_mv_billion": 15911.4}
            ],
        ),
        value_chain=IndustryValueChainSnapshot(upstream=["高粱/农产品"], downstream=["消费终端"]),
    )


def test_industry_diagnose_cli_parser() -> None:
    parser = industry_diagnose._build_parser()
    args = parser.parse_args(["--industry", "食品饮料", "--format", "json"])
    assert args.industry == "食品饮料"
    assert args.output_format == "json"


def test_industry_diagnose_cli_main_json(
    monkeypatch: pytest.MonkeyPatch, dummy_industry_result: IndustryDiagnosticsResult
) -> None:
    monkeypatch.setattr(
        industry_diagnose,
        "run_industry_diagnostics",
        MagicMock(return_value=dummy_industry_result),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["stock_cli.industry_diagnose", "--industry", "食品饮料", "--format", "json"],
    )

    out = StringIO()
    monkeypatch.setattr("sys.stdout", out)

    industry_diagnose.main()
    output_str = out.getvalue()
    parsed = json.loads(output_str)
    assert parsed["industry_code"] == "801120.SI"
    assert parsed["technicals"]["close"] == 13788.89


def test_industry_diagnose_cli_main_markdown(
    monkeypatch: pytest.MonkeyPatch, dummy_industry_result: IndustryDiagnosticsResult
) -> None:
    monkeypatch.setattr(
        industry_diagnose,
        "run_industry_diagnostics",
        MagicMock(return_value=dummy_industry_result),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["stock_cli.industry_diagnose", "--industry", "食品饮料", "--format", "markdown"],
    )

    out = StringIO()
    monkeypatch.setattr("sys.stdout", out)

    industry_diagnose.main()
    output_str = out.getvalue()
    assert "# 中观产业深度量化诊断报告" in output_str
    assert "食品饮料" in output_str
    assert "贵州茅台" in output_str
