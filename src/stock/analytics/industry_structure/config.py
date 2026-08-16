"""行业结构分析配置加载。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Self, cast

import yaml

DEFAULT_CONFIG_PATH = Path("config/analytics/industry_structure.yaml")


@dataclass(frozen=True, slots=True)
class ScoreWeights:
    """行业结构四类子分权重。"""

    momentum: float = 0.40
    valuation: float = 0.25
    fundamental: float = 0.15
    crowding: float = 0.20

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> Self:
        """从 YAML 字典构造评分权重。"""
        if data is None:
            return cls()
        return cls(
            momentum=float(data.get("momentum", 0.40)),
            valuation=float(data.get("valuation", 0.25)),
            fundamental=float(data.get("fundamental", 0.15)),
            crowding=float(data.get("crowding", 0.20)),
        )

    def as_dict(self) -> dict[str, float]:
        """转换为普通字典，便于 JSON 输出。"""
        return {
            "momentum": self.momentum,
            "valuation": self.valuation,
            "fundamental": self.fundamental,
            "crowding": self.crowding,
        }


@dataclass(frozen=True, slots=True)
class FundamentalBlendConfig:
    """行业基本面正式财报与快速确认指标的合成配置。"""

    stale_after_days: int = 90
    official_weight: float = 0.70
    fast_weight: float = 0.30
    stale_official_weight: float = 0.40
    stale_fast_weight: float = 0.60

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> Self:
        """从 YAML 字典构造基本面合成配置。"""
        if data is None:
            return cls()
        return cls(
            stale_after_days=int(data.get("stale_after_days", 90)),
            official_weight=float(data.get("official_weight", 0.70)),
            fast_weight=float(data.get("fast_weight", 0.30)),
            stale_official_weight=float(data.get("stale_official_weight", 0.40)),
            stale_fast_weight=float(data.get("stale_fast_weight", 0.60)),
        )

    def as_dict(self) -> dict[str, float | int]:
        """转换为普通字典，便于 JSON 输出。"""
        return {
            "stale_after_days": self.stale_after_days,
            "official_weight": self.official_weight,
            "fast_weight": self.fast_weight,
            "stale_official_weight": self.stale_official_weight,
            "stale_fast_weight": self.stale_fast_weight,
        }


@dataclass(frozen=True, slots=True)
class DatasetConfig:
    """事实层数据集水位配置。"""

    data_source: str
    dataset: str
    required: bool = False
    date_column: str = ""
    max_lag_days: int = 0
    static: bool = False
    note: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Self:
        """从 YAML 字典构造数据集配置。"""
        return cls(
            data_source=str(data["data_source"]),
            dataset=str(data["dataset"]),
            required=bool(data.get("required", False)),
            date_column=str(data.get("date_column", "")),
            max_lag_days=int(data.get("max_lag_days", 0)),
            static=bool(data.get("static", False)),
            note=str(data.get("note", "")),
        )


@dataclass(frozen=True, slots=True)
class IndustryStructureConfig:
    """行业结构分析顶层配置。"""

    schema_version: int
    title: str
    artifact_root: Path
    main_window: int
    short_windows: tuple[int, ...]
    medium_windows: tuple[int, ...]
    classification: str
    benchmark: str
    score_weights: ScoreWeights
    fundamental_blend: FundamentalBlendConfig
    datasets: tuple[DatasetConfig, ...]

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Self:
        """从 YAML 顶层字典构造配置对象。"""
        raw_short_windows = _as_sequence(data.get("short_windows", ()), "short_windows")
        raw_medium_windows = _as_sequence(data.get("medium_windows", ()), "medium_windows")
        raw_datasets = _as_sequence(data.get("datasets", ()), "datasets")
        score_weights = data.get("score_weights")
        fundamental_blend = data.get("fundamental_blend")
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            title=str(data.get("title", "申万行业结构分析")),
            artifact_root=Path(str(data.get("artifact_root", "data/analytics/industry_structure"))),
            main_window=int(data.get("main_window", 20)),
            short_windows=tuple(int(value) for value in raw_short_windows),
            medium_windows=tuple(int(value) for value in raw_medium_windows),
            classification=str(data.get("classification", "SW2021")),
            benchmark=str(data.get("benchmark", "000985")),
            score_weights=ScoreWeights.from_mapping(
                _as_mapping(score_weights, "score_weights") if score_weights is not None else None
            ),
            fundamental_blend=FundamentalBlendConfig.from_mapping(
                _as_mapping(fundamental_blend, "fundamental_blend")
                if fundamental_blend is not None
                else None
            ),
            datasets=tuple(
                DatasetConfig.from_mapping(_as_mapping(item, "dataset")) for item in raw_datasets
            ),
        )

    def with_artifact_root(self, artifact_root: Path | str | None) -> Self:
        """返回覆盖产物根目录后的配置。"""
        if artifact_root is None:
            return self
        return replace(self, artifact_root=Path(artifact_root))

    @property
    def windows(self) -> tuple[int, ...]:
        """返回所有需要保留的交易窗口。"""
        return tuple(sorted({self.main_window, *self.short_windows, *self.medium_windows}))


def load_industry_structure_config(
    config_path: Path | str = DEFAULT_CONFIG_PATH,
) -> IndustryStructureConfig:
    """加载行业结构 YAML 配置。"""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"行业结构配置不存在: {path}")
    with path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file)
    root = _as_mapping(raw, "industry_structure.yaml")
    data = _as_mapping(root.get("industry_structure"), "industry_structure")
    return IndustryStructureConfig.from_mapping(data)


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
