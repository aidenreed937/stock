"""统一因子计算与特征工程调度引擎 (FactorEngine)。"""

import polars as pl

from stock_analytics.features import factor_steps
from stock_analytics.features.factor_steps import (
    _INPUT_BASE_COLUMNS,
    run_factor_step,
    validate_factor_engine_steps,
)
from stock_core.exceptions import DataValidationError


def ensure_factor_columns_registered(columns: list[str]) -> None:
    """硬校验因子产出列均已登记为 STOCK 粒度 FACTOR 元数据（fail-closed）。

    Args:
        columns: 待校验的派生列名列表。

    Raises:
        DataValidationError: 存在未登记的产出列。
    """
    from stock_analytics.features.registry import FeatureRegistry
    from stock_analytics.features.spec import EntityType, FeatureKind

    registered = {
        spec.feature_id
        for spec in FeatureRegistry.list_all()
        if spec.kind == FeatureKind.FACTOR and spec.entity_type == EntityType.STOCK
    }
    unregistered = [column for column in columns if column not in registered]
    if unregistered:
        raise DataValidationError(
            "未登记的因子产出列: "
            f"{sorted(unregistered)}；请在 features/builtin_factor_specs.py 中登记后重试"
        )


class FactorEngine:
    """量化多因子统一计算、截面去极值与标准化引擎。

    因子计算由 :data:`~stock_analytics.features.factor_steps.FACTOR_ENGINE_STEPS`
    步骤表驱动（P2）：新增因子只需追加步骤与列级 spec，无需改动本类。
    """

    @staticmethod
    def winsorize(
        df: pl.DataFrame,
        factor_cols: list[str],
        lower_quantile: float = 0.01,
        upper_quantile: float = 0.99,
        group_col: str = "trade_date",
    ) -> pl.DataFrame:
        """对指定因子列进行截面分位数缩尾去极值 (Winsorization)。"""
        if df.is_empty() or not factor_cols:
            return df

        has_group = group_col in df.columns
        exprs = []
        for col in factor_cols:
            if col not in df.columns:
                continue
            if has_group:
                low = pl.col(col).quantile(lower_quantile, interpolation="linear").over(group_col)
                high = pl.col(col).quantile(upper_quantile, interpolation="linear").over(group_col)
            else:
                low = pl.col(col).quantile(lower_quantile, interpolation="linear")
                high = pl.col(col).quantile(upper_quantile, interpolation="linear")
            exprs.append(pl.col(col).clip(low, high).alias(col))

        return df.with_columns(exprs)

    @staticmethod
    def standardize_zscore(
        df: pl.DataFrame,
        factor_cols: list[str],
        group_col: str = "trade_date",
    ) -> pl.DataFrame:
        """对指定因子列执行截面 Z-Score 标准化 ((X - Mean) / Std)。"""
        if df.is_empty() or not factor_cols:
            return df

        has_group = group_col in df.columns
        exprs = []
        for col in factor_cols:
            if col not in df.columns:
                continue
            if has_group:
                mean = pl.col(col).mean().over(group_col)
                std = pl.col(col).std().over(group_col)
            else:
                mean = pl.col(col).mean()
                std = pl.col(col).std()
            exprs.append(((pl.col(col) - mean) / (std + 1e-8)).alias(f"{col}_zscore"))

        return df.with_columns(exprs)

    @classmethod
    def compute_all_factors(
        cls,
        df: pl.DataFrame,
        price_col: str = "close",
        *,
        normalize: bool = False,
    ) -> pl.DataFrame:
        """对日线行情与基本面数据执行全套因子特征提取（步骤表驱动）。

        Args:
            df: 必须包含 trade_date, close 等列的基础数据表。
            price_col: 价格基准列。
            normalize: 是否执行截面 Z-Score 标准化。

        Returns:
            pl.DataFrame: 注入了 20+ 个衍生因子特征的宽表。
        """
        if df.is_empty():
            return df

        # 静态一致性校验：步骤表产出与列级 spec 双集合一致（fail-closed）
        validate_factor_engine_steps()

        # 按步骤表顺序执行各因子算子（调用时读模块属性，单一事实源）
        res = df
        for step in factor_steps.FACTOR_ENGINE_STEPS:
            res = run_factor_step(res, step, price_col=price_col)

        # 硬校验：所有派生列都必须已登记为 STOCK FACTOR 元数据
        derived_columns = [column for column in res.columns if column not in _INPUT_BASE_COLUMNS]
        ensure_factor_columns_registered(derived_columns)

        if normalize:
            computed_factor_cols = [
                c
                for c in res.columns
                if c
                not in {
                    "trade_date",
                    "symbol",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "amount",
                    "pre_close",
                }
            ]
            res = FactorEngine.winsorize(res, computed_factor_cols)
            res = FactorEngine.standardize_zscore(res, computed_factor_cols)

        return res
