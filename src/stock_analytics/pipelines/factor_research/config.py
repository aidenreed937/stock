"""因子准入评估管线配置。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Self

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config/analytics/factor_research.yaml"

_DEFAULT_ALLOWED_UNITS = ("ratio", "percent", "percentile", "zscore", "score_0_100")


@dataclass(frozen=True, slots=True)
class FactorResearchThresholds:
    """因子准入判定阈值。"""

    icir: float = 0.5
    t_stat: float = 2.0
    long_short_mean: float = 0.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Self:
        """从 YAML 映射构造阈值。"""
        return cls(
            icir=float(data.get("icir", 0.5)),
            t_stat=float(data.get("t_stat", 2.0)),
            long_short_mean=float(data.get("long_short_mean", 0.0)),
        )


@dataclass(frozen=True, slots=True)
class FactorResearchConfig:
    """因子准入评估管线配置。"""

    schema_version: int = 1
    title: str = "因子准入评估报告"
    artifact_root: str = "data/analytics/factor_research"
    window_days: int = 730
    horizons: tuple[int, ...] = (1, 5, 20)
    decision_horizon: int = 5
    n_bins: int = 5
    price_col: str = "close"
    quantile_horizon: int = 20
    min_ic_days: int = 60
    thresholds: FactorResearchThresholds = field(default_factory=FactorResearchThresholds)
    allowed_units: tuple[str, ...] = _DEFAULT_ALLOWED_UNITS
    factor_whitelist: tuple[str, ...] = ()

    def with_artifact_root(self, output_root: Path | str | None) -> Self:
        """覆盖产物根目录（CLI --output-root）。"""
        if output_root is None:
            return self
        return replace(self, artifact_root=str(Path(output_root)))

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Self:
        """从 YAML 映射构造配置。"""
        horizons = tuple(int(h) for h in data.get("horizons", (1, 5, 20)))
        whitelist = tuple(str(f) for f in data.get("factor_whitelist", ()))
        threshold_map = data.get("thresholds", {})
        thresholds = (
            FactorResearchThresholds.from_mapping(threshold_map)
            if isinstance(threshold_map, Mapping)
            else FactorResearchThresholds()
        )
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            title=str(data.get("title", "因子准入评估报告")),
            artifact_root=str(data.get("artifact_root", "data/analytics/factor_research")),
            window_days=int(data.get("window_days", 730)),
            horizons=horizons,
            decision_horizon=int(data.get("decision_horizon", 5)),
            n_bins=int(data.get("n_bins", 5)),
            price_col=str(data.get("price_col", "close")),
            quantile_horizon=int(data.get("quantile_horizon", 20)),
            min_ic_days=int(data.get("min_ic_days", 60)),
            thresholds=thresholds,
            allowed_units=tuple(str(u) for u in data.get("allowed_units", _DEFAULT_ALLOWED_UNITS)),
            factor_whitelist=whitelist,
        )


def load_factor_research_config(
    config_path: Path | str = DEFAULT_CONFIG_PATH,
) -> FactorResearchConfig:
    """加载因子准入评估配置。"""
    with open(config_path, encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    section = raw.get("factor_research", raw)
    if not isinstance(section, Mapping):
        raise ValueError(f"配置缺少 factor_research 节: {config_path}")
    return FactorResearchConfig.from_mapping(section)


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "FactorResearchConfig",
    "FactorResearchThresholds",
    "load_factor_research_config",
]
