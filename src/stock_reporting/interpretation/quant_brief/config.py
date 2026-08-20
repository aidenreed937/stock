"""量化投研简报配置加载。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Self, cast

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config/analytics/quant_brief.yaml"


@dataclass(frozen=True, slots=True)
class TemperatureBandConfig:
    """综合温度档位及对应操作区间。"""

    band_id: str
    upper_bound: float | None
    label: str
    equity_position_band: str
    stance: str
    tactic: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Self:
        """从 YAML 映射构造温度档位。"""
        upper_bound = data.get("upper_bound")
        return cls(
            band_id=str(data["id"]),
            upper_bound=float(upper_bound) if upper_bound is not None else None,
            label=str(data["label"]),
            equity_position_band=str(data["equity_position_band"]),
            stance=str(data["stance"]),
            tactic=str(data["tactic"]),
        )


@dataclass(frozen=True, slots=True)
class QuantBriefConfig:
    """量化投研简报顶层配置。"""

    schema_version: int
    title: str
    artifact_root: Path
    market_temperature_root: Path
    industry_structure_root: Path
    temperature_bands: tuple[TemperatureBandConfig, ...]
    true_bull_min_fund_flow: float = 60.0
    true_bull_min_positive_60d_count: int = 25
    true_bull_min_composite_delta: float = 3.0
    pulse_min_technical: float = 60.0
    pulse_max_fund_flow: float = 50.0
    pulse_min_positive_20d_count: int = 25
    pulse_max_positive_60d_count: int = 5
    crowded_industry_share: float = 30.0
    crowding_temperature: float = 80.0
    top5pct_share: float = 0.5
    high_heat_valuation: float = 80.0
    high_heat_sentiment: float = 80.0
    margin_negative_threshold: float = 0.0
    max_crowded_industries: int = 8
    max_priority_industries: int = 5
    max_avoid_industries: int = 5
    max_lagging_industries: int = 5
    min_priority_structure_score: float = 50.0
    require_fund_flow_confirmation: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Self:
        """从 YAML 字典构造配置对象。"""
        raw_bands = _as_sequence(data.get("temperature_bands"), "temperature_bands")
        if not raw_bands:
            raise ValueError("quant_brief.temperature_bands 不能为空")
        nature = _as_mapping(data.get("nature", {}), "nature")
        veto = _as_mapping(data.get("veto", {}), "veto")
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            title=str(data.get("title", "A 股量化投研简报")),
            artifact_root=Path(str(data.get("artifact_root", "data/analytics/quant_brief"))),
            market_temperature_root=Path(
                str(data.get("market_temperature_root", "data/analytics/market_temperature"))
            ),
            industry_structure_root=Path(
                str(data.get("industry_structure_root", "data/analytics/industry_structure"))
            ),
            temperature_bands=tuple(
                TemperatureBandConfig.from_mapping(_as_mapping(item, "temperature_band"))
                for item in raw_bands
            ),
            true_bull_min_fund_flow=float(nature.get("true_bull_min_fund_flow", 60.0)),
            true_bull_min_positive_60d_count=int(
                nature.get("true_bull_min_positive_60d_count", 25)
            ),
            true_bull_min_composite_delta=float(nature.get("true_bull_min_composite_delta", 3.0)),
            pulse_min_technical=float(nature.get("pulse_min_technical", 60.0)),
            pulse_max_fund_flow=float(nature.get("pulse_max_fund_flow", 50.0)),
            pulse_min_positive_20d_count=int(nature.get("pulse_min_positive_20d_count", 25)),
            pulse_max_positive_60d_count=int(nature.get("pulse_max_positive_60d_count", 5)),
            crowded_industry_share=float(veto.get("crowded_industry_share", 30.0)),
            crowding_temperature=float(veto.get("crowding_temperature", 80.0)),
            top5pct_share=float(veto.get("top5pct_share", 0.5)),
            high_heat_valuation=float(veto.get("high_heat_valuation", 80.0)),
            high_heat_sentiment=float(veto.get("high_heat_sentiment", 80.0)),
            margin_negative_threshold=float(veto.get("margin_negative_threshold", 0.0)),
            max_crowded_industries=int(veto.get("max_crowded_industries", 8)),
            max_priority_industries=int(veto.get("max_priority_industries", 5)),
            max_avoid_industries=int(veto.get("max_avoid_industries", 5)),
            max_lagging_industries=int(veto.get("max_lagging_industries", 5)),
            min_priority_structure_score=float(veto.get("min_priority_structure_score", 50.0)),
            require_fund_flow_confirmation=bool(veto.get("require_fund_flow_confirmation", True)),
        )

    def with_artifact_root(self, artifact_root: Path | str | None) -> Self:
        """返回覆盖产物根目录后的配置。"""
        if artifact_root is None:
            return self
        return replace(self, artifact_root=Path(artifact_root))


def load_quant_brief_config(
    config_path: Path | str = DEFAULT_CONFIG_PATH,
) -> QuantBriefConfig:
    """加载量化投研简报 YAML 配置。"""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"量化投研简报配置不存在: {path}")
    with path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file)
    root = _as_mapping(raw, "quant_brief.yaml")
    data = _as_mapping(root.get("quant_brief"), "quant_brief")
    return QuantBriefConfig.from_mapping(data)


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
    "QuantBriefConfig",
    "TemperatureBandConfig",
    "load_quant_brief_config",
]
