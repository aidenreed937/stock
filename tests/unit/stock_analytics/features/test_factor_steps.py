"""FactorEngine 步骤表（P2 spec 驱动）单元测试。"""

from datetime import date

import polars as pl
import pytest

import stock_analytics.features.factor_steps as factor_steps
from stock_analytics.features import (
    EntityType,
    FactorEngine,
    FeatureKind,
    FeatureRegistry,
    FeatureSpec,
    FeatureUnit,
)
from stock_analytics.features.builtin_factor_specs import FACTOR_ENGINE_SPECS
from stock_analytics.features.factor_steps import (
    FACTOR_ENGINE_STEPS,
    FactorStep,
    validate_factor_engine_steps,
)
from stock_core.exceptions import DataValidationError

_INPUT_BASE_COLUMNS = {
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


def _create_sample_ohlcv(n: int = 50) -> pl.DataFrame:
    """构造与 test_factors 一致的基础测试用面板行情数据。"""
    dates = [date(2026, 1, 1) for _ in range(n)]
    prices = [10.0 + i * 0.2 for i in range(n)]
    return pl.DataFrame(
        {
            "trade_date": dates,
            "symbol": ["000001.SZ"] * n,
            "open": [p - 0.1 for p in prices],
            "high": [p + 0.3 for p in prices],
            "low": [p - 0.3 for p in prices],
            "close": prices,
            "volume": [10000.0 + i * 100 for i in range(n)],
            "amount": [(10.0 + i * 0.2) * (10000.0 + i * 100) for i in range(n)],
            "turnover_rate": [1.5 + (i % 5) * 0.2 for i in range(n)],
            "net_mf_amount": [5000.0 * (1 if i % 2 == 0 else -1) for i in range(n)],
            "pe_ttm": [15.0 + (i % 10) * 0.5 for i in range(n)],
            "pb": [1.8 + (i % 8) * 0.1 for i in range(n)],
        }
    )


def test_steps_bijection_with_column_specs() -> None:
    """步骤表产出与 26 条列级 spec 双集合一致；步骤内与跨步无重复产出列。"""
    assert len(FACTOR_ENGINE_STEPS) == 12

    produced = [col for step in FACTOR_ENGINE_STEPS for col in step.produces]
    assert len(produced) == 26
    assert len(produced) == len(set(produced))

    spec_ids = {spec.feature_id for spec in FACTOR_ENGINE_SPECS}
    assert set(produced) == spec_ids
    assert not (set(produced) & _INPUT_BASE_COLUMNS)

    # 静态校验通过（无异常）
    validate_factor_engine_steps()


def test_validate_rejects_step_without_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    """步骤表缺步（引擎不计算已登记列）必须抛 DataValidationError。"""
    monkeypatch.setattr(factor_steps, "FACTOR_ENGINE_STEPS", FACTOR_ENGINE_STEPS[1:])
    with pytest.raises(DataValidationError, match="已登记但未计算"):
        validate_factor_engine_steps()


def test_validate_rejects_spec_without_step(monkeypatch: pytest.MonkeyPatch) -> None:
    """列级 spec 多余（登记了但引擎不计算的列）必须抛 DataValidationError。"""
    phantom = FeatureSpec(
        feature_id="phantom_999d",
        kind=FeatureKind.FACTOR,
        entity_type=EntityType.STOCK,
        unit=FeatureUnit.RATIO,
        description="未接入步骤表的幽灵因子",
    )
    monkeypatch.setattr(factor_steps, "FACTOR_ENGINE_SPECS", (*FACTOR_ENGINE_SPECS, phantom))
    with pytest.raises(DataValidationError, match="已计算但未登记"):
        validate_factor_engine_steps()


def test_validate_rejects_unknown_operator(monkeypatch: pytest.MonkeyPatch) -> None:
    """步骤引用未知算子必须抛 DataValidationError（静态映射拒绝动态解析）。"""
    bad_step = FactorStep("bad_step", "calculate_nonexistent", {}, ("bad_col",))
    monkeypatch.setattr(factor_steps, "FACTOR_ENGINE_STEPS", (bad_step,))
    with pytest.raises(DataValidationError, match="未登记的因子算子"):
        validate_factor_engine_steps()


def test_engine_column_order_follows_step_order() -> None:
    """产出列顺序与步骤表声明顺序一致（行为兼容 P1 硬编码顺序）。"""
    df = _create_sample_ohlcv(60)
    res = FactorEngine.compute_all_factors(df)

    derived = [col for col in res.columns if col not in _INPUT_BASE_COLUMNS]
    expected = [col for step in FACTOR_ENGINE_STEPS for col in step.produces]
    assert derived == expected


def test_engine_extends_with_new_step(monkeypatch: pytest.MonkeyPatch) -> None:
    """新增因子只追加步骤 + 列 spec + 注册，引擎代码零改动即可自动计算。"""

    def _dummy_operator(df: pl.DataFrame) -> pl.DataFrame:
        return df.with_columns(pl.lit(2.0).alias("dummy_factor"))

    temp_step = FactorStep("dummy", "dummy_op", {}, ("dummy_factor",))
    temp_spec = FeatureSpec(
        feature_id="dummy_factor",
        kind=FeatureKind.FACTOR,
        entity_type=EntityType.STOCK,
        unit=FeatureUnit.RATIO,
        description="扩展性测试临时因子",
    )

    monkeypatch.setitem(factor_steps._FACTOR_OPERATORS, "dummy_op", _dummy_operator)
    monkeypatch.setattr(factor_steps, "FACTOR_ENGINE_STEPS", (*FACTOR_ENGINE_STEPS, temp_step))
    monkeypatch.setattr(factor_steps, "FACTOR_ENGINE_SPECS", (*FACTOR_ENGINE_SPECS, temp_spec))
    monkeypatch.setitem(FeatureRegistry._registry, "dummy_factor", {"v1": temp_spec})
    monkeypatch.setitem(FeatureRegistry._current_versions, "dummy_factor", "v1")

    df = _create_sample_ohlcv(60)
    res = FactorEngine.compute_all_factors(df)

    assert "dummy_factor" in res.columns
    assert res["dummy_factor"].to_list() == [2.0] * 60
    # 原有 26 列不受影响
    assert all(col in res.columns for col in ("mom_20d", "pb_percentile_1250d"))
