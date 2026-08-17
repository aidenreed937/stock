"""全市场两融杠杆渗透率多交易所并发聚合与边界切片单元测试。"""

from datetime import date

import polars as pl
import pytest

from stock.analytics.domains.micro.margin import MarginPenetrationCalculator


def test_margin_calculator_aggregates_all_exchanges() -> None:
    """验证多交易所（SSE/SZSE/BSE）两融余额能够被正确汇总并精确计算渗透率。"""
    margin_df = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 12), date(2026, 8, 12), date(2026, 8, 12)],
            "exchange_id": ["SSE", "SZSE", "BSE"],
            # 真实元数据为元：上交所 1.3552万亿，深交所 1.2837万亿，北交所 84亿
            "rzye": [1.3552e12, 1.2837e12, 8.4e9],
        }
    )

    # 全市场自由流通市值 (Curated 标准单位: 元): 合计 1.0089e14 元 = 100.89 万亿元
    basic_df = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 12), date(2026, 8, 12)],
            "symbol": ["000001.SZ", "600519.SH"],
            "circ_mv": [5.0e13, 5.089e13],
        }
    )

    calc = MarginPenetrationCalculator()
    res = calc.calculate_latest(
        target_date=date(2026, 8, 12),
        margin_df=margin_df,
        daily_basic_df=basic_df,
    )

    assert res is not None
    # 验证两融总余额正确求和：13552 + 12837 + 84 = 26473 亿元
    assert res.margin_balance_yi == pytest.approx(26473.0, 1.0)
    # 验证流通市值：1008900 亿元 (100.89 万亿)
    assert res.circ_mv_yi == pytest.approx(1008900.0, 100.0)
    # 验证渗透率：26473 / 1008900 * 100% = 2.62%
    assert res.margin_penetration == pytest.approx(2.62, 0.05)
    # 验证区间判定：2.62% 属于温和健康带，非出清大底也非过热大顶
    assert res.is_cleared_bottom is False
    assert res.is_overloaded_peak is False
    assert "温和健康带" in res.zone_desc


def test_margin_calculator_strictly_respects_target_date() -> None:
    """验证多日期数据存在时，严格截断至 target_date 之前，绝不计算未来数据。"""
    margin_df = pl.DataFrame(
        {
            "trade_date": [
                date(2026, 8, 11),
                date(2026, 8, 12),
                date(2026, 8, 13),  # 未来数据
            ],
            "rzye": [2.6e12, 2.65e12, 3.0e12],
        }
    )
    basic_df = pl.DataFrame(
        {
            "trade_date": [
                date(2026, 8, 11),
                date(2026, 8, 12),
                date(2026, 8, 13),
            ],
            "circ_mv": [1.0e14, 1.0e14, 1.0e14],
        }
    )

    calc = MarginPenetrationCalculator()
    res = calc.calculate_latest(
        target_date=date(2026, 8, 12),
        margin_df=margin_df,
        daily_basic_df=basic_df,
    )

    assert res is not None
    assert res.trade_date == date(2026, 8, 12)
    assert res.margin_balance_yi == pytest.approx(26500.0, 1.0)


def test_margin_calculator_excludes_incomplete_exchange_date() -> None:
    margin_df = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 14), date(2026, 8, 14)],
            "exchange_id": ["SSE", "SZSE"],
            "rzye": [1.0e12, 1.0e12],
        }
    )
    basic_df = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 14)],
            "circ_mv": [1.0e14],
        }
    )

    result = MarginPenetrationCalculator().calculate_series(
        margin_df=margin_df,
        daily_basic_df=basic_df,
    )

    assert result.is_empty()
