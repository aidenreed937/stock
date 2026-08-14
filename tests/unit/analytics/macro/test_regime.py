from datetime import date
from unittest.mock import MagicMock

from stock.analytics.macro.regime import MacroRegimeAnalyzer
from stock.analytics.models import (
    AllMarketValuationResult,
    BuffettRatioResult,
    EYBYRatioResult,
    MacroRegime,
    ValuationZone,
)


def test_macro_regime_opportunity_zone_pure_bottom() -> None:
    mock_eyby = MagicMock()
    mock_eyby.calculate_latest.return_value = EYBYRatioResult(
        trade_date=date(2026, 8, 14),
        symbol="000300",
        pe_ttm=11.5,
        earnings_yield=8.7,
        bond_yield_10y=2.1,
        ey_by_ratio=2.45,
        percentile_10y=95.0,
        zone=ValuationZone.EXTREME_LOW,
        zone_desc="战略大底",
        is_strategic_bottom=True,
        is_bubble_peak=False,
    )

    mock_all_market = MagicMock()
    mock_all_market.calculate_latest.return_value = AllMarketValuationResult(
        trade_date=date(2026, 8, 14),
        symbol="000985",
        index_name="中证全指",
        pb_ew=1.5,
        pb_percentile_10y=15.0,
        pe_ttm_ew=30.0,
        pe_percentile_10y=20.0,
        zone=ValuationZone.LOW,
        zone_desc="偏低估",
    )

    mock_buffett = MagicMock()
    mock_buffett.calculate_latest.return_value = BuffettRatioResult(
        trade_date=date(2026, 8, 14),
        total_market_cap_yi=600000.0,
        gdp_ttm_yi=1000000.0,
        securitization_ratio=60.0,
        percentile_10y=10.0,
        zone=ValuationZone.EXTREME_LOW,
        zone_desc="黄金大底",
        is_golden_bottom=True,
        is_bubble_overheat=False,
    )

    analyzer = MacroRegimeAnalyzer(
        eyby_calc=mock_eyby,
        buffett_calc=mock_buffett,
        all_market_analyzer=mock_all_market,
    )
    res = analyzer.evaluate_regime()

    assert res is not None
    assert res.regime == MacroRegime.OPPORTUNITY_ZONE
    assert res.suggested_equity_exposure >= 0.85
    assert len(res.key_drivers) >= 2


def test_macro_regime_structural_opportunity_zone() -> None:
    mock_eyby = MagicMock()
    mock_eyby.calculate_latest.return_value = EYBYRatioResult(
        trade_date=date(2026, 8, 14),
        symbol="000300",
        pe_ttm=12.0,
        earnings_yield=8.33,
        bond_yield_10y=1.7,
        ey_by_ratio=2.67,
        percentile_10y=86.0,
        zone=ValuationZone.EXTREME_LOW,
        zone_desc="战略大底",
        is_strategic_bottom=True,
        is_bubble_peak=False,
    )

    mock_all_market = MagicMock()
    mock_all_market.calculate_latest.return_value = AllMarketValuationResult(
        trade_date=date(2026, 8, 14),
        symbol="000985",
        index_name="中证全指",
        pb_ew=2.16,
        pb_percentile_10y=63.0,
        pe_ttm_ew=113.0,
        pe_percentile_10y=88.0,
        zone=ValuationZone.HIGH,
        zone_desc="中枢偏上",
    )

    mock_buffett = MagicMock()
    mock_buffett.calculate_latest.return_value = BuffettRatioResult(
        trade_date=date(2026, 8, 14),
        total_market_cap_yi=1300000.0,
        gdp_ttm_yi=1330000.0,
        securitization_ratio=97.7,
        percentile_10y=98.0,
        zone=ValuationZone.HIGH,
        zone_desc="规模高位",
        is_golden_bottom=False,
        is_bubble_overheat=True,
    )

    analyzer = MacroRegimeAnalyzer(
        eyby_calc=mock_eyby,
        buffett_calc=mock_buffett,
        all_market_analyzer=mock_all_market,
    )
    res = analyzer.evaluate_regime()

    assert res is not None
    assert res.regime == MacroRegime.OPPORTUNITY_ZONE
    assert res.suggested_equity_exposure == 0.75  # 结构性战略机会仓位 75%
    assert any("结构" in d for d in res.key_drivers)


def test_macro_regime_bubble_risk() -> None:
    mock_eyby = MagicMock()
    mock_eyby.calculate_latest.return_value = EYBYRatioResult(
        trade_date=date(2026, 8, 14),
        symbol="000300",
        pe_ttm=35.0,
        earnings_yield=2.85,
        bond_yield_10y=3.5,
        ey_by_ratio=0.81,
        percentile_10y=2.0,
        zone=ValuationZone.EXTREME_HIGH,
        zone_desc="牛顶泡沫",
        is_strategic_bottom=False,
        is_bubble_peak=True,
    )
    mock_all_market = MagicMock()
    mock_all_market.calculate_latest.return_value = None
    mock_buffett = MagicMock()
    mock_buffett.calculate_latest.return_value = None

    analyzer = MacroRegimeAnalyzer(
        eyby_calc=mock_eyby,
        buffett_calc=mock_buffett,
        all_market_analyzer=mock_all_market,
    )
    res = analyzer.evaluate_regime()

    assert res is not None
    assert res.regime == MacroRegime.BUBBLE_RISK
    assert res.suggested_equity_exposure <= 0.20
