"""单元测试: 全 A 资产水位分析器 AllMarketValuationAnalyzer。"""

from datetime import date
from unittest.mock import MagicMock

import polars as pl

from stock.analytics.macro.all_market import AllMarketValuationAnalyzer
from stock.analytics.models import ValuationZone


def _make_mock_fundamental_df() -> pl.DataFrame:
    """构造用于测试中证全指 PB 分位的模拟数据。"""
    dates = [
        date(2025, 1, 1),
        date(2025, 6, 1),
        date(2025, 12, 1),
        date(2026, 8, 12),
    ]
    return pl.DataFrame(
        {
            "symbol": ["000985"] * 4,
            "trade_date": dates,
            "pb.ew": [1.5, 2.0, 2.5, 2.2],
            "pe_ttm.ew": [50.0, 60.0, 70.0, 65.0],
        }
    )


def test_all_market_valuation_calculation() -> None:
    mock_catalog = MagicMock()
    mock_catalog.load_dataset.return_value = _make_mock_fundamental_df()

    analyzer = AllMarketValuationAnalyzer(catalog=mock_catalog)
    res = analyzer.calculate_latest(symbol="000985", target_date=date(2026, 8, 12))

    assert res is not None
    assert res.symbol == "000985"
    assert res.index_name == "中证全指"
    assert res.pb_ew == 2.2
    # pb 2.2 在 [1.5, 2.0, 2.5, 2.2] 中排第 3/4 = 75.0%
    assert res.pb_percentile_10y == 75.0
    assert res.zone == ValuationZone.HIGH


def test_all_market_valuation_symbol_normalization() -> None:
    mock_catalog = MagicMock()
    mock_catalog.load_dataset.return_value = _make_mock_fundamental_df()

    analyzer = AllMarketValuationAnalyzer(catalog=mock_catalog)
    # 支持 000985.SH 自动归一化
    res = analyzer.calculate_latest(symbol="000985.SH", target_date=date(2026, 8, 12))

    assert res is not None
    assert res.symbol == "000985"
    assert res.pb_ew == 2.2


def test_all_market_valuation_empty() -> None:
    mock_catalog = MagicMock()
    mock_catalog.load_dataset.return_value = pl.DataFrame()

    analyzer = AllMarketValuationAnalyzer(catalog=mock_catalog)
    res = analyzer.calculate_latest(symbol="000985")
    assert res is None
