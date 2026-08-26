"""量化投研简报配置加载。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
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
class CrossCycleConfig:
    """跨周期胜率/赔率矩阵配置（初始机制草案，待 61 天回测校准）。

    分值均为环境级评分分量：S=胜率环境、O=赔率环境，数值为正偏积极、为负偏谨慎。
    阈值与分值来源见 docs/research/cross_cycle_odds_matrix_design.md 第 4 节。
    """

    # 胜率环境 S：快慢背离等级
    win_sync_bonus: float = 10.0
    win_ice_extreme_penalty: float = -15.0
    win_hot_extreme_penalty: float = -10.0
    # S：短线温度位置
    short_ice_threshold: float = 35.0
    short_hot_threshold: float = 65.0
    win_short_ice_bonus: float = 10.0
    win_short_hot_penalty: float = -10.0
    # S：技术宽度
    width_healthy_threshold: float = 0.60
    width_weak_threshold: float = 0.40
    win_width_healthy_bonus: float = 10.0
    win_width_weak_penalty: float = -10.0
    # S：主力资金与外部冲击
    win_fund_confirmed_bonus: float = 10.0
    win_fund_outflow_penalty: float = -10.0
    win_external_pending_penalty: float = -10.0
    # S 档位映射
    win_level_high: float = 5.0
    win_level_low: float = -25.0

    # 赔率环境 O：慢温度/估值分位
    slow_low_threshold: float = 50.0
    slow_high_threshold: float = 65.0
    odds_slow_low_bonus: float = 20.0
    odds_slow_high_penalty: float = -10.0
    valuation_low_threshold: float = 40.0
    valuation_high_threshold: float = 70.0
    odds_valuation_low_bonus: float = 10.0
    odds_valuation_high_penalty: float = -10.0
    # O：行业扩散
    diffusion_low_threshold: float = 30.0
    diffusion_high_threshold: float = 60.0
    odds_diffusion_low_bonus: float = 10.0
    odds_diffusion_high_penalty: float = -10.0
    # O：拥挤占比
    crowding_share_threshold: float = 10.0
    odds_crowding_none_bonus: float = 10.0
    odds_crowding_high_penalty: float = -10.0
    # O：宏观流动性与外盘压力
    macro_loose_threshold: float = 40.0
    macro_tight_threshold: float = 65.0
    odds_macro_loose_bonus: float = 10.0
    odds_macro_tight_penalty: float = -10.0
    external_pressure_threshold: float = 75.0
    odds_external_pressure_penalty: float = -10.0
    # O 档位映射
    odds_level_high: float = 5.0
    odds_level_low: float = -10.0

    # 轨迹修正（作用于 S/O 最终分）
    trajectory_convergence_bonus: float = 5.0
    trajectory_deterioration_penalty: float = -5.0
    trajectory_rising_bonus: float = 5.0
    trajectory_falling_penalty: float = -5.0
    composite_trend_window: int = 5

    # 象限仓位微调（ppe）
    adj_core_pp: float = 0.0
    adj_left_pp: float = -7.0
    adj_band_pp: float = -5.0
    adj_avoid_pp: float = -5.0
    rules_version: str = "odds-matrix-v1"

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Self:
        """从 YAML 映射构造跨周期矩阵配置。"""

        def number(name: str, default: float) -> float:
            return float(data.get(name, default))

        return cls(
            win_sync_bonus=number("win_sync_bonus", 20.0),
            win_ice_extreme_penalty=number("win_ice_extreme_penalty", -30.0),
            win_hot_extreme_penalty=number("win_hot_extreme_penalty", -20.0),
            short_ice_threshold=number("short_ice_threshold", 35.0),
            short_hot_threshold=number("short_hot_threshold", 65.0),
            win_short_ice_bonus=number("win_short_ice_bonus", 10.0),
            win_short_hot_penalty=number("win_short_hot_penalty", -10.0),
            width_healthy_threshold=number("width_healthy_threshold", 0.60),
            width_weak_threshold=number("width_weak_threshold", 0.40),
            win_width_healthy_bonus=number("win_width_healthy_bonus", 10.0),
            win_width_weak_penalty=number("win_width_weak_penalty", -10.0),
            win_fund_confirmed_bonus=number("win_fund_confirmed_bonus", 10.0),
            win_fund_outflow_penalty=number("win_fund_outflow_penalty", -10.0),
            win_external_pending_penalty=number("win_external_pending_penalty", -10.0),
            win_level_high=number("win_level_high", 30.0),
            win_level_low=number("win_level_low", -10.0),
            slow_low_threshold=number("slow_low_threshold", 50.0),
            slow_high_threshold=number("slow_high_threshold", 65.0),
            odds_slow_low_bonus=number("odds_slow_low_bonus", 20.0),
            odds_slow_high_penalty=number("odds_slow_high_penalty", -10.0),
            valuation_low_threshold=number("valuation_low_threshold", 40.0),
            valuation_high_threshold=number("valuation_high_threshold", 70.0),
            odds_valuation_low_bonus=number("odds_valuation_low_bonus", 10.0),
            odds_valuation_high_penalty=number("odds_valuation_high_penalty", -10.0),
            diffusion_low_threshold=number("diffusion_low_threshold", 30.0),
            diffusion_high_threshold=number("diffusion_high_threshold", 60.0),
            odds_diffusion_low_bonus=number("odds_diffusion_low_bonus", 10.0),
            odds_diffusion_high_penalty=number("odds_diffusion_high_penalty", -10.0),
            crowding_share_threshold=number("crowding_share_threshold", 10.0),
            odds_crowding_none_bonus=number("odds_crowding_none_bonus", 10.0),
            odds_crowding_high_penalty=number("odds_crowding_high_penalty", -10.0),
            macro_loose_threshold=number("macro_loose_threshold", 40.0),
            macro_tight_threshold=number("macro_tight_threshold", 65.0),
            odds_macro_loose_bonus=number("odds_macro_loose_bonus", 10.0),
            odds_macro_tight_penalty=number("odds_macro_tight_penalty", -10.0),
            external_pressure_threshold=number("external_pressure_threshold", 75.0),
            odds_external_pressure_penalty=number("odds_external_pressure_penalty", -10.0),
            odds_level_high=number("odds_level_high", 20.0),
            odds_level_low=number("odds_level_low", -10.0),
            trajectory_convergence_bonus=number("trajectory_convergence_bonus", 10.0),
            trajectory_deterioration_penalty=number("trajectory_deterioration_penalty", -20.0),
            trajectory_rising_bonus=number("trajectory_rising_bonus", 5.0),
            trajectory_falling_penalty=number("trajectory_falling_penalty", -5.0),
            composite_trend_window=int(data.get("composite_trend_window", 5)),
            adj_core_pp=number("adj_core_pp", 0.0),
            adj_left_pp=number("adj_left_pp", -7.0),
            adj_band_pp=number("adj_band_pp", -5.0),
            adj_avoid_pp=number("adj_avoid_pp", -10.0),
            rules_version=str(data.get("rules_version", "odds-matrix-v1")),
        )


@dataclass(frozen=True, slots=True)
class QuantBriefConfig:
    """量化投研简报顶层配置。"""

    schema_version: int
    title: str
    artifact_root: Path
    latest_root: Path
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
    valuation_red_flag_temperature: float = 85.0
    composite_red_flag_temperature: float = 65.0
    defensive_position_band: str = "0%-30%"
    divergence_extreme_threshold: float = 15.0
    divergence_hot_fast_temperature: float = 60.0
    divergence_ice_fast_temperature: float = 35.0
    cross_cycle: CrossCycleConfig = field(default_factory=CrossCycleConfig)
    main_money_outflow_share_hard: float = -0.05
    market_amount_high_percentile: float = 90.0
    margin_buy_share_warning: float = 0.10
    margin_penetration_extreme_percentile: float = 95.0
    breadth_above_ma60_healthy: float = 0.50
    breadth_above_ma60_weak: float = 0.30
    positive_20d_sector_min: int = 10
    industry_tcr_warning: float = 20.0
    industry_tcr_hard: float = 25.0
    industry_crowding_hard_temperature: float = 90.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Self:
        """从 YAML 字典构造配置对象。"""
        raw_bands = _as_sequence(data.get("temperature_bands"), "temperature_bands")
        if not raw_bands:
            raise ValueError("quant_brief.temperature_bands 不能为空")
        nature = _as_mapping(data.get("nature", {}), "nature")
        veto = _as_mapping(data.get("veto", {}), "veto")
        risk_gates = _as_mapping(data.get("risk_gates", {}), "risk_gates")
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            title=str(data.get("title", "A 股量化投研简报")),
            artifact_root=Path(str(data.get("artifact_root", "data/analytics/quant_brief"))),
            latest_root=Path(str(data.get("latest_root", "data/analytics/quant_brief"))),
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
            valuation_red_flag_temperature=float(
                risk_gates.get("valuation_red_flag_temperature", 85.0)
            ),
            composite_red_flag_temperature=float(
                risk_gates.get("composite_red_flag_temperature", 65.0)
            ),
            defensive_position_band=str(risk_gates.get("defensive_position_band", "0%-30%")),
            divergence_extreme_threshold=float(
                risk_gates.get("divergence_extreme_threshold", 15.0)
            ),
            divergence_hot_fast_temperature=float(
                risk_gates.get("divergence_hot_fast_temperature", 60.0)
            ),
            divergence_ice_fast_temperature=float(
                risk_gates.get("divergence_ice_fast_temperature", 35.0)
            ),
            cross_cycle=CrossCycleConfig.from_mapping(
                _as_mapping(data.get("cross_cycle", {}), "cross_cycle")
            ),
            main_money_outflow_share_hard=float(
                risk_gates.get("main_money_outflow_share_hard", -0.05)
            ),
            market_amount_high_percentile=float(
                risk_gates.get("market_amount_high_percentile", 90.0)
            ),
            margin_buy_share_warning=float(risk_gates.get("margin_buy_share_warning", 0.10)),
            margin_penetration_extreme_percentile=float(
                risk_gates.get("margin_penetration_extreme_percentile", 95.0)
            ),
            breadth_above_ma60_healthy=float(risk_gates.get("breadth_above_ma60_healthy", 0.50)),
            breadth_above_ma60_weak=float(risk_gates.get("breadth_above_ma60_weak", 0.30)),
            positive_20d_sector_min=int(risk_gates.get("positive_20d_sector_min", 10)),
            industry_tcr_warning=float(risk_gates.get("industry_tcr_warning", 20.0)),
            industry_tcr_hard=float(risk_gates.get("industry_tcr_hard", 25.0)),
            industry_crowding_hard_temperature=float(
                risk_gates.get("industry_crowding_hard_temperature", 90.0)
            ),
        )

    def with_artifact_root(self, artifact_root: Path | str | None) -> Self:
        """返回覆盖产物根目录后的配置。"""
        if artifact_root is None:
            return self
        root = Path(artifact_root)
        return replace(self, artifact_root=root, latest_root=root)


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
    "CrossCycleConfig",
    "QuantBriefConfig",
    "TemperatureBandConfig",
    "load_quant_brief_config",
]
