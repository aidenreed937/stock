"""行业高低切换动量剪刀差分析器 (Momentum Spread Engine)。

计算逻辑:
    监控 120D 领跑行业与 20D 超跌行业之间的动量反转剪刀差，
    捕捉资金从高位高拥挤板块向低位超跌板块溢出的结构性轮动信号。
"""

from datetime import date
from typing import cast

import polars as pl

from stock.analytics.domains.industry.classifier import IndustryClassifier
from stock.analytics.models import MomentumSpreadResult
from stock.data.catalog import DataCatalog

__all__ = ["IndustryMomentumSpreadAnalyzer"]


class IndustryMomentumSpreadAnalyzer:
    """行业动量反转剪刀差分析器。"""

    def __init__(self, catalog: DataCatalog | None = None) -> None:
        """初始化分析器。"""
        self.catalog = catalog or DataCatalog(data_source="tushare")

    def calculate_spread(
        self,
        target_date: date | None = None,
        sw_daily_df: pl.DataFrame | None = None,
        long_window: int = 120,
        short_window: int = 20,
    ) -> MomentumSpreadResult | None:
        """计算行业动量剪刀差。"""
        raw_sw = self.catalog.load_dataset("sw_daily") if sw_daily_df is None else sw_daily_df
        if raw_sw.is_empty():
            return None

        if target_date is not None:
            raw_sw = raw_sw.filter(pl.col("trade_date") <= target_date)

        max_d = raw_sw["trade_date"].max()
        if max_d is None:
            return None
        eval_date = max_d if isinstance(max_d, date) else date.fromisoformat(str(max_d))

        classifier = IndustryClassifier(self.catalog)
        l1_codes = list(classifier.get_l1_codes())
        filtered_l1 = raw_sw.filter(pl.col("symbol").is_in(l1_codes))
        l1_df = (
            filtered_l1.sort(["symbol", "trade_date"])
            if filtered_l1["symbol"].n_unique() >= 10
            else raw_sw.sort(["symbol", "trade_date"])
        )

        returns_df = (
            l1_df.with_columns(
                [
                    ((pl.col("close") / pl.col("close").shift(long_window) - 1.0) * 100.0)
                    .over("symbol")
                    .alias("ret_120d"),
                    ((pl.col("close") / pl.col("close").shift(short_window) - 1.0) * 100.0)
                    .over("symbol")
                    .alias("ret_20d"),
                ]
            )
            .filter(pl.col("trade_date") == eval_date)
            .drop_nulls(subset=["ret_120d", "ret_20d"])
        )

        if len(returns_df) < 10:
            return None

        top_120 = returns_df.sort("ret_120d", descending=True).head(5)
        bot_20 = returns_df.sort("ret_20d", descending=False).head(5)

        m_top = top_120["ret_120d"].mean()
        m_bot = bot_20["ret_20d"].mean()
        avg_top_120 = float(cast("float", m_top)) if m_top is not None else 0.0
        avg_bot_20 = float(cast("float", m_bot)) if m_bot is not None else 0.0
        spread = round(avg_top_120 - avg_bot_20, 2)

        is_imminent = bool(spread >= 35.0)
        if is_imminent:
            diag = (
                f"动量剪刀差达 {spread:.1f}% (>=35%)，领跑板块亢奋，超跌板块性价比显现，"
                f"资金高低切换概率极高"
            )
        else:
            diag = f"动量剪刀差为 {spread:.1f}%，行业分化处于常态区间"

        return MomentumSpreadResult(
            trade_date=eval_date,
            top_leaders_120d=[
                {"symbol": r["symbol"], "ret_120d": round(float(r["ret_120d"]), 2)}
                for r in top_120.to_dicts()
            ],
            bottom_laggards_20d=[
                {"symbol": r["symbol"], "ret_20d": round(float(r["ret_20d"]), 2)}
                for r in bot_20.to_dicts()
            ],
            spread=spread,
            is_switch_imminent=is_imminent,
            diagnostics=diag,
        )
