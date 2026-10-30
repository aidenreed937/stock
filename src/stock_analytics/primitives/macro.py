"""宏观总量、证券化率与利差原语 (Macro Primitives)。

本模块为纯函数、无状态数学原语，零内部业务依赖，仅依赖 Polars 与标准库。
涵盖宏观资产容量（证券化率）、收益率曲线斜率及宏观利差等物理指标计算。
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

import polars as pl


def _nth_weekday(year: int, month: int, weekday: int, ordinal: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + (ordinal - 1) * 7)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    last = date(year, month, monthrange(year, month)[1])
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed_fixed_date(year: int, month: int, day: int) -> date:
    holiday = date(year, month, day)
    if holiday.weekday() == 5:
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


def _us_federal_holidays(start_year: int, end_year: int) -> set[date]:
    holidays: set[date] = set()
    for year in range(start_year - 1, end_year + 2):
        holidays.update(
            {
                _observed_fixed_date(year, 1, 1),
                _observed_fixed_date(year, 7, 4),
                _observed_fixed_date(year, 12, 25),
                _nth_weekday(year, 11, 3, 4),
            }
        )
        if year >= 1986:
            holidays.add(_nth_weekday(year, 1, 0, 3))
        holidays.add(
            _nth_weekday(year, 2, 0, 3) if year >= 1971 else _observed_fixed_date(year, 2, 22)
        )
        holidays.add(
            _last_weekday(year, 5, 0) if year >= 1971 else _observed_fixed_date(year, 5, 30)
        )
        holidays.add(_nth_weekday(year, 9, 0, 1))
        holidays.add(
            _nth_weekday(year, 10, 0, 2) if year >= 1971 else _observed_fixed_date(year, 10, 12)
        )
        if year in range(1971, 1978):
            holidays.add(_nth_weekday(year, 10, 0, 4))
        else:
            holidays.add(_observed_fixed_date(year, 11, 11))
        if year >= 2021:
            holidays.add(_observed_fixed_date(year, 6, 19))
    return holidays


def _dff_market_availability_date(observation_date: date) -> date:
    cursor = observation_date + timedelta(days=1)
    holidays = _us_federal_holidays(observation_date.year, observation_date.year)
    while cursor.weekday() >= 5 or cursor in holidays:
        cursor += timedelta(days=1)
    # H.15 is released at 16:15 ET on the next Federal Reserve business day;
    # it is already the next calendar date in Beijing before the A-share close.
    return cursor + timedelta(days=1)


def add_dff_availability_date(
    df: pl.DataFrame,
    date_column: str = "trade_date",
    output_column: str = "available_date",
) -> pl.DataFrame:
    """按 H.15 下一个联储工作日发布时间映射 DFF 的 A 股可用日期。"""
    from datetime import date

    if df.is_empty() or date_column not in df.columns:
        return df
    dates = df[date_column].cast(pl.Date, strict=False).to_list()
    available_dates = [
        _dff_market_availability_date(value) if isinstance(value, date) else None for value in dates
    ]
    return df.with_columns(pl.Series(output_column, available_dates, dtype=pl.Date))


def calculate_dff_change_6m(df: pl.DataFrame) -> pl.DataFrame:
    """计算 DFF 当前值相对六个日历月前最近可用观测的变化（pp）。

    ``trade_date`` 输出为 DFF 数值对 A 股收盘可用的日期，原始观测日保存在
    ``observation_date``，避免日频 FRED 发布时差造成前视。
    """
    empty = pl.DataFrame(
        schema={
            "trade_date": pl.Date,
            "observation_date": pl.Date,
            "ffr_chg_6m": pl.Float64,
        }
    )
    if df.is_empty() or not {"trade_date", "value"}.issubset(df.columns):
        return empty

    source = (
        df.select(
            pl.col("trade_date").cast(pl.Date, strict=False),
            pl.col("value").cast(pl.Float64, strict=False),
        )
        .drop_nulls()
        .unique(subset=["trade_date"], keep="last")
        .sort("trade_date")
    )
    if source.is_empty():
        return empty
    source = add_dff_availability_date(source)

    prior = source.select(
        pl.col("trade_date").alias("_prior_date"),
        pl.col("value").alias("_prior_value"),
    ).sort("_prior_date")
    return (
        source.with_columns(pl.col("trade_date").dt.offset_by("-6mo").alias("_lookback_date"))
        .join_asof(
            prior,
            left_on="_lookback_date",
            right_on="_prior_date",
            strategy="backward",
        )
        .with_columns(
            pl.col("trade_date").alias("observation_date"),
            (pl.col("value") - pl.col("_prior_value")).alias("ffr_chg_6m"),
        )
        .drop_nulls(["_prior_value", "ffr_chg_6m"])
        .select(
            pl.col("available_date").alias("trade_date"),
            "observation_date",
            "ffr_chg_6m",
        )
        .sort("trade_date")
        .unique(subset=["trade_date"], keep="last")
    )


def calculate_securitization_ratio(
    total_market_cap_yi: float,
    gdp_ttm_yi: float,
) -> float:
    """计算证券化率（巴菲特指标：全市场股票总市值 / GDP TTM）。

    Args:
        total_market_cap_yi: 全市场总市值 (亿元)。
        gdp_ttm_yi: 滚动 4 季度 GDP TTM (亿元)。

    Returns:
        float: 证券化率百分比 (如 97.7 表示 97.7%)。若分母无效则返回 0.0。
    """
    if gdp_ttm_yi <= 0:
        return 0.0
    return (total_market_cap_yi / gdp_ttm_yi) * 100.0


def calculate_yield_curve_slope(
    df: pl.DataFrame,
    long_yield_col: str = "t10y",
    short_yield_col: str = "t2y",
) -> pl.DataFrame:
    """计算国债期限利差与收益率曲线斜率 (如 10Y - 2Y 利差)。

    Args:
        df: 包含长端和短端国债收益率的 DataFrame。
        long_yield_col: 长端国债收益率列名 (默认 "t10y")。
        short_yield_col: 短端国债收益率列名 (默认 "t2y")。

    Returns:
        pl.DataFrame: 附加了 yield_curve_slope_10y_2y 列的 DataFrame。
    """
    return calculate_macro_spread(
        df,
        higher_rate_col=long_yield_col,
        lower_rate_col=short_yield_col,
        spread_col_name="yield_curve_slope_10y_2y",
    )


def calculate_macro_spread(
    df: pl.DataFrame,
    higher_rate_col: str,
    lower_rate_col: str,
    spread_col_name: str = "macro_spread",
) -> pl.DataFrame:
    """计算通用宏观利差 (如信用利差、中美利差等)。

    Args:
        df: 包含两列利率数据的 DataFrame。
        higher_rate_col: 目标利率 A 列名。
        lower_rate_col: 基准利率 B 列名。
        spread_col_name: 输出的利差列名。

    Returns:
        pl.DataFrame: 附加了利差列的 DataFrame。
    """
    required = {higher_rate_col, lower_rate_col}
    if df.is_empty() or not required.issubset(df.columns):
        return df

    spread_expr = (pl.col(higher_rate_col) - pl.col(lower_rate_col)).alias(spread_col_name)
    return df.with_columns(spread_expr)


def consecutive_days(
    df: pl.DataFrame,
    col: str,
    threshold: float,
    trade_date_col: str = "trade_date",
    output_col: str | None = None,
) -> pl.DataFrame:
    """标记每个交易日该信号满足 ``col >= threshold`` 的连续天数 (含当日)。

    连续计数只在信号连续达标时累加，一旦回落（或数据缺失）即清零，天然刻画
    「内部人 / 聪明钱连续维持 N 天」的确认强度。缺失值按「未达标」处理，避免
    跨数据缺口误续连。

    Args:
        df: 需按 ``trade_date_col`` 升序排列的因子面板。
        col: 信号分位列名（如 ``insider_net_score``）。
        threshold: 达标阈值。
        trade_date_col: 排序/分组依据的交易日列名。
        output_col: 输出列名，默认 ``{col}_consec``。

    Returns:
        pl.DataFrame: 原面板附加 ``output_col`` 列（原列只读、不覆盖）。
    """
    if df.is_empty() or col not in df.columns:
        return df
    name = output_col or f"{col}_consec"
    hit = (
        pl.when(pl.col(col).is_null())
        .then(False)
        .otherwise(pl.col(col) >= threshold)
        .cast(pl.Int64)
        .alias("_hit_int")
    )
    # 命中/未命中每次切换都新开一组；组内累计即「连续达标天数」
    group = (
        pl.when(pl.col("_hit_int") != pl.col("_hit_int").shift(1).fill_null(0))
        .then(1)
        .otherwise(0)
        .cum_sum()
        .alias("_group")
    )
    consec = pl.col("_hit_int").cum_sum().over("_group", order_by=trade_date_col).alias(name)
    return df.with_columns(hit).with_columns(group).with_columns(consec).drop("_hit_int", "_group")


__all__ = [
    "calculate_macro_spread",
    "calculate_securitization_ratio",
    "calculate_yield_curve_slope",
    "consecutive_days",
]
