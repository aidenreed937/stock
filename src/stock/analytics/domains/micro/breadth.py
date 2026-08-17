"""多周期市场宽度 (Market Breadth) 与顶底背离诊断分析器。

监控维度:
    1. 站上 MA20 比例 (短线进攻情绪)
    2. 站上 MA60 比例 (中期生命线健康度)
    3. 站上 MA120 比例 (半年线大趋势)
背离诊断:
    - 宽度底背离: 指数破位新低，但 MA60 站上率从冰点 (<15%) 逆势企稳回升
    - 宽度顶背离: 指数新高突破，但 MA20 站上率大幅衰竭跌破 50%
"""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from stock.analytics.models import MarketBreadthResult
from stock.data.catalog import DataCatalog


def _detect_breadth_divergences(
    recent_df: pl.DataFrame,
    index_df: pl.DataFrame | None,
    cur_date: date,
    lookback_days: int,
) -> tuple[bool, bool, list[str]]:
    """检测市场宽度的顶底背离信号。"""
    is_bottom_div = False
    is_top_div = False
    diagnostics: list[str] = []

    if len(recent_df) < 10 or index_df is None or index_df.is_empty():
        return is_bottom_div, is_top_div, diagnostics

    r20 = float(recent_df["above_ma20_ratio"].to_list()[-1])
    r60 = float(recent_df["above_ma60_ratio"].to_list()[-1])

    idx_sub = (
        index_df.filter(pl.col("trade_date") <= cur_date).sort("trade_date").tail(lookback_days)
    )
    if len(idx_sub) < 10:
        return is_bottom_div, is_top_div, diagnostics

    idx_closes = idx_sub["close"].to_list()
    idx_cur = idx_closes[-1]
    idx_min, idx_max = min(idx_closes[:-1]), max(idx_closes[:-1])

    # 底背离判断
    r60_series = recent_df["above_ma60_ratio"].to_list()
    r60_min = min(r60_series)
    if idx_cur <= idx_min and (r60 - r60_min) >= 8.0 and r60_min < 20.0:
        is_bottom_div = True
        diagnostics.append(
            f"【宽度底背离】指数创新低 ({idx_cur:.1f})，但 MA60 宽度从"
            f"冰点 ({r60_min:.1f}%) 逆势回升至 {r60:.1f}%，具备左侧见底特征"
        )

    # 顶背离判断
    r20_series = recent_df["above_ma20_ratio"].to_list()
    r20_max = max(r20_series)
    if idx_cur >= idx_max and r20 < 50.0 and (r20_max - r20) >= 20.0:
        is_top_div = True
        diagnostics.append(
            f"【宽度顶背离】指数创新高 ({idx_cur:.1f})，但 MA20 站上率"
            f"大幅退潮至 {r20:.1f}% (<50%)，属于少数权重掩护派发"
        )

    return is_bottom_div, is_top_div, diagnostics


def _append_status_diagnostics(diags: list[str], r20: float, r60: float, r120: float) -> None:
    """根据最新均线站上比例追加状态诊断。"""
    if r60 < 15.0:
        diags.append(f"MA60 站上率仅 {r60:.1f}% (<15%)，全市场处于极度超跌冰点区")
    elif r20 > 80.0:
        diags.append(f"MA20 站上率高达 {r20:.1f}% (>80%)，短线情绪极度亢奋过热")
    else:
        diags.append(
            f"市场宽度处于常态区间 (MA20: {r20:.1f}%, MA60: {r60:.1f}%, MA120: {r120:.1f}%)"
        )


class MultiPeriodMarketBreadthAnalyzer:
    """多周期全市场宽度与背离诊断分析器。"""

    def __init__(self, catalog: DataCatalog | None = None) -> None:
        """初始化分析器。"""
        self.catalog = catalog or DataCatalog(data_source="tushare")

    def calculate_breadth_series(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        bars_df: pl.DataFrame | None = None,
    ) -> pl.DataFrame:
        """计算全市场多周期宽度时间序列。"""
        raw_bars = (
            self.catalog.load_bars(start_date=start_date, end_date=end_date)
            if bars_df is None
            else bars_df
        )
        if raw_bars.is_empty():
            return pl.DataFrame()

        sorted_bars = raw_bars.select(["symbol", "trade_date", "close"]).sort(
            ["symbol", "trade_date"]
        )

        df_with_ma = sorted_bars.with_columns(
            [
                pl.col("close").rolling_mean(window_size=20).over("symbol").alias("ma20"),
                pl.col("close").rolling_mean(window_size=60).over("symbol").alias("ma60"),
                pl.col("close").rolling_mean(window_size=120).over("symbol").alias("ma120"),
            ]
        )

        flags = df_with_ma.with_columns(
            [
                (pl.col("close") > pl.col("ma20")).alias("above_ma20"),
                (pl.col("close") > pl.col("ma60")).alias("above_ma60"),
                (pl.col("close") > pl.col("ma120")).alias("above_ma120"),
            ]
        )

        aggregated = (
            flags.group_by("trade_date")
            .agg(
                [
                    pl.count("symbol").alias("total_stocks"),
                    pl.col("above_ma20").sum().alias("cnt_ma20"),
                    pl.col("above_ma60").sum().alias("cnt_ma60"),
                    pl.col("above_ma120").sum().alias("cnt_ma120"),
                ]
            )
            .sort("trade_date")
        )

        return aggregated.with_columns(
            [
                (pl.col("cnt_ma20") / pl.col("total_stocks") * 100.0).alias("above_ma20_ratio"),
                (pl.col("cnt_ma60") / pl.col("total_stocks") * 100.0).alias("above_ma60_ratio"),
                (pl.col("cnt_ma120") / pl.col("total_stocks") * 100.0).alias("above_ma120_ratio"),
            ]
        ).drop(["cnt_ma20", "cnt_ma60", "cnt_ma120"])

    def _resolve_breadth_df(
        self,
        target_date: date | None,
        lookback_days: int,
        bars_df: pl.DataFrame | None,
        breadth_df: pl.DataFrame | None,
    ) -> pl.DataFrame:
        """解析获取计算所用的宽度序列 DataFrame。"""
        if breadth_df is not None:
            df = breadth_df
        elif bars_df is not None:
            df = self.calculate_breadth_series(bars_df=bars_df)
        else:
            end_d = target_date or date.today()
            start_d = end_d - timedelta(days=lookback_days * 3)
            df = self.calculate_breadth_series(start_date=start_d, end_date=end_d)

        if target_date and not df.is_empty():
            df = df.filter(pl.col("trade_date") <= target_date)
        return df

    def diagnose_latest(
        self,
        target_date: date | None = None,
        lookback_days: int = 60,
        index_df: pl.DataFrame | None = None,
        bars_df: pl.DataFrame | None = None,
        breadth_df: pl.DataFrame | None = None,
    ) -> MarketBreadthResult | None:
        """针对指定交易日或最新一日输出综合广度诊断与背离信号。"""
        df = self._resolve_breadth_df(target_date, lookback_days, bars_df, breadth_df)
        if df.is_empty():
            return None

        latest_row = df.tail(1).to_dicts()[0]
        cur_date = latest_row["trade_date"]
        total_stocks = int(latest_row["total_stocks"])
        r20 = float(latest_row["above_ma20_ratio"])
        r60 = float(latest_row["above_ma60_ratio"])
        r120 = float(latest_row["above_ma120_ratio"])

        if index_df is None:
            try:
                index_df = self.catalog.load_dataset(
                    "index_daily", symbols=["000001.SH", "000300.SH"]
                )
            except Exception:
                index_df = pl.DataFrame()

        is_bot, is_top, diags = _detect_breadth_divergences(
            df.tail(lookback_days), index_df, cur_date, lookback_days
        )
        _append_status_diagnostics(diags, r20, r60, r120)

        return MarketBreadthResult(
            trade_date=cur_date,
            total_stocks=total_stocks,
            above_ma20_ratio=round(r20, 2),
            above_ma60_ratio=round(r60, 2),
            above_ma120_ratio=round(r120, 2),
            is_bottom_divergence=is_bot,
            is_top_divergence=is_top,
            diagnostics=diags,
        )


__all__ = ["MultiPeriodMarketBreadthAnalyzer"]
