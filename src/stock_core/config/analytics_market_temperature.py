"""市场温度计配置加载。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Self, cast

import yaml

from stock_core.config.external_risk import (
    ExternalRiskConfig,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config/analytics/market_temperature.yaml"


@dataclass(frozen=True, slots=True)
class MetricInputConfig:
    """单个可计算指标的配置。"""

    metric_id: str
    aggregation: str = "latest"
    direction: str = "positive"
    weight: float = 1.0
    enabled: bool = True
    source: str = "metric_engine"
    subgroup: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Self:
        """从 YAML 字典构造指标配置。"""
        subgroup = str(data.get("subgroup", ""))
        if subgroup not in {"", "daily", "activity", "slow", "domestic", "external"}:
            raise ValueError(f"不支持的指标 subgroup: {subgroup}")
        return cls(
            metric_id=str(data["metric_id"]),
            aggregation=str(data.get("aggregation", "latest")),
            direction=str(data.get("direction", "positive")),
            weight=float(data.get("weight", 1.0)),
            enabled=bool(data.get("enabled", True)),
            source=str(data.get("source", "metric_engine")),
            subgroup=subgroup,
        )


@dataclass(frozen=True, slots=True)
class DimensionConfig:
    """六维温度维度配置。"""

    id: str
    name: str
    weight: float
    role: str = ""
    metrics: tuple[MetricInputConfig, ...] = ()
    stale_after_days: int | None = None
    stale_weight_scale: float = 0.4
    subgroup_external_cap: float | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Self:
        """从 YAML 字典构造维度配置。"""
        raw_metrics = _as_sequence(data.get("metrics", ()), "dimensions.metrics")
        stale_after = data.get("stale_after_days")
        external_cap = data.get("subgroup_external_cap")
        if external_cap is not None and not 0.0 < float(external_cap) <= 1.0:
            raise ValueError(f"subgroup_external_cap 必须在 (0, 1] 内: {external_cap}")
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            weight=float(data["weight"]),
            role=str(data.get("role", "")),
            metrics=tuple(
                MetricInputConfig.from_mapping(_as_mapping(item, "metric")) for item in raw_metrics
            ),
            stale_after_days=int(stale_after) if stale_after is not None else None,
            stale_weight_scale=float(data.get("stale_weight_scale", 0.4)),
            subgroup_external_cap=float(external_cap) if external_cap is not None else None,
        )


@dataclass(frozen=True, slots=True)
class DatasetConfig:
    """事实层数据集水位配置。"""

    data_source: str
    dataset: str
    dimension: str
    required: bool = False
    date_column: str = ""
    max_lag_days: int = 0
    static: bool = False
    cadence: str = "unspecified"
    quality_tier: str = "optional"
    note: str = ""
    in_score: bool = False

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Self:
        """从 YAML 字典构造数据集配置。"""
        return cls(
            data_source=str(data["data_source"]),
            dataset=str(data["dataset"]),
            dimension=str(data.get("dimension", "")),
            required=bool(data.get("required", False)),
            date_column=str(data.get("date_column", "")),
            max_lag_days=int(data.get("max_lag_days", 0)),
            static=bool(data.get("static", False)),
            cadence=str(data.get("cadence", "unspecified")),
            quality_tier=str(data.get("quality_tier", "optional")),
            note=str(data.get("note", "")),
            in_score=bool(data.get("in_score", False)),
        )


@dataclass(frozen=True, slots=True)
class MetricValuesConfig:
    """指标事实采集开关。"""

    enabled: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> Self:
        """从 YAML 字典构造指标采集配置。"""
        if data is None:
            return cls()
        return cls(enabled=bool(data.get("enabled", True)))


@dataclass(frozen=True, slots=True)
class TemperatureLevelsConfig:
    """温度分档阈值。"""

    low_opportunity: float = 20.0
    cool_observation: float = 40.0
    neutral_rotation: float = 60.0
    warm_recovery: float = 80.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> Self:
        """从 YAML 字典构造温度分档阈值配置。"""
        if data is None:
            return cls()
        return cls(
            low_opportunity=float(data.get("low_opportunity", 20.0)),
            cool_observation=float(data.get("cool_observation", 40.0)),
            neutral_rotation=float(data.get("neutral_rotation", 60.0)),
            warm_recovery=float(data.get("warm_recovery", 80.0)),
        )


@dataclass(frozen=True, slots=True)
class PressureLevelsConfig:
    """宏观压力分档阈值。"""

    moderate: float = 40.0
    high_moderate: float = 60.0
    high: float = 80.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> Self:
        """从 YAML 字典构造宏观压力分档阈值配置。"""
        if data is None:
            return cls()
        return cls(
            moderate=float(data.get("moderate", 40.0)),
            high_moderate=float(data.get("high_moderate", 60.0)),
            high=float(data.get("high", 80.0)),
        )


@dataclass(frozen=True, slots=True)
class DeltaLevelsConfig:
    """跨期变化评语阈值。"""

    stable: float = 3.0
    moderate: float = 5.0
    significant: float = 20.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> Self:
        """从 YAML 字典构造跨期变化评语阈值配置。"""
        if data is None:
            return cls()
        return cls(
            stable=float(data.get("stable", 3.0)),
            moderate=float(data.get("moderate", 5.0)),
            significant=float(data.get("significant", 20.0)),
        )


@dataclass(frozen=True, slots=True)
class BandsConfig:
    """市场温度计分档阈值总配置。"""

    temperature_levels: TemperatureLevelsConfig = field(default_factory=TemperatureLevelsConfig)
    pressure_levels: PressureLevelsConfig = field(default_factory=PressureLevelsConfig)
    delta_levels: DeltaLevelsConfig = field(default_factory=DeltaLevelsConfig)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> Self:
        """从 YAML 字典构造分档阈值总配置。"""
        if data is None:
            return cls()
        temp = data.get("temperature_levels")
        pres = data.get("pressure_levels")
        delta = data.get("delta_levels")
        return cls(
            temperature_levels=TemperatureLevelsConfig.from_mapping(
                _as_mapping(temp, "temperature_levels") if temp is not None else None
            ),
            pressure_levels=PressureLevelsConfig.from_mapping(
                _as_mapping(pres, "pressure_levels") if pres is not None else None
            ),
            delta_levels=DeltaLevelsConfig.from_mapping(
                _as_mapping(delta, "delta_levels") if delta is not None else None
            ),
        )


@dataclass(frozen=True, slots=True)
class SystemicRiskConfig:
    """系统性风险规则阈值（Step 2 校准：死规则分位化、情绪红旗降级）。

    语义（Step 1 修正）：risk_level 是"温度读数可信度"——低=各维度共振干净，
    高=存在硬性风险事件（估值/情绪/宏观/背离），读数可能被污染或滞后；
    不是价格收益预测器。阈值经 8.9.1 审计校准：
      - valuation 原 80/70 永不可达（历史峰值 69.2），改为 p90≈60 / p80≈55；
      - macro 原 <40 永不可达（国内口径 min=46.1），改为国内口径 <50 告警；
      - composite 原 80 永不可达（峰值 68.6），红灯收敛到 65（与高温极端一致）；
      - sentiment >=80 触发后 fwd20 反而 +2.44%（方向存疑），降级为 warning，
        不参与红旗表决，仅保留触发记录。
    """

    rules_version: str = "systemic-risk-v4"
    valuation_red: float = 60.0
    valuation_warning: float = 55.0
    technical_gte: float = 60.0
    fund_flow_lt: float = 50.0
    sentiment_red: float = 200.0  # 已降级：不参与红旗表决（触发即 warning）
    sentiment_warning: float = 80.0
    sentiment_offset_below: float = 60.0
    macro_domestic_warning_below: float = 50.0  # 国内流动性偏紧告警线
    fundamental_offset_gte: float = 55.0
    fundamental_warning_below: float = 40.0
    composite_red: float = 65.0
    composite_warning: float = 60.0
    divergence_extreme: float = 15.0
    divergence_hot_fast: float = 60.0
    divergence_ice_fast: float = 35.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> Self:
        """从 YAML 字典构造风险规则阈值配置。"""
        if data is None:
            return cls()
        return cls(
            rules_version=str(data.get("rules_version", "systemic-risk-v4")),
            valuation_red=float(data.get("valuation_red", 60.0)),
            valuation_warning=float(data.get("valuation_warning", 55.0)),
            technical_gte=float(data.get("technical_gte", 60.0)),
            fund_flow_lt=float(data.get("fund_flow_lt", 50.0)),
            sentiment_red=float(data.get("sentiment_red", 200.0)),
            sentiment_warning=float(data.get("sentiment_warning", 80.0)),
            sentiment_offset_below=float(data.get("sentiment_offset_below", 60.0)),
            macro_domestic_warning_below=float(data.get("macro_domestic_warning_below", 50.0)),
            fundamental_offset_gte=float(data.get("fundamental_offset_gte", 55.0)),
            fundamental_warning_below=float(data.get("fundamental_warning_below", 40.0)),
            composite_red=float(data.get("composite_red", 65.0)),
            composite_warning=float(data.get("composite_warning", 60.0)),
            divergence_extreme=float(data.get("divergence_extreme", 15.0)),
            divergence_hot_fast=float(data.get("divergence_hot_fast", 60.0)),
            divergence_ice_fast=float(data.get("divergence_ice_fast", 35.0)),
        )


@dataclass(frozen=True, slots=True)
class MarketTemperatureConfig:
    """市场温度计顶层配置。"""

    schema_version: int
    title: str
    artifact_root: Path
    main_window: int
    short_windows: tuple[int, ...]
    dimensions: tuple[DimensionConfig, ...]
    datasets: tuple[DatasetConfig, ...]
    metric_values: MetricValuesConfig = field(default_factory=MetricValuesConfig)
    domain_mart_observations_enabled: bool = False
    bands: BandsConfig = field(default_factory=BandsConfig)
    external_risk: ExternalRiskConfig = field(default_factory=ExternalRiskConfig)
    systemic_risk: SystemicRiskConfig = field(default_factory=SystemicRiskConfig)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Self:
        """从 YAML 顶层字典构造配置对象。"""
        raw_dimensions = _as_sequence(data.get("dimensions", ()), "dimensions")
        raw_datasets = _as_sequence(data.get("datasets", ()), "datasets")
        raw_short_windows = _as_sequence(data.get("short_windows", ()), "short_windows")
        metric_values = data.get("metric_values")
        domain_mart_observations_enabled = bool(data.get("domain_mart_observations_enabled", False))
        bands = data.get("bands")
        external_risk = data.get("external_risk")
        systemic_risk = data.get("systemic_risk")
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            title=str(data.get("title", "A 股六维市场温度计")),
            artifact_root=Path(str(data.get("artifact_root", "data/analytics/market_temperature"))),
            main_window=int(data.get("main_window", 20)),
            short_windows=tuple(int(value) for value in raw_short_windows),
            dimensions=tuple(
                DimensionConfig.from_mapping(_as_mapping(item, "dimension"))
                for item in raw_dimensions
            ),
            datasets=tuple(
                DatasetConfig.from_mapping(_as_mapping(item, "dataset")) for item in raw_datasets
            ),
            metric_values=MetricValuesConfig.from_mapping(
                _as_mapping(metric_values, "metric_values") if metric_values is not None else None
            ),
            domain_mart_observations_enabled=domain_mart_observations_enabled,
            bands=BandsConfig.from_mapping(
                _as_mapping(bands, "bands") if bands is not None else None
            ),
            external_risk=ExternalRiskConfig.from_mapping(
                _as_mapping(external_risk, "external_risk") if external_risk is not None else None
            ),
            systemic_risk=SystemicRiskConfig.from_mapping(
                _as_mapping(systemic_risk, "systemic_risk") if systemic_risk is not None else None
            ),
        )

    def with_artifact_root(self, artifact_root: Path | str | None) -> Self:
        """返回覆盖产物根目录后的配置。"""
        if artifact_root is None:
            return self
        return replace(self, artifact_root=Path(artifact_root))


def load_market_temperature_config(
    config_path: Path | str = DEFAULT_CONFIG_PATH,
) -> MarketTemperatureConfig:
    """加载市场温度计 YAML 配置。"""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"市场温度计配置不存在: {path}")
    with path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file)
    root = _as_mapping(raw, "market_temperature.yaml")
    data = _as_mapping(root.get("market_temperature"), "market_temperature")
    return MarketTemperatureConfig.from_mapping(data)


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} 必须是映射对象")
    return cast("Mapping[str, Any]", value)


def _as_sequence(value: Any, name: str) -> Sequence[Any]:
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise TypeError(f"{name} 必须是列表")
    return cast("Sequence[object]", value)


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "BandsConfig",
    "DatasetConfig",
    "DeltaLevelsConfig",
    "DimensionConfig",
    "MarketTemperatureConfig",
    "MetricInputConfig",
    "MetricValuesConfig",
    "PressureLevelsConfig",
    "SystemicRiskConfig",
    "TemperatureLevelsConfig",
    "load_market_temperature_config",
]
