"""证券化率 (巴菲特指标 A 股总市值 / GDP TTM) 计算器。

计算公式:
    证券化率 = (全市场 A 股总市值 / 滚动 4 季度 GDP TTM) * 100%
"""

from datetime import date

import polars as pl

from stock.analytics.models import BuffettRatioResult, ValuationZone
from stock.data.catalog import DataCatalog


def _evaluate_buffett_zone(ratio: float) -> tuple[ValuationZone, str, bool, bool]:
    """根据 A 股本土化证券化率评估牛熊估值区间。"""
    if ratio < 65.0:
        desc = "历史黄金建仓大底带 (<65%，全市场资产深度折价)"
        return ValuationZone.EXTREME_LOW, desc, True, False
    if ratio < 75.0:
        desc = "偏低估安全带 (具备较好长期配置价值)"
        return ValuationZone.LOW, desc, False, False
    if ratio <= 86.0:
        desc = "合理估值中枢带 (经济总量与资产定价匹配)"
        return ValuationZone.FAIR, desc, False, False
    if ratio <= 100.0:
        desc = "偏高估过热区 (资产膨胀快于实体产出，需防范估值收缩)"
        return ValuationZone.HIGH, desc, False, False
    desc = "极端泡沫过热区 (>100%，系统性脱离基本面支撑)"
    return ValuationZone.EXTREME_HIGH, desc, False, True


def _q_to_date(q_str: str) -> date:
    """将季度字符串转换为大致发布日期。"""
    try:
        yr = int(q_str[:4])
        q = q_str[4:]
        if "1" in q:
            return date(yr, 4, 15)
        if "2" in q:
            return date(yr, 7, 15)
        if "3" in q:
            return date(yr, 10, 15)
        return date(yr + 1, 1, 15)
    except Exception:
        return date(2020, 1, 1)


def _annualize_gdp(q_str: str, val: float) -> float:
    """根据 TuShare 季度累计 GDP 计算年化 GDP TTM (亿元)。"""
    try:
        q = str(q_str).upper()
        if "Q1" in q or "1" in q[-2:]:
            return val * 4.0
        if "Q2" in q or "2" in q[-2:]:
            return (val / 2.0) * 4.0
        if "Q3" in q or "3" in q[-2:]:
            return (val / 3.0) * 4.0
        return val  # Q4 为全年累计
    except Exception:
        return val if val > 500000.0 else val * 4.0


def _process_gdp_ttm_df(raw_gdp: pl.DataFrame) -> pl.DataFrame:
    """计算滚动 4 季度 GDP TTM 序列并关联有效日期。"""
    gdp_val_col = None
    for col in ["gdp", "gdp_yoy", "val"]:
        if col in raw_gdp.columns:
            gdp_val_col = col
            break

    if gdp_val_col is None:
        gdp_val_col = next(
            (c for c in raw_gdp.columns if c not in ["quarter", "pub_date", "trade_date"]),
            "gdp",
        )

    gdp_sorted = raw_gdp.sort("quarter" if "quarter" in raw_gdp.columns else "trade_date")

    # 根据 quarter 和累计值年化 GDP TTM
    if "quarter" in gdp_sorted.columns:
        ttm_vals = [
            _annualize_gdp(str(row["quarter"]), float(row[gdp_val_col]))
            for row in gdp_sorted.to_dicts()
        ]
        dates = [_q_to_date(str(q)) for q in gdp_sorted["quarter"].to_list()]
        gdp_ttm_df = gdp_sorted.with_columns(
            [
                pl.Series("gdp_ttm_yi", ttm_vals),
                pl.Series("effective_date", dates),
            ]
        )
    else:
        gdp_ttm_df = gdp_sorted.with_columns(
            pl.col(gdp_val_col).cast(pl.Float64).rolling_sum(window_size=4).alias("gdp_ttm_yi")
        ).drop_nulls(subset=["gdp_ttm_yi"])
        if "pub_date" in gdp_ttm_df.columns:
            gdp_ttm_df = gdp_ttm_df.with_columns(
                pl.col("pub_date").cast(pl.Date).alias("effective_date")
            )
        else:
            gdp_ttm_df = gdp_ttm_df.with_columns(
                pl.col("trade_date").cast(pl.Date).alias("effective_date")
            )

    return gdp_ttm_df.select(["effective_date", "gdp_ttm_yi"]).sort("effective_date")


class BuffettIndicatorCalculator:
    """A 股证券化率 (总市值 / GDP TTM) 分析器。"""

    def __init__(self, catalog: DataCatalog | None = None) -> None:
        """初始化分析器。"""
        self.catalog = catalog or DataCatalog(data_source="tushare")

    def calculate_series(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        daily_basic_df: pl.DataFrame | None = None,
        gdp_df: pl.DataFrame | None = None,
    ) -> pl.DataFrame:
        """计算指定时间段内的每日全市场总市值与证券化率。"""
        raw_basic = (
            self.catalog.load_dataset("daily_basic", start_date=start_date, end_date=end_date)
            if daily_basic_df is None
            else daily_basic_df
        )
        if raw_basic.is_empty():
            return pl.DataFrame()

        # Curated 层 total_mv 单位为元 -> 转换为亿元 (除以 1e8)
        daily_mv = (
            raw_basic.select(["trade_date", "total_mv"])
            .drop_nulls()
            .group_by("trade_date")
            .agg((pl.col("total_mv").sum() / 1e8).alias("total_market_cap_yi"))
            .sort("trade_date")
        )
        if daily_mv.is_empty():
            return pl.DataFrame()

        raw_gdp = self.catalog.load_dataset("cn_gdp") if gdp_df is None else gdp_df
        if raw_gdp.is_empty():
            return pl.DataFrame()

        gdp_clean = _process_gdp_ttm_df(raw_gdp)
        daily_joined = daily_mv.join_asof(
            gdp_clean, left_on="trade_date", right_on="effective_date", strategy="backward"
        ).drop_nulls(subset=["gdp_ttm_yi"])

        if daily_joined.is_empty():
            return pl.DataFrame()

        return daily_joined.with_columns(
            ((pl.col("total_market_cap_yi") / pl.col("gdp_ttm_yi")) * 100.0).alias(
                "securitization_ratio"
            )
        ).select(["trade_date", "total_market_cap_yi", "gdp_ttm_yi", "securitization_ratio"])

    def calculate_latest(
        self,
        target_date: date | None = None,
        window_years: int = 10,
        daily_basic_df: pl.DataFrame | None = None,
    ) -> BuffettRatioResult | None:
        """计算指定日期的最新证券化率及历史百分位。"""
        df = self.calculate_series(end_date=target_date, daily_basic_df=daily_basic_df)
        if df.is_empty():
            return None

        if target_date is not None:
            df = df.filter(pl.col("trade_date") <= target_date)
            if df.is_empty():
                return None

        latest_row = df.tail(1).to_dicts()[0]
        cur_date: date = latest_row["trade_date"]
        start_year = cur_date.year - window_years
        window_df = df.filter(pl.col("trade_date").dt.year() >= start_year)

        cur_ratio = float(latest_row["securitization_ratio"])
        sample_size = len(window_df)
        if sample_size > 0:
            count_below = float(len(window_df.filter(pl.col("securitization_ratio") <= cur_ratio)))
            percentile = round((count_below / sample_size) * 100.0, 2)
        else:
            percentile = 50.0

        zone, zone_desc, is_bottom, is_peak = _evaluate_buffett_zone(cur_ratio)

        return BuffettRatioResult(
            trade_date=cur_date,
            total_market_cap_yi=round(float(latest_row["total_market_cap_yi"]), 2),
            gdp_ttm_yi=round(float(latest_row["gdp_ttm_yi"]), 2),
            securitization_ratio=round(cur_ratio, 2),
            percentile_10y=percentile,
            zone=zone,
            zone_desc=zone_desc,
            is_golden_bottom=is_bottom,
            is_bubble_overheat=is_peak,
        )
