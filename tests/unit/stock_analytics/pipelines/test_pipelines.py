"""测试 analytics.pipelines 顶级导出与管线入口。"""

from stock_analytics.pipelines import (
    IndustryStructureRunResult,
    InvestorBriefRunResult,
    MarketTemperatureRunResult,
    run_industry_structure,
    run_investor_brief,
    run_market_temperature,
)


def test_pipelines_exports() -> None:
    assert callable(run_market_temperature)
    assert callable(run_industry_structure)
    assert callable(run_investor_brief)
    assert IndustryStructureRunResult is not None
    assert InvestorBriefRunResult is not None
    assert MarketTemperatureRunResult is not None
