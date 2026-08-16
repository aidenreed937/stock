"""市场温度计配置加载。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Self, cast

import yaml

DEFAULT_CONFIG_PATH = Path("config/analytics/market_temperature.yaml")


@dataclass(frozen=True, slots=True)
class MetricInputConfig:
    """单个可计算指标的配置。"""

    metric_id: str
    aggregation: str = "latest"
    direction: str = "positive"
    weight: float = 1.0
    enabled: bool = True
    source: str = "metric_engine"

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Self:
        """从 YAML 字典构造指标配置。"""
        return cls(
            metric_id=str(data["metric_id"]),
            aggregation=str(data.get("aggregation", "latest")),
            direction=str(data.get("direction", "positive")),
            weight=float(data.get("weight", 1.0)),
            enabled=bool(data.get("enabled", True)),
            source=str(data.get("source", "metric_engine")),
        )


@dataclass(frozen=True, slots=True)
class DimensionConfig:
    """六维温度维度配置。"""

    id: str
    name: str
    weight: float
    role: str = ""
    metrics: tuple[MetricInputConfig, ...] = ()

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Self:
        """从 YAML 字典构造维度配置。"""
        raw_metrics = _as_sequence(data.get("metrics", ()), "dimensions.metrics")
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            weight=float(data["weight"]),
            role=str(data.get("role", "")),
            metrics=tuple(
                MetricInputConfig.from_mapping(_as_mapping(item, "metric")) for item in raw_metrics
            ),
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

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Self:
        """从 YAML 顶层字典构造配置对象。"""
        raw_dimensions = _as_sequence(data.get("dimensions", ()), "dimensions")
        raw_datasets = _as_sequence(data.get("datasets", ()), "datasets")
        raw_short_windows = _as_sequence(data.get("short_windows", ()), "short_windows")
        metric_values = data.get("metric_values")
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
