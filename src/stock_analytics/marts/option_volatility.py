"""基于期权结算价的隐含波动率代理 Mart。"""

from __future__ import annotations

import math

import polars as pl

from stock_data.pipeline.cleaner.date_utils import parse_mixed_date

SETTLEMENT_IV_PROXY_MART_NAME = "settlement_iv_proxy_daily"
DEFAULT_UNDERLYINGS = ("510050.SH", "510300.SH", "000300.SH")


def _empty_mart() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "trade_date": pl.Date,
            "underlying_symbol": pl.Utf8,
            "settlement_iv_proxy_median": pl.Float64,
            "settlement_iv_proxy_call_median": pl.Float64,
            "settlement_iv_proxy_put_median": pl.Float64,
            "settlement_iv_proxy_put_call_skew": pl.Float64,
            "settlement_iv_proxy_valid_count": pl.Int64,
            "settlement_iv_proxy_call_count": pl.Int64,
            "settlement_iv_proxy_put_count": pl.Int64,
            "risk_free_rate": pl.Float64,
        }
    )


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _black_scholes_price(
    spot: float,
    strike: float,
    time_years: float,
    rate: float,
    volatility: float,
    call_put: str,
) -> float:
    if time_years <= 0.0:
        intrinsic = max(spot - strike, 0.0) if call_put == "C" else max(strike - spot, 0.0)
        return intrinsic
    root_time = math.sqrt(time_years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * volatility * volatility) * time_years) / (
        volatility * root_time
    )
    d2 = d1 - volatility * root_time
    discount = math.exp(-rate * time_years)
    if call_put == "C":
        return spot * _normal_cdf(d1) - strike * discount * _normal_cdf(d2)
    return strike * discount * _normal_cdf(-d2) - spot * _normal_cdf(-d1)


def settlement_implied_volatility(
    settlement: float,
    spot: float,
    strike: float,
    time_years: float,
    rate: float,
    call_put: str,
) -> float | None:
    """反解欧式 Black-Scholes 波动率；输入价格必须为结算价。"""
    if (
        settlement <= 0.0
        or spot <= 0.0
        or strike <= 0.0
        or time_years <= 0.0
        or call_put not in {"C", "P"}
        or not all(math.isfinite(value) for value in (settlement, spot, strike, time_years, rate))
    ):
        return None
    discount_strike = strike * math.exp(-rate * time_years)
    lower = (
        max(spot - discount_strike, 0.0) if call_put == "C" else max(discount_strike - spot, 0.0)
    )
    upper = spot if call_put == "C" else discount_strike
    if settlement <= lower or settlement >= upper:
        return None

    low, high = 1e-6, 8.0
    low_value = _black_scholes_price(spot, strike, time_years, rate, low, call_put) - settlement
    high_value = _black_scholes_price(spot, strike, time_years, rate, high, call_put) - settlement
    if low_value * high_value > 0.0:
        return None
    for _ in range(60):
        middle = (low + high) / 2.0
        value = _black_scholes_price(spot, strike, time_years, rate, middle, call_put)
        if abs(value - settlement) < 1e-8:
            return middle
        if (value - settlement) * low_value > 0.0:
            low = middle
            low_value = value - settlement
        else:
            high = middle
    return (low + high) / 2.0


def _date_column(frame: pl.DataFrame, candidates: tuple[str, ...]) -> str | None:
    return next((column for column in candidates if column in frame.columns), None)


def _prepare_risk_free(
    risk_free_rates: pl.DataFrame | None,
    default_rate: float,
) -> pl.DataFrame:
    if risk_free_rates is None or risk_free_rates.is_empty():
        return pl.DataFrame({"trade_date": [], "_risk_free_rate": []}).cast(
            {"trade_date": pl.Date, "_risk_free_rate": pl.Float64}
        )
    date_col = _date_column(risk_free_rates, ("trade_date", "date", "cal_date"))
    rate_col = _date_column(risk_free_rates, ("risk_free_rate", "rate", "yield", "close"))
    if date_col is None or rate_col is None:
        return pl.DataFrame({"trade_date": [], "_risk_free_rate": []}).cast(
            {"trade_date": pl.Date, "_risk_free_rate": pl.Float64}
        )
    return (
        risk_free_rates.with_columns(
            parse_mixed_date(date_col).alias("trade_date"),
            pl.col(rate_col).cast(pl.Float64, strict=False).alias("_risk_free_rate"),
        )
        .select("trade_date", "_risk_free_rate")
        .drop_nulls()
        .unique(subset=["trade_date"], keep="last")
    )


def build_settlement_iv_proxy_mart(
    daily: pl.DataFrame,
    basic: pl.DataFrame,
    underlying_prices: pl.DataFrame,
    *,
    risk_free_rates: pl.DataFrame | None = None,
    default_risk_free_rate: float = 0.0,
    underlying_symbols: tuple[str, ...] = DEFAULT_UNDERLYINGS,
) -> pl.DataFrame:
    """从结算价反解 Black-Scholes 波动率并按标的日频聚合。

    该结果明确是 ``settlement_iv_proxy``：结算价不是买一卖一中间价，且本函数
    不实现 CBOE VIX 的跨执行价方差积分，因此不能命名为标准 VIX 或标准 IV 指数。
    ``default_risk_free_rate`` 与风险利率表均使用小数形式，例如 2% 为 0.02。
    """
    required_daily = {"symbol", "trade_date", "settle"}
    required_basic = {"symbol", "call_put", "exercise_price", "maturity_date", "opt_code"}
    if (
        daily.is_empty()
        or basic.is_empty()
        or underlying_prices.is_empty()
        or not required_daily.issubset(daily.columns)
        or not required_basic.issubset(basic.columns)
    ):
        return _empty_mart()

    daily_frame = daily.select(
        pl.col("symbol").cast(pl.Utf8).alias("symbol"),
        parse_mixed_date("trade_date").alias("trade_date"),
        pl.col("settle").cast(pl.Float64, strict=False).alias("_settle"),
    ).drop_nulls(subset=["symbol", "trade_date", "_settle"])
    basic_frame = (
        basic.select(
            pl.col("symbol").cast(pl.Utf8).alias("symbol"),
            pl.col("call_put").cast(pl.Utf8).str.to_uppercase().alias("_call_put"),
            pl.col("exercise_price").cast(pl.Float64, strict=False).alias("_strike"),
            parse_mixed_date("maturity_date").alias("_maturity_date"),
            pl.col("opt_code").cast(pl.Utf8).alias("_opt_code"),
            pl.col("opt_type").cast(pl.Utf8).alias("_opt_type")
            if "opt_type" in basic.columns
            else pl.lit("").alias("_opt_type"),
        )
        .with_columns(pl.col("_opt_code").str.replace(r"^OP", "").alias("_underlying_symbol"))
        .filter(
            pl.col("_underlying_symbol").is_in(list(underlying_symbols))
            & pl.col("_call_put").is_in(["C", "P"])
        )
        .drop_nulls(subset=["symbol", "_strike", "_maturity_date", "_underlying_symbol"])
    )
    if daily_frame.is_empty() or basic_frame.is_empty():
        return _empty_mart()

    underlying_symbol = _date_column(underlying_prices, ("symbol", "ts_code"))
    if underlying_symbol is None or not {"trade_date", "close"}.issubset(underlying_prices.columns):
        return _empty_mart()
    underlying = (
        underlying_prices.select(
            pl.col(underlying_symbol).cast(pl.Utf8).alias("_underlying_symbol"),
            parse_mixed_date("trade_date").alias("trade_date"),
            pl.col("close").cast(pl.Float64, strict=False).alias("_spot"),
        )
        .drop_nulls()
        .unique(subset=["_underlying_symbol", "trade_date"], keep="last")
    )
    risk_free = _prepare_risk_free(risk_free_rates, default_risk_free_rate)
    frame = (
        daily_frame.join(basic_frame, on="symbol", how="inner")
        .join(underlying, on=["_underlying_symbol", "trade_date"], how="inner")
        .join(risk_free, on="trade_date", how="left")
        .with_columns(pl.col("_risk_free_rate").fill_null(default_risk_free_rate))
    )
    if frame.is_empty():
        return _empty_mart()

    from stock_analytics.plugins.options import compute_fast_bs_iv

    evaluated = (
        frame.with_columns(
            ((pl.col("_maturity_date") - pl.col("trade_date")).dt.total_days() / 365.0).alias(
                "_time_years"
            )
        )
        .with_columns(
            compute_fast_bs_iv(
                pl.col("_settle"),
                pl.col("_spot"),
                pl.col("_strike"),
                pl.col("_time_years"),
                pl.col("_risk_free_rate"),
                pl.col("_call_put"),
            ).alias("_iv")
        )
        .filter(pl.col("_iv").is_not_null() & pl.col("_iv").is_finite())
    )
    if evaluated.is_empty():
        return _empty_mart()

    return (
        evaluated.group_by(["trade_date", "_underlying_symbol"])
        .agg(
            pl.col("_iv").median().alias("settlement_iv_proxy_median"),
            pl.when(pl.col("_call_put") == "C")
            .then(pl.col("_iv"))
            .otherwise(None)
            .median()
            .alias("settlement_iv_proxy_call_median"),
            pl.when(pl.col("_call_put") == "P")
            .then(pl.col("_iv"))
            .otherwise(None)
            .median()
            .alias("settlement_iv_proxy_put_median"),
            pl.col("_iv").count().cast(pl.Int64).alias("settlement_iv_proxy_valid_count"),
            (pl.col("_call_put") == "C")
            .sum()
            .cast(pl.Int64)
            .alias("settlement_iv_proxy_call_count"),
            (pl.col("_call_put") == "P")
            .sum()
            .cast(pl.Int64)
            .alias("settlement_iv_proxy_put_count"),
            pl.col("_risk_free_rate").median().alias("risk_free_rate"),
        )
        .with_columns(
            (
                pl.col("settlement_iv_proxy_put_median") - pl.col("settlement_iv_proxy_call_median")
            ).alias("settlement_iv_proxy_put_call_skew")
        )
        .rename({"_underlying_symbol": "underlying_symbol"})
        .select(list(_empty_mart().columns))
        .sort(["trade_date", "underlying_symbol"])
    )


__all__ = [
    "DEFAULT_UNDERLYINGS",
    "SETTLEMENT_IV_PROXY_MART_NAME",
    "build_settlement_iv_proxy_mart",
    "settlement_implied_volatility",
]
