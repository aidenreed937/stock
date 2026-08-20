"""全市场聚合短期趋势测试。"""

from datetime import datetime
from zoneinfo import ZoneInfo

import polars as pl

from stock_analytics.pipelines.market_aggregate.trend import (
    build_short_term_trend,
    build_trend_facts,
)
from stock_data.fetcher.realtime.market_aggregate import MarketAggregateSnapshot

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


class _Catalog:
    def __init__(self) -> None:
        rows: list[dict[str, object]] = []
        changes = {
            "2026-08-14": (1.0, -1.0),
            "2026-08-17": (2.0, 1.0),
            "2026-08-18": (-1.0, -2.0),
            "2026-08-19": (3.0, 4.0),
        }
        for trade_date, values in changes.items():
            for index, symbol in enumerate(("000001.SZ", "600000.SH")):
                rows.append(
                    {
                        "trade_date": trade_date,
                        "symbol": symbol,
                        "close": 10.0,
                        "pre_close": 10.0,
                        "pct_chg": values[index],
                        "amount": 100.0 * (index + 1),
                    }
                )
        self.bars = pl.DataFrame(rows)
        self.basic = pl.DataFrame(
            [
                {
                    "trade_date": trade_date,
                    "symbol": symbol,
                    "circ_mv": 1_000.0,
                    "total_mv": 1_200.0,
                }
                for trade_date in changes
                for symbol in ("000001.SZ", "600000.SH")
            ]
        )

    def load_dataset(self, dataset: str, **_: object) -> pl.DataFrame:
        return self.bars if dataset == "stock_daily_bar" else self.basic


def _current_snapshot() -> MarketAggregateSnapshot:
    return MarketAggregateSnapshot(
        status="valid",
        quote_at=datetime(2026, 8, 20, 10, 0, tzinfo=_SHANGHAI_TZ),
        received_at=datetime(2026, 8, 20, 10, 0, tzinfo=_SHANGHAI_TZ),
        reported_count=2,
        returned_count=2,
        priced_count=2,
        change_count=2,
        amount_count=2,
        market_cap_count=2,
        coverage_ratio=1.0,
        advance_count=2,
        decline_count=0,
        flat_count=0,
        advance_share=1.0,
        decline_share=0.0,
        advance_decline_ratio=None,
        strong_up_threshold_pct=5.0,
        strong_up_count=0,
        strong_down_count=0,
        strong_up_share=0.0,
        strong_down_share=0.0,
        median_pct_change=2.5,
        pct_change_p25=2.0,
        pct_change_p75=3.0,
        weighted_pct_change=2.67,
        amount_total_yuan=300.0,
        total_market_value_yuan=2_400.0,
        free_float_market_value_yuan=2_000.0,
        free_float_turnover_pct=15.0,
        amount_top_5pct_share=1.0,
    )


def test_build_short_term_trend_uses_four_local_trade_days() -> None:
    trend = build_short_term_trend(_Catalog(), _current_snapshot())

    assert trend["status"] == "available"
    assert trend["history_dates"] == [
        "2026-08-14",
        "2026-08-17",
        "2026-08-18",
        "2026-08-19",
    ]
    assert [row["date"] for row in trend["rows"]] == [
        "2026-08-14",
        "2026-08-17",
        "2026-08-18",
        "2026-08-19",
        "2026-08-20",
    ]
    assert trend["summary"]["direction"] == "improving"
    assert trend["summary"]["current_vs_history_average"]["advance_share_change_pp"] > 0
    comparison = trend["summary"]["current_vs_history_average"]
    assert comparison["amount_comparison"] == "not_comparable_intraday_vs_full_day"
    assert "amount_change_pct" not in comparison
    assert "amount_top_5pct_share_change_pp" in comparison

    facts = build_trend_facts(trend)
    assert facts.height == 5
    assert facts["date"].to_list()[-1] == "2026-08-20"
    assert "strong_up_share" in facts.columns
