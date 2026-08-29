"""中观产业与行业量化诊断管线配置。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path("config/analytics/industry_diagnostics.yaml")


@dataclass(frozen=True)
class TechnicalsConfig:
    ma_short_window: int = 20
    ma_medium_window: int = 60
    rsi_window: int = 14

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> TechnicalsConfig:
        return cls(
            ma_short_window=int(data.get("ma_short_window", data.get("ma_short", 20))),
            ma_medium_window=int(data.get("ma_medium_window", data.get("ma_medium", 60))),
            rsi_window=int(data.get("rsi_window", data.get("rsi", 14))),
        )


@dataclass(frozen=True)
class ValuationConfig:
    percentile_5y_window: int = 1250
    percentile_10y_window: int = 2500
    min_periods: int = 500
    threshold_low: float = 20.0
    threshold_fair: float = 40.0
    threshold_neutral: float = 70.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ValuationConfig:
        return cls(
            percentile_5y_window=int(data.get("percentile_5y_window", data.get("window_5y", 1250))),
            percentile_10y_window=int(
                data.get("percentile_10y_window", data.get("window_10y", 2500))
            ),
            min_periods=int(data.get("min_periods", 500)),
            threshold_low=float(data.get("threshold_low", 20.0)),
            threshold_fair=float(data.get("threshold_fair", 40.0)),
            threshold_neutral=float(data.get("threshold_neutral", 70.0)),
        )


@dataclass(frozen=True)
class ScoreWeightsConfig:
    momentum: float = 0.30
    valuation: float = 0.25
    fundamental: float = 0.25
    crowding: float = 0.20

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ScoreWeightsConfig:
        return cls(
            momentum=float(data.get("momentum", 0.30)),
            valuation=float(data.get("valuation", 0.25)),
            fundamental=float(data.get("fundamental", 0.25)),
            crowding=float(data.get("crowding", 0.20)),
        )


@dataclass(frozen=True)
class ValuationWeightsConfig:
    pb_weight: float = 0.50
    pe_weight: float = 0.50

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ValuationWeightsConfig:
        return cls(
            pb_weight=float(data.get("pb_weight", 0.50)),
            pe_weight=float(data.get("pe_weight", 0.50)),
        )


@dataclass(frozen=True)
class ArchetypeConfig:
    title: str = "通用制造与消费"
    keywords: tuple[str, ...] = ()
    valuation_weights: ValuationWeightsConfig = field(default_factory=ValuationWeightsConfig)
    score_weights: ScoreWeightsConfig = field(default_factory=ScoreWeightsConfig)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ArchetypeConfig:
        vw = data.get("valuation_weights", {})
        sw = data.get("score_weights", {})
        kw = data.get("keywords", [])
        return cls(
            title=str(data.get("title", "通用制造与消费")),
            keywords=tuple(str(k) for k in kw),
            valuation_weights=ValuationWeightsConfig.from_mapping(vw)
            if isinstance(vw, Mapping)
            else ValuationWeightsConfig(),
            score_weights=ScoreWeightsConfig.from_mapping(sw)
            if isinstance(sw, Mapping)
            else ScoreWeightsConfig(),
        )


@dataclass(frozen=True)
class IndustryThresholdsConfig:
    top_leaders_count: int = 5
    max_constituents_eval: int = 200
    momentum_bias_limit: float = 10.0
    rsi_overbought: float = 75.0
    rsi_oversold: float = 25.0
    roe_high: float = 18.0
    roe_mid: float = 12.0
    roe_low: float = 6.0
    growth_fast: float = 20.0
    growth_slump: float = -20.0
    scissors_positive: float = 5.0
    scissors_negative: float = -10.0
    cr5_crowded: float = 80.0
    breadth_severe_divergence: float = 30.0
    breadth_mild_divergence: float = 45.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> IndustryThresholdsConfig:
        return cls(
            top_leaders_count=int(data.get("top_leaders_count", 5)),
            max_constituents_eval=int(data.get("max_constituents_eval", 200)),
            momentum_bias_limit=float(data.get("momentum_bias_limit", 10.0)),
            rsi_overbought=float(data.get("rsi_overbought", 75.0)),
            rsi_oversold=float(data.get("rsi_oversold", 25.0)),
            roe_high=float(data.get("roe_high", 18.0)),
            roe_mid=float(data.get("roe_mid", 12.0)),
            roe_low=float(data.get("roe_low", 6.0)),
            growth_fast=float(data.get("growth_fast", 20.0)),
            growth_slump=float(data.get("growth_slump", -20.0)),
            scissors_positive=float(data.get("scissors_positive", 5.0)),
            scissors_negative=float(data.get("scissors_negative", -10.0)),
            cr5_crowded=float(data.get("cr5_crowded", 80.0)),
            breadth_severe_divergence=float(data.get("breadth_severe_divergence", 30.0)),
            breadth_mild_divergence=float(data.get("breadth_mild_divergence", 45.0)),
        )


@dataclass(frozen=True)
class VetoRulesConfig:
    profit_decay_threshold: float = -30.0
    revenue_decay_threshold: float = -15.0
    overheat_turnover_percentile: float = 90.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> VetoRulesConfig:
        return cls(
            profit_decay_threshold=float(data.get("profit_decay_threshold", -30.0)),
            revenue_decay_threshold=float(data.get("revenue_decay_threshold", -15.0)),
            overheat_turnover_percentile=float(data.get("overheat_turnover_percentile", 90.0)),
        )


@dataclass(frozen=True)
class IndustryDiagnosticsConfig:
    technicals: TechnicalsConfig = field(default_factory=TechnicalsConfig)
    valuation: ValuationConfig = field(default_factory=ValuationConfig)
    score_weights: ScoreWeightsConfig = field(default_factory=ScoreWeightsConfig)
    archetypes: dict[str, ArchetypeConfig] = field(default_factory=dict)
    thresholds: IndustryThresholdsConfig = field(default_factory=IndustryThresholdsConfig)
    veto_rules: VetoRulesConfig = field(default_factory=VetoRulesConfig)
    value_chain_map_path: Path | str = "config/industry/value_chain_map.yaml"
    schema_version: int = 1
    artifact_type: str = "industry_diagnostics"
    title: str = "中观产业与行业量化深度诊断"
    artifact_root: str = "data/analytics/industry_diagnostics"
    raw_datasets: list[dict[str, Any]] = field(default_factory=list)

    def resolve_archetype(self, industry_name: str) -> ArchetypeConfig:
        """根据行业名称匹配原型配置，无匹配时返回 general 或默认原型。"""
        for key, arch in self.archetypes.items():
            if key == "general":
                continue
            for kw in arch.keywords:
                if kw in industry_name:
                    return arch
        if "general" in self.archetypes:
            return self.archetypes["general"]
        return ArchetypeConfig()

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> IndustryDiagnosticsConfig:
        windows = data.get("windows", {})
        tech_data = windows.get("technicals", data.get("technicals", {}))
        val_data = windows.get("valuation", data.get("valuation", {}))
        weights_data = data.get("score_weights", {})
        veto_data = data.get("veto_rules", {})
        thresh_data = data.get("thresholds", {})
        raw_archetypes = data.get("archetypes", {})
        raw_datasets = data.get("datasets", [])

        archetypes_map = {
            str(k): ArchetypeConfig.from_mapping(v)
            for k, v in raw_archetypes.items()
            if isinstance(v, Mapping)
        }

        return cls(
            technicals=TechnicalsConfig.from_mapping(tech_data)
            if isinstance(tech_data, Mapping)
            else TechnicalsConfig(),
            valuation=ValuationConfig.from_mapping(val_data)
            if isinstance(val_data, Mapping)
            else ValuationConfig(),
            score_weights=ScoreWeightsConfig.from_mapping(weights_data)
            if isinstance(weights_data, Mapping)
            else ScoreWeightsConfig(),
            archetypes=archetypes_map,
            thresholds=IndustryThresholdsConfig.from_mapping(thresh_data)
            if isinstance(thresh_data, Mapping)
            else IndustryThresholdsConfig(),
            veto_rules=VetoRulesConfig.from_mapping(veto_data)
            if isinstance(veto_data, Mapping)
            else VetoRulesConfig(),
            value_chain_map_path=str(
                data.get("value_chain_map_path", "config/industry/value_chain_map.yaml")
            ),
            schema_version=int(data.get("schema_version", 1)),
            artifact_type=str(data.get("artifact_type", "industry_diagnostics")),
            title=str(data.get("title", "中观产业与行业量化深度诊断")),
            artifact_root=str(data.get("artifact_root", "data/analytics/industry_diagnostics")),
            raw_datasets=list(raw_datasets) if isinstance(raw_datasets, list) else [],
        )


def load_industry_diagnostics_config(
    config_path: Path | str | None = None,
) -> IndustryDiagnosticsConfig:
    """加载行业量化诊断配置。若文件不存在则返回默认配置。"""
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not path.exists():
        return IndustryDiagnosticsConfig()
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return IndustryDiagnosticsConfig.from_mapping(raw.get("industry_diagnostics", raw))
