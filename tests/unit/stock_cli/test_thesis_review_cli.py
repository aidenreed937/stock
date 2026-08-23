"""投资假设跨周期复盘 CLI 单元测试。"""

import json
from io import StringIO
from unittest.mock import MagicMock

import pytest

from stock_analytics.pipelines.thesis_review.types import (
    InvestmentThesis,
    ThesisReviewAttribution,
    ThesisReviewResult,
)
from stock_cli import thesis_review


@pytest.fixture
def dummy_review_result() -> ThesisReviewResult:
    thesis = InvestmentThesis(
        thesis_id="600519_2026-05-20",
        symbol="600519.SH",
        name="贵州茅台",
        created_date="2026-05-20",
        base_price=1550.0,
        initial_pe_ttm=24.5,
        expected_growth=12.0,
        expected_pe_anchor=25.0,
    )
    attribution = ThesisReviewAttribution(
        current_price=1272.83,
        price_change_pct=-17.88,
        actual_growth=8.5,
        growth_gap=-3.5,
        current_pe_ttm=19.5,
        pe_change_pct=-20.4,
        is_stop_loss_triggered=True,
        is_value_trap=True,
        verdict="🚨 触及严格止损线 (建议执行风控纪律)",
        reflection_notes=["估值端收缩 20.4%"],
        action_guidance=["严格执行止损纪律"],
    )
    return ThesisReviewResult(
        thesis=thesis,
        as_of_date="2026-08-21",
        days_elapsed=93,
        attribution=attribution,
    )


def test_thesis_review_cli_parser() -> None:
    parser = thesis_review._build_parser()
    args = parser.parse_args(["--symbol", "600519.SH", "--format", "json"])
    assert args.symbol == "600519.SH"
    assert args.output_format == "json"


def test_thesis_review_cli_main_json(
    monkeypatch: pytest.MonkeyPatch, dummy_review_result: ThesisReviewResult
) -> None:
    monkeypatch.setattr(
        thesis_review,
        "run_thesis_review",
        MagicMock(return_value=dummy_review_result),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["stock_cli.thesis_review", "--symbol", "600519.SH", "--format", "json"],
    )

    out = StringIO()
    monkeypatch.setattr("sys.stdout", out)

    thesis_review.main()
    output_str = out.getvalue()
    parsed = json.loads(output_str)
    assert parsed["thesis"]["symbol"] == "600519.SH"
    assert parsed["attribution"]["is_stop_loss_triggered"] is True


def test_thesis_review_cli_main_markdown(
    monkeypatch: pytest.MonkeyPatch, dummy_review_result: ThesisReviewResult
) -> None:
    monkeypatch.setattr(
        thesis_review,
        "run_thesis_review",
        MagicMock(return_value=dummy_review_result),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["stock_cli.thesis_review", "--symbol", "600519.SH", "--format", "markdown"],
    )

    out = StringIO()
    monkeypatch.setattr("sys.stdout", out)

    thesis_review.main()
    output_str = out.getvalue()
    assert "# 投资假设跨周期验证与复盘自省报告" in output_str
    assert "贵州茅台" in output_str
    assert "600519.SH" in output_str
