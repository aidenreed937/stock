"""个股排雷 YAML 配置加载。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Self, cast

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config/analytics/stock_screen.yaml"


@dataclass(frozen=True, slots=True)
class RuleConfig:
    """单条排雷规则配置。"""

    rule_id: str
    enabled: bool
    scope: str
    params: dict[str, Any] = field(default_factory=dict)
    note: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Self:
        raw_params = data.get("params", {})
        if raw_params is None:
            raw_params = {}
        return cls(
            rule_id=str(data.get("id", "")),
            enabled=bool(data.get("enabled", True)),
            scope=str(data.get("scope", "all_market")),
            params=dict(_as_mapping(raw_params, "rule.params")),
            note=str(data.get("note", "")),
        )


@dataclass(frozen=True, slots=True)
class DatasetConfig:
    """排雷数据集及其可用性说明。"""

    data_source: str
    dataset: str
    required: bool = False
    date_column: str = ""
    max_lag_days: int = 0
    static: bool = False
    cadence: str = "unspecified"
    quality_tier: str = "optional"
    note: str = ""
    enabled: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Self:
        return cls(
            data_source=str(data.get("data_source", "tushare")),
            dataset=str(data["dataset"]),
            enabled=bool(data.get("enabled", True)),
            required=bool(data.get("required", False)),
            date_column=str(data.get("date_column", "")),
            max_lag_days=int(data.get("max_lag_days", 0)),
            static=bool(data.get("static", False)),
            cadence=str(data.get("cadence", "unspecified")),
            quality_tier=str(data.get("quality_tier", "optional")),
            note=str(data.get("note", "")),
        )


@dataclass(frozen=True, slots=True)
class OutputConfig:
    """排雷展示产物配置。"""

    top_passed: int = 100
    max_warn_rows: int = 500

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> Self:
        data = data or {}
        return cls(
            top_passed=int(data.get("top_passed", 100)),
            max_warn_rows=int(data.get("max_warn_rows", 500)),
        )


@dataclass(frozen=True, slots=True)
class StockScreenConfig:
    """个股排雷顶层配置。"""

    schema_version: int
    title: str
    artifact_root: Path
    as_of: str | None
    symbols: tuple[str, ...]
    hard_exclusion: tuple[RuleConfig, ...]
    yellow_warn: tuple[RuleConfig, ...]
    output: OutputConfig
    datasets: tuple[DatasetConfig, ...]

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Self:
        hard_section = _as_mapping(data.get("hard_exclusion") or {}, "hard_exclusion")
        yellow_section = _as_mapping(data.get("yellow_warn") or {}, "yellow_warn")
        hard = _as_sequence(hard_section.get("rules", ()), "hard_exclusion.rules")
        yellow = _as_sequence(yellow_section.get("rules", ()), "yellow_warn.rules")
        raw_symbols = _as_sequence(data.get("symbols", ()), "symbols")
        raw_datasets = _as_sequence(data.get("datasets", ()), "datasets")
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            title=str(data.get("title", "个股排雷")),
            artifact_root=Path(str(data.get("artifact_root", "data/analytics/stock_screen"))),
            as_of=str(data["as_of"]) if data.get("as_of") is not None else None,
            symbols=tuple(str(value) for value in raw_symbols),
            hard_exclusion=tuple(
                RuleConfig.from_mapping(_as_mapping(item, "hard_exclusion.rule")) for item in hard
            ),
            yellow_warn=tuple(
                RuleConfig.from_mapping(_as_mapping(item, "yellow_warn.rule")) for item in yellow
            ),
            output=OutputConfig.from_mapping(
                _as_mapping(data.get("output"), "output")
                if data.get("output") is not None
                else None
            ),
            datasets=tuple(
                DatasetConfig.from_mapping(_as_mapping(item, "dataset")) for item in raw_datasets
            ),
        )

    def with_artifact_root(self, artifact_root: Path | str | None) -> Self:
        """返回覆盖产物根目录后的配置。"""
        return self if artifact_root is None else replace(self, artifact_root=Path(artifact_root))

    def with_symbols(self, symbols: Sequence[str] | None) -> Self:
        """返回应用运行时标的范围后的配置。"""
        return (
            self if symbols is None else replace(self, symbols=tuple(str(item) for item in symbols))
        )


def load_stock_screen_config(
    config_path: Path | str = DEFAULT_CONFIG_PATH,
) -> StockScreenConfig:
    """加载个股排雷 YAML 配置。"""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"个股排雷配置不存在: {path}")
    with path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file)
    root = _as_mapping(raw, "stock_screen.yaml")
    return StockScreenConfig.from_mapping(_as_mapping(root.get("stock_screen"), "stock_screen"))


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} 必须是映射对象")
    return cast("Mapping[str, Any]", value)


def _as_sequence(value: Any, name: str) -> Sequence[Any]:
    if value is None or isinstance(value, str) or not isinstance(value, Sequence):
        raise TypeError(f"{name} 必须是列表")
    return tuple(value)


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "DatasetConfig",
    "OutputConfig",
    "RuleConfig",
    "StockScreenConfig",
    "load_stock_screen_config",
]
