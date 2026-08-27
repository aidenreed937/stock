"""FactorEngine 因子计算步骤表（P2 spec 驱动执行计划）。

将 :meth:`FactorEngine.compute_all_factors` 的硬编码 12 段算子调用
声明为有序步骤表 :data:`FACTOR_ENGINE_STEPS`：新增因子 = 追加一条
``FactorStep`` + 在 ``builtin_factor_specs.py`` 补充列级 ``FeatureSpec``，
引擎代码无需改动。步骤表与列级 spec 经 :func:`validate_factor_engine_steps`
做强一致校验（fail-closed，任一方向不同步即抛 ``DataValidationError``）。

执行语义：

- 步骤表有序，声明顺序即执行顺序（当前 12 步无跨步数据依赖）；
- 算子名经 :data:`_FACTOR_OPERATORS` 显式静态映射解析，不做动态 import/eval；
- ``price_col`` / ``close_col`` 两类价格参数由引擎入参注入
  （见 :func:`run_factor_step`），步骤表内仅固化默认列名。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

import polars as pl

from stock_analytics.features.builtin_factor_specs import FACTOR_ENGINE_SPECS
from stock_analytics.primitives import (
    calculate_amihud_illiquidity,
    calculate_atr,
    calculate_bollinger_bandwidth,
    calculate_distance_to_high,
    calculate_ema_spread,
    calculate_main_moneyflow_factors,
    calculate_momentum,
    calculate_realized_volatility,
    calculate_rolling_percentile,
    calculate_short_term_reversal,
    calculate_turnover_factors,
    calculate_volume_surprise,
)
from stock_core.exceptions import DataValidationError

#: compute_all_factors 的输入基础列（其余列视为因子派生列，纳入注册校验）。
_INPUT_BASE_COLUMNS = frozenset(
    {
        "trade_date",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "pre_close",
        "turnover_rate",
        "net_mf_amount",
        "pe_ttm",
        "pb",
    }
)

#: 因子算子类型签名：入参为 DataFrame，返回注入新列后的 DataFrame。
Operator = Callable[..., pl.DataFrame]


@dataclass(frozen=True, slots=True)
class FactorStep:
    """因子计算单步声明：一次算子调用及其产出列。"""

    step_id: str
    operator: str
    params: Mapping[str, object]
    produces: tuple[str, ...]


#: 算子名 -> primitives 函数的显式静态映射（禁止动态 import/eval）。
_FACTOR_OPERATORS: dict[str, Operator] = {
    "calculate_momentum": calculate_momentum,
    "calculate_short_term_reversal": calculate_short_term_reversal,
    "calculate_distance_to_high": calculate_distance_to_high,
    "calculate_ema_spread": calculate_ema_spread,
    "calculate_realized_volatility": calculate_realized_volatility,
    "calculate_atr": calculate_atr,
    "calculate_bollinger_bandwidth": calculate_bollinger_bandwidth,
    "calculate_amihud_illiquidity": calculate_amihud_illiquidity,
    "calculate_turnover_factors": calculate_turnover_factors,
    "calculate_volume_surprise": calculate_volume_surprise,
    "calculate_main_moneyflow_factors": calculate_main_moneyflow_factors,
    "calculate_rolling_percentile": calculate_rolling_percentile,
}

#: FactorEngine.compute_all_factors 的有序步骤表（对应 P1 硬编码 12 段调用）。
FACTOR_ENGINE_STEPS: tuple[FactorStep, ...] = (
    FactorStep(
        "momentum",
        "calculate_momentum",
        {"price_col": "close"},
        ("mom_20d", "mom_60d", "mom_120d", "mom_250d"),
    ),
    FactorStep(
        "reversal",
        "calculate_short_term_reversal",
        {"price_col": "close"},
        ("reversal_5d",),
    ),
    FactorStep(
        "dist_to_high",
        "calculate_distance_to_high",
        {"price_col": "close"},
        ("dist_to_high_250d",),
    ),
    FactorStep(
        "ema_spread",
        "calculate_ema_spread",
        {"price_col": "close"},
        ("ema_spread_12_26",),
    ),
    FactorStep(
        "realized_vol",
        "calculate_realized_volatility",
        {"price_col": "close"},
        ("realized_vol_20d", "realized_vol_60d"),
    ),
    FactorStep(
        "atr",
        "calculate_atr",
        {"close_col": "close"},
        ("atr_14d", "atr_ratio_14d"),
    ),
    FactorStep(
        "bollinger",
        "calculate_bollinger_bandwidth",
        {"price_col": "close"},
        ("bollinger_bandwidth_20d", "bollinger_percent_b_20d"),
    ),
    FactorStep(
        "amihud",
        "calculate_amihud_illiquidity",
        {"price_col": "close"},
        ("amihud_illiq_20d",),
    ),
    FactorStep(
        "turnover",
        "calculate_turnover_factors",
        {},
        (
            "turnover_mean_5d",
            "turnover_std_5d",
            "turnover_mean_20d",
            "turnover_std_20d",
            "turnover_mean_60d",
            "turnover_std_60d",
        ),
    ),
    FactorStep(
        "volume_surprise",
        "calculate_volume_surprise",
        {},
        ("volume_surprise_5_20",),
    ),
    FactorStep(
        "moneyflow",
        "calculate_main_moneyflow_factors",
        {},
        ("main_inflow_ratio", "main_inflow_ratio_5d", "main_inflow_ratio_20d"),
    ),
    FactorStep(
        "percentile",
        "calculate_rolling_percentile",
        {},
        ("pe_ttm_percentile_1250d", "pb_percentile_1250d"),
    ),
)


def run_factor_step(df: pl.DataFrame, step: FactorStep, price_col: str = "close") -> pl.DataFrame:
    """按步骤执行一次算子调用，引擎价格参数仅覆盖步骤表内的价格列参数。"""
    params = dict(step.params)
    for key in ("price_col", "close_col"):
        if key in params:
            params[key] = price_col
    return _FACTOR_OPERATORS[step.operator](df, **params)


def validate_factor_engine_steps() -> None:
    """静态校验步骤表与列级 spec 的强一致（fail-closed）。

    Raises:
        DataValidationError: 步骤表存在未知算子、空/重复/基础列产出，
            或步骤表产出与 ``FACTOR_ENGINE_SPECS`` 未登记列不一致。
    """
    produced: list[str] = []
    for step in FACTOR_ENGINE_STEPS:
        if step.operator not in _FACTOR_OPERATORS:
            raise DataValidationError(
                f"未登记的因子算子: step={step.step_id} operator={step.operator}"
            )
        if not step.produces:
            raise DataValidationError(f"步骤未声明产出列: step={step.step_id}")
        base_overlap = sorted(set(step.produces) & _INPUT_BASE_COLUMNS)
        if base_overlap:
            raise DataValidationError(
                f"步骤产出列为引擎基础列: step={step.step_id} columns={base_overlap}"
            )
        duplicate = [col for col in step.produces if col in produced]
        if duplicate:
            raise DataValidationError(
                f"步骤产出列跨步重复: step={step.step_id} columns={sorted(set(duplicate))}"
            )
        produced.extend(step.produces)

    spec_ids = {spec.feature_id for spec in FACTOR_ENGINE_SPECS}
    produced_set = set(produced)
    if produced_set != spec_ids:
        missing = sorted(spec_ids - produced_set)
        extra = sorted(produced_set - spec_ids)
        raise DataValidationError(
            "步骤表产出与列级 spec 不一致（须双向同步）: "
            f"已登记但未计算={missing}；已计算但未登记={extra}"
        )

    from stock_analytics.features.registry import FeatureRegistry
    from stock_analytics.features.spec import EntityType, FeatureKind

    registered = {
        spec.feature_id
        for spec in FeatureRegistry.list_all()
        if spec.kind == FeatureKind.FACTOR and spec.entity_type == EntityType.STOCK
    }
    unregistered = sorted(produced_set - registered)
    if unregistered:
        raise DataValidationError(
            f"未登记到 FeatureRegistry 的因子产出列: {unregistered}；"
            "请在 features/builtin_factor_specs.py 中登记后重试"
        )


__all__ = [
    "FACTOR_ENGINE_STEPS",
    "FactorStep",
    "run_factor_step",
    "validate_factor_engine_steps",
]
