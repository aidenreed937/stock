"""自选池批量扫描 CLI 单元测试。"""

import json
from io import StringIO
from unittest.mock import MagicMock

import pytest

from stock_analytics.pipelines.watchlist_scanner.types import (
    WatchlistItemSummary,
    WatchlistScanResult,
)
from stock_cli import scan_watchlist


@pytest.fixture
def dummy_scan_result() -> WatchlistScanResult:
    return WatchlistScanResult(
        as_of_date="2026-08-21",
        total_scanned=1,
        items=[
            WatchlistItemSummary(
                symbol="600519.SH",
                name="贵州茅台",
                industry="白酒",
                close=1272.83,
                pct_chg=-1.45,
                pe_ttm=19.54,
                pe_percentile_5y=4.7,
                pb=6.33,
                dv_ttm=4.09,
                dividend_spread_10y=2.41,
                roe=17.95,
                trend_description="震荡整理",
                value_trap_warning=False,
                screen_status="passed",
                tags=["极低估值", "高股息利差"],
            )
        ],
        golden_pit_candidates=[],
        high_dividend_candidates=[],
        value_trap_candidates=[],
    )


def test_scan_watchlist_cli_parser() -> None:
    parser = scan_watchlist._build_parser()
    args = parser.parse_args(["--format", "json"])
    assert args.output_format == "json"


def test_scan_watchlist_cli_main_json(
    monkeypatch: pytest.MonkeyPatch, dummy_scan_result: WatchlistScanResult
) -> None:
    monkeypatch.setattr(
        scan_watchlist,
        "run_watchlist_scanner",
        MagicMock(return_value=dummy_scan_result),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["stock_cli.scan_watchlist", "--format", "json"],
    )

    out = StringIO()
    monkeypatch.setattr("sys.stdout", out)

    scan_watchlist.main()
    output_str = out.getvalue()
    parsed = json.loads(output_str)
    assert parsed["total_scanned"] == 1
    assert parsed["items"][0]["symbol"] == "600519.SH"


def test_scan_watchlist_cli_main_markdown(
    monkeypatch: pytest.MonkeyPatch, dummy_scan_result: WatchlistScanResult
) -> None:
    monkeypatch.setattr(
        scan_watchlist,
        "run_watchlist_scanner",
        MagicMock(return_value=dummy_scan_result),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["stock_cli.scan_watchlist", "--format", "markdown"],
    )

    out = StringIO()
    monkeypatch.setattr("sys.stdout", out)

    scan_watchlist.main()
    output_str = out.getvalue()
    assert "# 核心观察池量化全景雷达" in output_str
    assert "贵州茅台" in output_str
