"""自选池批量量化雷达单元测试。"""

from datetime import date
from pathlib import Path
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
from stock_analytics.pipelines.watchlist_scanner import (
    WatchlistItemSummary,
    WatchlistScanResult,
    run_watchlist_scanner,
)
from stock_analytics.pipelines.watchlist_scanner.pipeline import (
    _load_watchlist_stock_symbols,
)


def test_watchlist_serialization() -> None:
    res = WatchlistScanResult(
        as_of_date="2026-08-21",
        total_scanned=2,
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
                value_trap_warning=True,
                screen_status="passed",
                tags=["高股息利差", "⚠️价值陷阱"],
            )
        ],
        golden_pit_candidates=[],
        high_dividend_candidates=[],
        value_trap_candidates=[],
    )

    d = res.to_dict()
    assert d["total_scanned"] == 2
    assert d["items"][0]["symbol"] == "600519.SH"

    md = res.to_markdown()
    assert "核心观察池量化全景雷达" in md
    assert "贵州茅台" in md
    assert "600519.SH" in md
    assert "1272.83" in md


def test_load_watchlist_stock_symbols(tmp_path: Path) -> None:
    yaml_content = """
universe:
  a_shares:
    stocks:
      - code: "600519.SH"
        name: "贵州茅台"
      - code: "300750.SZ"
        name: "宁德时代"
"""
    p = tmp_path / "test_watchlist.yaml"
    p.write_text(yaml_content, encoding="utf-8")

    syms = _load_watchlist_stock_symbols(p)
    assert syms == ["600519.SH", "300750.SZ"]


def test_run_watchlist_scanner_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    dummy_diag = StockDiagnosticsResult(
        symbol="600519.SH",
        name="贵州茅台",
        as_of_date="2026-08-21",
        industry="白酒",
        area="贵州",
        market="主板",
        technicals=TechnicalsSnapshot(close=1272.83, pct_chg=-1.45, trend_description="多头排列"),
        valuation=ValuationSnapshot(
            pe_ttm=19.54,
            pe_percentile_5y=4.7,
            pb=6.33,
            dv_ttm=4.09,
            dividend_spread_10y=2.41,
            value_trap_warning=False,
        ),
        financials=FinancialsSnapshot(roe=17.95),
        capital_flow=CapitalFlowSnapshot(),
        screen=ScreenSnapshot(status="passed"),
        market_context=MarketContextSnapshot(),
    )

    from stock_analytics.pipelines.watchlist_scanner import pipeline

    monkeypatch.setattr(pipeline, "run_stock_diagnostics", MagicMock(return_value=dummy_diag))

    res = run_watchlist_scanner(
        target_date=date(2026, 8, 21),
        symbols=["600519.SH"],
    )

    assert res.total_scanned == 1
    assert len(res.golden_pit_candidates) == 1
    assert len(res.high_dividend_candidates) == 1
    assert "极低估值" in res.items[0].tags
    assert "多头排列" in res.items[0].tags
