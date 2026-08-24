"""测试 analytics.pipelines 顶级导出与管线入口。"""

from stock_analytics.pipelines import (
    IndustryStructureRunResult,
    InvestorBriefRunResult,
    MarketTemperatureRunResult,
    run_industry_diagnostics,
    run_industry_structure,
    run_investor_brief,
    run_market_temperature,
    run_stock_diagnostics,
    run_stock_screen,
    run_thesis_review,
    run_watchlist_scanner,
)


def test_pipelines_exports() -> None:
    assert callable(run_market_temperature)
    assert callable(run_industry_structure)
    assert callable(run_investor_brief)
    assert callable(run_industry_diagnostics)
    assert IndustryStructureRunResult is not None
    assert InvestorBriefRunResult is not None
    assert MarketTemperatureRunResult is not None
    assert callable(run_stock_diagnostics)
    assert callable(run_stock_screen)
    assert callable(run_thesis_review)
    assert callable(run_watchlist_scanner)
