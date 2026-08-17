"""全市场破净率与自由流通换手率极值情绪分析器。

监控逻辑:
    1. 全市场破净率 (PB < 1.0 比例):
       - > 10% ~ 15%: 资产全面折价大底 (历史极值大熊底特征)
       - < 1% ~ 2%: 全线泡沫化
    2. 自由流通市值换手率:
       - < 2.0% ~ 2.3%: 地量见地价 (筹码充分锁定，大底前夜)
       - > 5.0% ~ 6.0%: 天量见天价 (主力加速派发，短线极度亢奋)
"""

from datetime import date

import polars as pl

from stock.analytics.models import MarketSentimentResult
from stock.data.catalog import DataCatalog


class MarketSentimentAnalyzer:
    """全市场破净率与换手率极值分析器。"""

    def __init__(self, catalog: DataCatalog | None = None) -> None:
        """初始化分析器。"""
        self.catalog = catalog or DataCatalog(data_source="tushare")

    def calculate_series(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        daily_basic_df: pl.DataFrame | None = None,
    ) -> pl.DataFrame:
        """计算每日破净率与平均换手率序列。"""
        if daily_basic_df is None:
            raw_basic = self.catalog.load_dataset(
                "daily_basic", start_date=start_date, end_date=end_date
            )
        else:
            raw_basic = daily_basic_df

        if raw_basic.is_empty():
            return pl.DataFrame()

        # 提取 PB 与 换手率列
        turnover_col = None
        for col in ["turnover_rate_f", "turnover_rate", "turnover"]:
            if col in raw_basic.columns:
                turnover_col = col
                break

        if turnover_col is None:
            turnover_col = "turnover_rate"

        turnover_expr = (
            pl.col(turnover_col).cast(pl.Float64).alias("turnover")
            if turnover_col in raw_basic.columns
            else pl.lit(2.5).alias("turnover")
        )

        clean = raw_basic.select(
            [
                pl.col("trade_date"),
                pl.col("symbol"),
                pl.col("pb").cast(pl.Float64),
                turnover_expr,
            ]
        ).drop_nulls(subset=["trade_date", "pb"])

        if clean.is_empty():
            return pl.DataFrame()

        pb_broken_expr = ((pl.col("pb") < 1.0) & (pl.col("pb") > 0)).sum()

        return (
            clean.group_by("trade_date")
            .agg(
                [
                    pl.count("symbol").alias("total_stocks"),
                    pb_broken_expr.cast(pl.Int64).alias("pb_broken_count"),
                    (pb_broken_expr / pl.count("symbol") * 100.0).alias("pb_break_ratio"),
                    pl.col("turnover").mean().alias("turnover_ratio"),
                ]
            )
            .sort("trade_date")
        )

    def diagnose_latest(
        self,
        target_date: date | None = None,
        sentiment_df: pl.DataFrame | None = None,
        daily_basic_df: pl.DataFrame | None = None,
    ) -> MarketSentimentResult | None:
        """诊断指定日期的破净率与换手率情绪极值。"""
        if sentiment_df is None:
            df = self.calculate_series(end_date=target_date, daily_basic_df=daily_basic_df)
        else:
            df = sentiment_df
        if df.is_empty():
            return None

        if target_date is not None:
            df = df.filter(pl.col("trade_date") <= target_date)
            if df.is_empty():
                return None

        latest_row = df.tail(1).to_dicts()[0]
        cur_date: date = latest_row["trade_date"]
        pb_ratio = float(latest_row["pb_break_ratio"])
        turnover = float(latest_row["turnover_ratio"])

        is_shrink = turnover < 2.3
        is_huge = turnover > 5.5
        is_broken = pb_ratio > 10.0

        diagnostics: list[str] = []
        if is_broken:
            diagnostics.append(
                f"【破净大底】全市场破净率达 {pb_ratio:.2f}% (>10%)，资产出现大面积清算折价"
            )
        elif pb_ratio < 1.5:
            diagnostics.append(f"全市场破净率仅 {pb_ratio:.2f}% (<1.5%)，全线资产估值饱满")

        if is_shrink:
            diagnostics.append(
                f"【地量地价】全市场平均换手率低至 {turnover:.2f}% (<2.3%)，抛压彻底衰竭"
            )
        elif is_huge:
            diagnostics.append(
                f"【天量天价】全市场平均换手率高达 {turnover:.2f}% (>5.5%)，短线情绪极度亢奋"
            )
        else:
            diagnostics.append(f"市场换手率处于常态中枢 ({turnover:.2f}%)")

        return MarketSentimentResult(
            trade_date=cur_date,
            pb_break_ratio=round(pb_ratio, 2),
            turnover_ratio=round(turnover, 2),
            is_shrink_volume_bottom=is_shrink,
            is_huge_volume_peak=is_huge,
            is_wide_pb_broken_bottom=is_broken,
            diagnostics=diagnostics,
        )
