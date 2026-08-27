"""内置 STOCK 粒度横截面因子元数据定义。

登记 :meth:`FactorEngine.compute_all_factors` 的 26 个产出列与
``pipelines.stock_screen`` 评分宽表的 10 个评分因子：赋予
ID/单位/方向/版本，使因子可发现、可校验（见 ``factors.py`` 的
P1-2 列名硬校验）并有机器可读语义。

注意：``direction`` 为按金融常识给出的默认值，待投研复核
（见 docs/plan/factor_spec_plan.md 决策点 D4）；``unit`` 反映
P0-b 小数制迁移后的量纲。
"""

from __future__ import annotations

from stock_analytics.features.spec import EntityType, FeatureKind, FeatureSpec, FeatureUnit

_DEFAULT_FACTOR_COLUMNS = ("trade_date", "symbol", "close")


def _factor_spec(
    feature_id: str,
    description: str,
    *,
    unit: FeatureUnit,
    direction: str = "neutral",
    lookback_days: int = 1,
    inputs: tuple[str, ...] = (),
    datasets: tuple[str, ...] = ("stock_daily_bar",),
    columns: tuple[str, ...] = _DEFAULT_FACTOR_COLUMNS,
) -> FeatureSpec:
    """构造一个 STOCK 粒度横截面因子元数据定义。"""
    return FeatureSpec(
        feature_id=feature_id,
        kind=FeatureKind.FACTOR,
        entity_type=EntityType.STOCK,
        unit=unit,
        lookback_days=lookback_days,
        inputs=inputs,
        direction=direction,
        required_datasets=datasets,
        required_columns=columns,
        description=description,
    )


_MOMENTUM_INPUTS = ("calculate_momentum(price_col=close, windows=(20,60,120,250))",)
_REVERSAL_INPUTS = ("calculate_short_term_reversal(window=5)",)
_DIST_HIGH_INPUTS = ("calculate_distance_to_high(window=250)",)
_EMA_SPREAD_INPUTS = ("calculate_ema_spread(fast=12, slow=26)",)
_VOL_INPUTS = ("calculate_realized_volatility(windows=(20,60))",)
_ATR_INPUTS = ("calculate_atr(window=14)",)
_BOLLINGER_INPUTS = ("calculate_bollinger_bandwidth(window=20)",)
_AMIHUD_INPUTS = ("calculate_amihud_illiquidity(window=20, scale_factor=1e8)",)
_TURNOVER_INPUTS = ("calculate_turnover_factors(windows=(5,20,60))",)
_VOLUME_SURPRISE_INPUTS = ("calculate_volume_surprise(short_window=5, long_window=20)",)
_MONEYFLOW_INPUTS = ("calculate_main_moneyflow_factors(windows=(5,20))",)
_PERCENTILE_INPUTS = ("calculate_rolling_percentile(metric_cols=(pe_ttm,pb), window_days=1250)",)

_OHLC_COLUMNS = ("trade_date", "symbol", "close", "high", "low")
_AMOUNT_COLUMNS = ("trade_date", "symbol", "close", "amount")
_VOLUME_COLUMNS = ("trade_date", "symbol", "close", "volume")
_TURNOVER_COLUMNS = ("trade_date", "symbol", "close", "turnover_rate")
_MONEYFLOW_COLUMNS = ("trade_date", "symbol", "close", "amount", "net_mf_amount")
_VALUATION_COLUMNS = ("trade_date", "symbol", "pe_ttm", "pb")

#: FactorEngine.compute_all_factors 的 26 个产出列（P0-b 迁移后量纲）。
FACTOR_ENGINE_SPECS: tuple[FeatureSpec, ...] = (
    _factor_spec(
        "mom_20d",
        "20日动量收益（小数制）",
        unit=FeatureUnit.RATIO,
        direction="positive",
        lookback_days=20,
        inputs=_MOMENTUM_INPUTS,
    ),
    _factor_spec(
        "mom_60d",
        "60日动量收益（小数制）",
        unit=FeatureUnit.RATIO,
        direction="positive",
        lookback_days=60,
        inputs=_MOMENTUM_INPUTS,
    ),
    _factor_spec(
        "mom_120d",
        "120日动量收益（小数制）",
        unit=FeatureUnit.RATIO,
        direction="positive",
        lookback_days=120,
        inputs=_MOMENTUM_INPUTS,
    ),
    _factor_spec(
        "mom_250d",
        "250日动量收益（小数制）",
        unit=FeatureUnit.RATIO,
        direction="positive",
        lookback_days=250,
        inputs=_MOMENTUM_INPUTS,
    ),
    _factor_spec(
        "reversal_5d",
        "5日短期反转因子（小数制，上涨时为负）",
        unit=FeatureUnit.RATIO,
        direction="negative",
        lookback_days=5,
        inputs=_REVERSAL_INPUTS,
    ),
    _factor_spec(
        "dist_to_high_250d",
        "距250日最高价距离（小数制，负值表示回撤深度）",
        unit=FeatureUnit.RATIO,
        direction="positive",
        lookback_days=250,
        inputs=_DIST_HIGH_INPUTS,
    ),
    _factor_spec(
        "ema_spread_12_26",
        "12/26 快慢均线偏离（小数制）",
        unit=FeatureUnit.RATIO,
        direction="positive",
        lookback_days=26,
        inputs=_EMA_SPREAD_INPUTS,
    ),
    _factor_spec(
        "realized_vol_20d",
        "20日年化已实现波动率（小数制）",
        unit=FeatureUnit.RATIO,
        direction="negative",
        lookback_days=20,
        inputs=_VOL_INPUTS,
    ),
    _factor_spec(
        "realized_vol_60d",
        "60日年化已实现波动率（小数制）",
        unit=FeatureUnit.RATIO,
        direction="negative",
        lookback_days=60,
        inputs=_VOL_INPUTS,
    ),
    _factor_spec(
        "atr_14d",
        "14日平均真实波幅（价格单位，元）",
        unit=FeatureUnit.CNY,
        direction="neutral",
        lookback_days=14,
        inputs=_ATR_INPUTS,
        columns=_OHLC_COLUMNS,
    ),
    _factor_spec(
        "atr_ratio_14d",
        "14日 ATR 相对收盘价比率（小数制）",
        unit=FeatureUnit.RATIO,
        direction="negative",
        lookback_days=14,
        inputs=_ATR_INPUTS,
        columns=_OHLC_COLUMNS,
    ),
    _factor_spec(
        "bollinger_bandwidth_20d",
        "20日布林带相对宽度（小数制）",
        unit=FeatureUnit.RATIO,
        direction="neutral",
        lookback_days=20,
        inputs=_BOLLINGER_INPUTS,
    ),
    _factor_spec(
        "bollinger_percent_b_20d",
        "20日布林 %B 价格位置（0-1 小数）",
        unit=FeatureUnit.RATIO,
        direction="neutral",
        lookback_days=20,
        inputs=_BOLLINGER_INPUTS,
    ),
    _factor_spec(
        "amihud_illiq_20d",
        "20日 Amihud 非流动性（绝对量，×1e8 标度）",
        unit=FeatureUnit.UNKNOWN,
        direction="negative",
        lookback_days=20,
        inputs=_AMIHUD_INPUTS,
        columns=_AMOUNT_COLUMNS,
    ),
    _factor_spec(
        "turnover_mean_5d",
        "5日平均换手率（沿用源列 turnover_rate 百分数口径）",
        unit=FeatureUnit.PERCENT,
        direction="neutral",
        lookback_days=5,
        inputs=_TURNOVER_INPUTS,
        columns=_TURNOVER_COLUMNS,
    ),
    _factor_spec(
        "turnover_std_5d",
        "5日换手率波动（百分数口径）",
        unit=FeatureUnit.PERCENT,
        direction="neutral",
        lookback_days=5,
        inputs=_TURNOVER_INPUTS,
        columns=_TURNOVER_COLUMNS,
    ),
    _factor_spec(
        "turnover_mean_20d",
        "20日平均换手率（百分数口径）",
        unit=FeatureUnit.PERCENT,
        direction="neutral",
        lookback_days=20,
        inputs=_TURNOVER_INPUTS,
        columns=_TURNOVER_COLUMNS,
    ),
    _factor_spec(
        "turnover_std_20d",
        "20日换手率波动（百分数口径）",
        unit=FeatureUnit.PERCENT,
        direction="neutral",
        lookback_days=20,
        inputs=_TURNOVER_INPUTS,
        columns=_TURNOVER_COLUMNS,
    ),
    _factor_spec(
        "turnover_mean_60d",
        "60日平均换手率（百分数口径）",
        unit=FeatureUnit.PERCENT,
        direction="neutral",
        lookback_days=60,
        inputs=_TURNOVER_INPUTS,
        columns=_TURNOVER_COLUMNS,
    ),
    _factor_spec(
        "turnover_std_60d",
        "60日换手率波动（百分数口径）",
        unit=FeatureUnit.PERCENT,
        direction="neutral",
        lookback_days=60,
        inputs=_TURNOVER_INPUTS,
        columns=_TURNOVER_COLUMNS,
    ),
    _factor_spec(
        "volume_surprise_5_20",
        "5/20 日成交量突增偏离（小数制）",
        unit=FeatureUnit.RATIO,
        direction="neutral",
        lookback_days=20,
        inputs=_VOLUME_SURPRISE_INPUTS,
        columns=_VOLUME_COLUMNS,
    ),
    _factor_spec(
        "main_inflow_ratio",
        "主力净流入占成交额比重（小数制）",
        unit=FeatureUnit.RATIO,
        direction="positive",
        lookback_days=1,
        inputs=_MONEYFLOW_INPUTS,
        columns=_MONEYFLOW_COLUMNS,
    ),
    _factor_spec(
        "main_inflow_ratio_5d",
        "主力净流入占比 5 日滚动平均（小数制）",
        unit=FeatureUnit.RATIO,
        direction="positive",
        lookback_days=5,
        inputs=_MONEYFLOW_INPUTS,
        columns=_MONEYFLOW_COLUMNS,
    ),
    _factor_spec(
        "main_inflow_ratio_20d",
        "主力净流入占比 20 日滚动平均（小数制）",
        unit=FeatureUnit.RATIO,
        direction="positive",
        lookback_days=20,
        inputs=_MONEYFLOW_INPUTS,
        columns=_MONEYFLOW_COLUMNS,
    ),
    _factor_spec(
        "pe_ttm_percentile_1250d",
        "PE-TTM 五年历史分位数（0-100）",
        unit=FeatureUnit.PERCENTILE,
        direction="negative",
        lookback_days=1250,
        inputs=_PERCENTILE_INPUTS,
        datasets=("daily_basic",),
        columns=_VALUATION_COLUMNS,
    ),
    _factor_spec(
        "pb_percentile_1250d",
        "PB 五年历史分位数（0-100）",
        unit=FeatureUnit.PERCENTILE,
        direction="negative",
        lookback_days=1250,
        inputs=_PERCENTILE_INPUTS,
        datasets=("daily_basic",),
        columns=_VALUATION_COLUMNS,
    ),
)

#: pipelines/stock_screen 评分宽表的 10 个评分因子（内部列名不改）。
STOCK_SCREEN_SPECS: tuple[FeatureSpec, ...] = (
    _factor_spec(
        "pe",
        "市盈率（倍数，daily_basic 透传）",
        unit=FeatureUnit.RATIO,
        direction="neutral",
        lookback_days=1,
        datasets=("daily_basic",),
        columns=("symbol", "pe"),
    ),
    _factor_spec(
        "pb",
        "市净率（倍数，daily_basic 透传）",
        unit=FeatureUnit.RATIO,
        direction="neutral",
        lookback_days=1,
        datasets=("daily_basic",),
        columns=("symbol", "pb"),
    ),
    _factor_spec(
        "total_mv",
        "总市值（元，daily_basic 透传）",
        unit=FeatureUnit.CNY,
        direction="neutral",
        lookback_days=1,
        datasets=("daily_basic",),
        columns=("symbol", "total_mv"),
    ),
    _factor_spec(
        "turnover_rate",
        "换手率（daily_basic 透传，百分数口径）",
        unit=FeatureUnit.PERCENT,
        direction="neutral",
        lookback_days=1,
        datasets=("daily_basic",),
        columns=("symbol", "turnover_rate"),
    ),
    _factor_spec(
        "rel_return_20d",
        "相对沪深300 的 20 日收益差（百分数）",
        unit=FeatureUnit.PERCENT,
        direction="positive",
        lookback_days=20,
        datasets=("stock_daily_bar", "index_daily_bar"),
        columns=("trade_date", "symbol", "close"),
    ),
    _factor_spec(
        "rel_return_60d",
        "相对沪深300 的 60 日收益差（百分数）",
        unit=FeatureUnit.PERCENT,
        direction="positive",
        lookback_days=60,
        datasets=("stock_daily_bar", "index_daily_bar"),
        columns=("trade_date", "symbol", "close"),
    ),
    _factor_spec(
        "netprofit_growth",
        "最新报告期净利润同比增速（fina_indicator 透传，百分数）",
        unit=FeatureUnit.PERCENT,
        direction="positive",
        lookback_days=1,
        datasets=("fina_indicator",),
        columns=("symbol", "netprofit_yoy"),
    ),
    _factor_spec(
        "roe",
        "最新报告期 ROE（百分数）",
        unit=FeatureUnit.PERCENT,
        direction="positive",
        lookback_days=1,
        datasets=("income", "balancesheet"),
        columns=("symbol", "n_income", "total_hldr_eqy_exc_min_int"),
    ),
    _factor_spec(
        "ocf_ratio",
        "经营现金流与净利润之比（倍）",
        unit=FeatureUnit.RATIO,
        direction="positive",
        lookback_days=1,
        datasets=("cashflow", "income"),
        columns=("symbol", "n_cashflow_act", "n_income"),
    ),
    _factor_spec(
        "goodwill_ratio",
        "商誉占净资产比例（百分数）",
        unit=FeatureUnit.PERCENT,
        direction="negative",
        lookback_days=1,
        datasets=("balancesheet",),
        columns=("symbol", "goodwill", "total_hldr_eqy_exc_min_int"),
    ),
)


def get_all_builtin_factor_specs() -> tuple[FeatureSpec, ...]:
    """获取全套内置 STOCK 横截面因子元数据规范。"""
    return (*FACTOR_ENGINE_SPECS, *STOCK_SCREEN_SPECS)


__all__ = [
    "FACTOR_ENGINE_SPECS",
    "STOCK_SCREEN_SPECS",
    "get_all_builtin_factor_specs",
]
