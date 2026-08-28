"""宏观风控管线配置加载。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class FactorConfig:
    series: str
    column: str
    window: int
    min_periods: int
    direction: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> FactorConfig:
        return cls(
            series=str(data["series"]),
            column=str(data["column"]),
            window=int(data["window"]),
            min_periods=int(data["min_periods"]),
            direction=str(data["direction"]),
        )


@dataclass(frozen=True)
class IndexComponentConfig:
    dim: str
    direction: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> IndexComponentConfig:
        return cls(
            dim=str(data["dim"]),
            direction=str(data["direction"]),
        )


@dataclass(frozen=True)
class MacroRiskConfig:
    factors: dict[str, FactorConfig]
    dims: dict[str, list[str]]
    indices: dict[str, list[IndexComponentConfig]]

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> MacroRiskConfig:
        factors = {k: FactorConfig.from_mapping(v) for k, v in data.get("factors", {}).items()}
        dims = {str(k): [str(item) for item in v] for k, v in data.get("dimensions", {}).items()}
        indices = {
            str(k): [IndexComponentConfig.from_mapping(item) for item in v]
            for k, v in data.get("indices", {}).items()
        }
        return cls(factors=factors, dims=dims, indices=indices)


def load_macro_risk_config(
    config_path: Path | str = "config/analytics/macro_risk.yaml",
) -> MacroRiskConfig:
    """加载配置。"""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return MacroRiskConfig.from_mapping(raw.get("macro_risk", {}))
