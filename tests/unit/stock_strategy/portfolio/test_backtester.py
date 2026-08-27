"""因子组合回测核心测试（手工可算小样本）。"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from stock_core.exceptions import DataValidationError
from stock_strategy.portfolio.backtester import run_factor_backtest

_D1, _D2, _D3, _D4, _D5, _D6 = (date(2024, 1, i) for i in range(1, 7))


def _scores() -> pl.DataFrame:
    """六日三标的组合分数（top-2 选择在 d1/d3/d5 调仓日确定）。"""
    return pl.DataFrame(
        {
            "trade_date": [
                _D1,
                _D1,
                _D1,
                _D2,
                _D2,
                _D2,
                _D3,
                _D3,
                _D3,
                _D4,
                _D4,
                _D4,
                _D5,
                _D5,
                _D5,
                _D6,
                _D6,
                _D6,
            ],
            "symbol": ["A", "B", "C"] * 6,
            "composite_score": [
                10.0,
                9.0,
                1.0,  # d1 -> picks A,B
                0.0,
                0.0,
                0.0,  # d2（非调仓日，分数无关）
                1.0,
                10.0,
                9.0,  # d3 -> picks B,C
                0.0,
                0.0,
                0.0,  # d4
                9.0,
                8.0,
                10.0,  # d5 -> picks C,A
                0.0,
                0.0,
                0.0,  # d6
            ],
        }
    )


def _prices() -> pl.DataFrame:
    """六日三标的收盘价（相邻日收益：A 0/10%/0/10%/0；B 10%/0/10%/0/10%；C 0/10%/0/10%/0）。"""
    return pl.DataFrame(
        {
            "trade_date": [
                _D1,
                _D1,
                _D1,
                _D2,
                _D2,
                _D2,
                _D3,
                _D3,
                _D3,
                _D4,
                _D4,
                _D4,
                _D5,
                _D5,
                _D5,
                _D6,
                _D6,
                _D6,
            ],
            "symbol": ["A", "B", "C"] * 6,
            "close": [
                100.0,
                100.0,
                50.0,
                100.0,
                110.0,
                50.0,
                110.0,
                110.0,
                55.0,
                110.0,
                121.0,
                55.0,
                121.0,
                121.0,
                60.5,
                121.0,
                133.1,
                60.5,
            ],
        }
    )


class TestRunBacktest:
    def test_hand_calculated_nav(self) -> None:
        result = run_factor_backtest(_scores(), _prices(), rebalance_days=2, top_n=2)
        nav = result.nav["nav"].to_list()
        # 手工推导：1, 1.05, 1.1025, 1.157625, 1.21550625, 1.21550625
        assert nav == pytest.approx([1.0, 1.05, 1.1025, 1.157625, 1.21550625, 1.21550625])

    def test_top_n_weights_only_selected(self) -> None:
        # d1 分数 10/9/1，top-2 仅 A、B 有仓位（每份 1/2），C 不持仓
        result = run_factor_backtest(_scores(), _prices(), rebalance_days=2, top_n=2)
        # d1->d2 收益 = 0.5*0 + 0.5*10% = 5%
        assert result.nav[1, "nav"] == pytest.approx(1.05)

    def test_single_valid_score_cash_buffer(self) -> None:
        scores = _scores().with_columns(
            pl.when(pl.col("symbol") != "A")
            .then(None)
            .otherwise(pl.col("composite_score"))
            .alias("composite_score")
        )
        prices = _prices()
        # d1 仅 A 有分数：top-2 只持有 A（0.5 权重），现金 0.5
        result = run_factor_backtest(scores, prices, rebalance_days=2, top_n=2)
        # d1->d2 收益 = 0.5 * A(0%) = 0
        assert result.nav[1, "nav"] == pytest.approx(1.0)

    def test_stale_weights_hold_over_missing_score(self) -> None:
        # d3 无任何分数：沿用 d1 的 A/B 持仓；d3 当天收益按 A/B 旧权重计
        scores = _scores().with_columns(
            pl.when(pl.col("trade_date") == _D3)
            .then(None)
            .otherwise(pl.col("composite_score"))
            .alias("composite_score")
        )
        result = run_factor_backtest(scores, _prices(), rebalance_days=2, top_n=2)
        # d2 收益 5%（A0/B10）；d3 调仓日沿用 A/B：0.5*10% + 0.5*0 = 5%
        assert result.nav[1, "nav"] == pytest.approx(1.05)
        assert result.nav[2, "nav"] == pytest.approx(1.1025)

    def test_benchmark_equal_weight(self) -> None:
        result = run_factor_backtest(_scores(), _prices(), rebalance_days=2, top_n=2)
        bench = result.benchmark_nav["nav"].to_list()
        # 等权 1/3：d2 = 0.10/3；d3 = 0.20/3；d4 = 0.10/3；d5 = 0.20/3；d6 = 0.10/3
        expected = [1.0]
        for factor in (0.10 / 3, 0.20 / 3, 0.10 / 3, 0.20 / 3, 0.10 / 3):
            expected.append(expected[-1] * (1.0 + factor))
        assert bench == pytest.approx(expected)


class TestStats:
    def test_stats_math(self) -> None:
        result = run_factor_backtest(_scores(), _prices(), rebalance_days=2, top_n=2)
        stats = result.stats
        final_nav = 1.21550625
        assert stats["n_trading_days"] == 5
        assert stats["total_return"] == pytest.approx(final_nav - 1.0)
        assert stats["annual_return"] == pytest.approx(final_nav ** (252 / 5) - 1.0)
        assert stats["max_drawdown"] == 0.0  # 单调上行无回撤
        assert stats["period_win_rate"] == 1.0  # 两个调仓期收益均 > 0
        assert stats["annual_volatility"] is not None
        assert stats["sharpe"] == pytest.approx(stats["annual_return"] / stats["annual_volatility"])

    def test_max_drawdown_detected(self) -> None:
        prices = pl.DataFrame(
            {
                "trade_date": [_D1, _D1, _D1, _D2, _D2, _D2, _D3, _D3, _D3],
                "symbol": ["A", "B", "C"] * 3,
                "close": [100.0, 100.0, 50.0, 110.0, 110.0, 55.0, 99.0, 99.0, 49.5],
            }
        )
        scores = _scores().filter(pl.col("trade_date") <= _D3)
        result = run_factor_backtest(scores, prices, rebalance_days=2, top_n=2)
        # 只持 A/B：d2 +10%(A)，d3 -10%(A) -> 回撤 10%
        assert result.stats["max_drawdown"] == pytest.approx(0.1)


class TestFailClosed:
    def test_empty_scores_raises(self) -> None:
        with pytest.raises(DataValidationError):
            run_factor_backtest(pl.DataFrame(), _prices(), rebalance_days=2, top_n=2)

    def test_missing_columns_raises(self) -> None:
        bad = _scores().drop("composite_score")
        with pytest.raises(DataValidationError):
            run_factor_backtest(bad, _prices(), rebalance_days=2, top_n=2)

    def test_no_overlap_raises(self) -> None:
        prices = _prices().with_columns(pl.lit("X").alias("symbol"))
        with pytest.raises(DataValidationError):
            run_factor_backtest(_scores(), prices, rebalance_days=2, top_n=2)

    def test_invalid_parameters_raise(self) -> None:
        with pytest.raises(ValueError, match="top_n"):
            run_factor_backtest(_scores(), _prices(), rebalance_days=2, top_n=0)
        with pytest.raises(ValueError, match="rebalance_days"):
            run_factor_backtest(_scores(), _prices(), rebalance_days=0, top_n=2)

    def test_too_short_window_raises(self) -> None:
        prices = _prices().filter(pl.col("trade_date") <= _D1)
        scores = _scores().filter(pl.col("trade_date") <= _D1)
        with pytest.raises(DataValidationError):
            run_factor_backtest(scores, prices, rebalance_days=2, top_n=2)
