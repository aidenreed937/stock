from datetime import date
from unittest.mock import MagicMock

from stock.analytics.macro.regime import MacroRegimeAnalyzer
from stock.analytics.models import BuffettRatioResult, EYBYRatioResult, MacroRegime, ValuationZone


def test_macro_regime_opportunity_zone() -> None:
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

    analyzer = MacroRegimeAnalyzer(eyby_calc=mock_eyby, buffett_calc=mock_buffett)
    res = analyzer.evaluate_regime()

    assert res is not None
    assert res.regime == MacroRegime.OPPORTUNITY_ZONE
    assert res.suggested_equity_exposure >= 0.85
    assert len(res.key_drivers) >= 2


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
    mock_buffett = MagicMock()
    mock_buffett.calculate_latest.return_value = None

    analyzer = MacroRegimeAnalyzer(eyby_calc=mock_eyby, buffett_calc=mock_buffett)
    res = analyzer.evaluate_regime()

    assert res is not None
    assert res.regime == MacroRegime.BUBBLE_RISK
    assert res.suggested_equity_exposure <= 0.20
