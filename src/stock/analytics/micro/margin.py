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


def _filter_complete_exchanges(df: pl.DataFrame) -> pl.DataFrame:
    """过滤确保交易日至少同时涵盖 SSE 与 SZSE 核心两市，避免单边残缺数据扭曲全市场口径。"""
    if "exchange_id" not in df.columns or df.is_empty():
        return df
    valid_dates = (
        df.filter(pl.col("exchange_id").is_in(["SSE", "SZSE"]))
        .group_by("trade_date")
        .agg(pl.col("exchange_id").n_unique().alias("ex_count"))
        .filter(pl.col("ex_count") >= 2)
        .select("trade_date")
    )
    return df.join(valid_dates, on="trade_date", how="inner")


def _resolve_margin_balance_expr(df: pl.DataFrame) -> pl.Expr | None:
    """提取两融总余额计算表达式 (优先 rzrqye 融资融券余额，或 rzye + rqye 合计)。"""
    if "rzrqye" in df.columns:
        return pl.col("rzrqye")
    if "rzye" in df.columns and "rqye" in df.columns:
        return pl.col("rzye") + pl.col("rqye")
    for col in ["rzrqye", "margin_balance", "balance", "total_balance", "rzye"]:
        if col in df.columns:
            return pl.col(col)
    return None


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
        raw_margin = (
            self.catalog.load_dataset("margin", start_date=start_date, end_date=end_date)
            if margin_df is None
            else margin_df
        )

        if raw_margin.is_empty():
            return pl.DataFrame()

        bal_expr = _resolve_margin_balance_expr(raw_margin)
        if bal_expr is None:
            return pl.DataFrame()

        filtered_margin = _filter_complete_exchanges(raw_margin)

        margin_clean = (
            filtered_margin.with_columns(bal_expr.alias("_bal"))
            .select(["trade_date", "_bal"])
            .drop_nulls(subset=["trade_date", "_bal"])
            .group_by("trade_date")
            .agg((pl.col("_bal").sum() / 1e8).alias("margin_balance_yi"))
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
