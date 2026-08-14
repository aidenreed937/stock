"""两融杠杆渗透率 (Margin Penetration Ratio) 分析器。

计算公式:
    两融渗透率 = (全市场两融总余额 / 全市场自由流通总市值) * 100%
牛熊标尺:
    < 2.2%: 杠杆彻底出清大底 (去杠杆充分，筹码结构纯净)
    > 3.5%: 杠杆过载脆弱区 (高位踩踏风险陡增，短线波动放大)
"""

from datetime import date

import polars as pl

from stock.analytics.models import MarginPenetrationResult
from stock.data.catalog import DataCatalog


class MarginPenetrationCalculator:
    """全市场两融杠杆渗透率分析器。"""

    def __init__(self, catalog: DataCatalog | None = None) -> None:
        """初始化分析器。"""
        self.catalog = catalog or DataCatalog(data_source="tushare")

    def calculate_series(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        margin_df: pl.DataFrame | None = None,
        daily_basic_df: pl.DataFrame | None = None,
    ) -> pl.DataFrame:
        """计算每日两融渗透率序列。"""
        # 1. 加载两融全市场总量数据 (margin)
        if margin_df is None:
            raw_margin = self.catalog.load_dataset(
                "margin", start_date=start_date, end_date=end_date
            )
        else:
            raw_margin = margin_df

        if raw_margin.is_empty():
            return pl.DataFrame()

        # 提取两融总余额 (rzye + rqye 或 rzye, 单位一般为元)
        bal_col = None
        for col in ["rzye", "margin_balance", "balance", "total_balance"]:
            if col in raw_margin.columns:
                bal_col = col
                break

        if bal_col is None:
            return pl.DataFrame()

        # 按 trade_date 汇总两融余额 (元 -> 亿元)
        margin_clean = (
            raw_margin.select(["trade_date", bal_col])
            .drop_nulls()
            .group_by("trade_date")
            .agg((pl.col(bal_col).sum() / 1e8).alias("margin_balance_yi"))
            .sort("trade_date")
        )

        # 2. 加载全市场流通市值 (daily_basic circ_mv 单位: 万元 -> 亿元)
        if daily_basic_df is None:
            raw_basic = self.catalog.load_dataset(
                "daily_basic", start_date=start_date, end_date=end_date
            )
        else:
            raw_basic = daily_basic_df

        if raw_basic.is_empty():
            return pl.DataFrame()

        circ_clean = (
            raw_basic.select(["trade_date", "circ_mv"])
            .drop_nulls()
            .group_by("trade_date")
            .agg((pl.col("circ_mv").sum() / 1e8).alias("circ_mv_yi"))
            .sort("trade_date")
        )

        # 3. 按 trade_date 关联并计算渗透率
        joined = margin_clean.join(circ_clean, on="trade_date", how="inner").sort("trade_date")
        if joined.is_empty():
            return pl.DataFrame()

        return joined.with_columns(
            ((pl.col("margin_balance_yi") / pl.col("circ_mv_yi")) * 100.0).alias(
                "margin_penetration"
            )
        )

    def calculate_latest(
        self,
        target_date: date | None = None,
        margin_df: pl.DataFrame | None = None,
        daily_basic_df: pl.DataFrame | None = None,
    ) -> MarginPenetrationResult | None:
        """计算指定日期的最新两融杠杆渗透率。"""
        df = self.calculate_series(
            end_date=target_date, margin_df=margin_df, daily_basic_df=daily_basic_df
        )
        if df.is_empty():
            return None

        if target_date is not None:
            df = df.filter(pl.col("trade_date") <= target_date)
            if df.is_empty():
                return None

        latest_row = df.tail(1).to_dicts()[0]
        cur_date: date = latest_row["trade_date"]
        ratio = float(latest_row["margin_penetration"])
        margin_yi = float(latest_row["margin_balance_yi"])
        circ_yi = float(latest_row["circ_mv_yi"])

        is_cleared = ratio < 2.2
        is_overloaded = ratio > 3.5

        if is_cleared:
            zone_desc = "杠杆彻底出清底 (<2.2%，筹码结构纯净，无强平负反馈风险)"
        elif ratio < 2.8:
            zone_desc = "杠杆温和健康带 (2.2%~2.8%，资金情绪适中)"
        elif ratio <= 3.5:
            zone_desc = "杠杆活跃偏热带 (2.8%~3.5%，游资与高贝塔品种博弈活跃)"
        else:
            zone_desc = "杠杆过载脆弱区 (>3.5%，杠杆盘过度拥挤，极易诱发集中踩踏)"

        return MarginPenetrationResult(
            trade_date=cur_date,
            margin_balance_yi=round(margin_yi, 2),
            circ_mv_yi=round(circ_yi, 2),
            margin_penetration=round(ratio, 2),
            is_cleared_bottom=is_cleared,
            is_overloaded_peak=is_overloaded,
            zone_desc=zone_desc,
        )
