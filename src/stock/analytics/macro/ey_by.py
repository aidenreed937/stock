"""股债收益比 (Earnings Yield / Bond Yield Ratio, EY/BY) 计算器。

计算公式:
    EY = 1 / PE_TTM * 100%
    BY = 10年期中债国债到期收益率 (%)
    EY/BY Ratio = EY / BY
"""

from datetime import date

import polars as pl

from stock.analytics.models import EYBYRatioResult, ValuationZone
from stock.data.catalog import DataCatalog


def _evaluate_eyby_zone(ratio: float) -> tuple[ValuationZone, str, bool, bool]:
    """根据无量纲股债收益比评估估值区间与牛熊标尺。"""
    if ratio >= 2.2:
        desc = "战略级大熊底 (股票性价比极高，大级别高胜率高赔率)"
        return ValuationZone.EXTREME_LOW, desc, True, False
    if ratio >= 1.8:
        desc = "偏低估机会区 (权益资产吸引力显著高于债券)"
        return ValuationZone.LOW, desc, False, False
    if ratio >= 1.3:
        desc = "合理估值中枢 (股债配置均衡)"
        return ValuationZone.FAIR, desc, False, False
    if ratio >= 1.15:
        desc = "偏高估防御区 (股票风险溢价压缩，宜逐步收缩战线)"
        return ValuationZone.HIGH, desc, False, False
    desc = "大牛顶泡沫警戒 (股债收益率严重倒挂，强制战略避险)"
    return ValuationZone.EXTREME_HIGH, desc, False, True


def _extract_bond_yield_df(raw_bond: pl.DataFrame) -> pl.DataFrame:
    """从国债数据集中提取 10Y 国债收益率序列。"""
    bond_10y_col = None
    for col in ["ten_y", "10y", "y10", "yield_10y"]:
        if col in raw_bond.columns:
            bond_10y_col = col
            break

    if bond_10y_col is None:
        matching = [c for c in raw_bond.columns if "10" in c.lower()]
        if matching:
            bond_10y_col = matching[0]
        else:
            return pl.DataFrame()

    df = raw_bond.select(
        [
            pl.col("trade_date"),
            pl.col(bond_10y_col).cast(pl.Float64).alias("bond_yield_10y"),
        ]
    ).drop_nulls()

    # 若存储格式为小数 (如 0.021 代表 2.1%)，自动转换为百分比数值
    return df.with_columns(
        pl.when(pl.col("bond_yield_10y") < 0.2)
        .then(pl.col("bond_yield_10y") * 100.0)
        .otherwise(pl.col("bond_yield_10y"))
        .alias("bond_yield_10y")
    )


def _extract_index_pe_df(raw_idx: pl.DataFrame, symbol: str) -> pl.DataFrame:
    """从指数数据集中提取 PE-TTM 序列。"""
    pe_col = None
    for col in ["pe_ttm.mcw", "pe_ttm.ew", "pe_ttm", "pe"]:
        if col in raw_idx.columns:
            pe_col = col
            break

    if pe_col is None:
        return pl.DataFrame()

    sym_expr = (
        pl.col("symbol").cast(pl.Utf8).alias("symbol")
        if "symbol" in raw_idx.columns
        else pl.lit(symbol).alias("symbol")
    )

    return (
        raw_idx.select(
            [
                pl.col("trade_date"),
                sym_expr,
                pl.col(pe_col).cast(pl.Float64).alias("pe_ttm"),
            ]
        )
        .filter(pl.col("pe_ttm") > 0)
        .drop_nulls()
    )


class EYBYCalculator:
    """无量纲股债收益比 (EY/BY) 分析器。"""

    def __init__(self, catalog: DataCatalog | None = None) -> None:
        """初始化分析器。"""
        self.catalog = catalog or DataCatalog(data_source="lixinger")

    def calculate_series(
        self,
        symbol: str = "000300",
        start_date: date | None = None,
        end_date: date | None = None,
        index_df: pl.DataFrame | None = None,
        bond_df: pl.DataFrame | None = None,
    ) -> pl.DataFrame:
        """计算指定指数全历史或指定区间的每日股债收益比序列。"""
        if index_df is None:
            raw_idx = self.catalog.load_dataset(
                "index_fundamental", symbols=[symbol], start_date=start_date, end_date=end_date
            )
        else:
            raw_idx = (
                index_df.filter(pl.col("symbol") == symbol)
                if "symbol" in index_df.columns
                else index_df
            )

        if raw_idx.is_empty():
            return pl.DataFrame()

        raw_bond = (
            self.catalog.load_dataset("national_debt", start_date=start_date, end_date=end_date)
            if bond_df is None
            else bond_df
        )

        if raw_bond.is_empty():
            return pl.DataFrame()

        bond_clean = _extract_bond_yield_df(raw_bond)
        if bond_clean.is_empty():
            return pl.DataFrame()

        idx_clean = _extract_index_pe_df(raw_idx, symbol)
        if idx_clean.is_empty():
            return pl.DataFrame()

        joined = idx_clean.join(bond_clean, on="trade_date", how="inner").sort("trade_date")
        if joined.is_empty():
            return pl.DataFrame()

        return joined.with_columns(
            [
                (100.0 / pl.col("pe_ttm")).alias("earnings_yield"),
                ((100.0 / pl.col("pe_ttm")) / pl.col("bond_yield_10y")).alias("ey_by_ratio"),
            ]
        )

    def calculate_latest(
        self,
        symbol: str = "000300",
        target_date: date | None = None,
        window_years: int = 10,
    ) -> EYBYRatioResult | None:
        """计算指定日期的最新股债收益比及过去 10 年历史分位数。"""
        df = self.calculate_series(symbol=symbol)
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

        cur_ratio = float(latest_row["ey_by_ratio"])
        sample_size = len(window_df)
        if sample_size > 0:
            count_below = float(len(window_df.filter(pl.col("ey_by_ratio") <= cur_ratio)))
            percentile = round((count_below / sample_size) * 100.0, 2)
        else:
            percentile = 50.0

        zone, zone_desc, is_bottom, is_peak = _evaluate_eyby_zone(cur_ratio)

        return EYBYRatioResult(
            trade_date=cur_date,
            symbol=str(latest_row["symbol"]),
            pe_ttm=round(float(latest_row["pe_ttm"]), 2),
            earnings_yield=round(float(latest_row["earnings_yield"]), 2),
            bond_yield_10y=round(float(latest_row["bond_yield_10y"]), 3),
            ey_by_ratio=round(cur_ratio, 3),
            percentile_10y=percentile,
            zone=zone,
            zone_desc=zone_desc,
            is_strategic_bottom=is_bottom,
            is_bubble_peak=is_peak,
        )
