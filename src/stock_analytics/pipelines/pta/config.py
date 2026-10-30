"""精对苯二甲酸 (PTA) 全景基本面对账管线配置。

配置来源: ``config/analytics/pta.yaml``；文件缺失或字段非法时回退默认值。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = "config/analytics/pta.yaml"

_ARTIFACT_ROOT_DEFAULT = "data/analytics/pta"
_TITLE_DEFAULT = "精对苯二甲酸 (PTA) 全景基本面对账研报"


@dataclass(frozen=True, slots=True)
class InputsConfig:
    """管线输入源定位。"""

    capacity_projects: str = "config/industry/chemicals/pta/capacity_projects.yaml"
    trading_gates: str = "config/industry/chemicals/pta/trading_gates.yaml"
    cost_models: str = "config/industry/chemicals/pta/cost_models.yaml"
    company_projections: str = "config/industry/chemicals/pta/company_projections.yaml"
    customs_trade_dataset: str = "customs_trade_gacc"
    customs_trade_fallback: str = "customs_trade"
    chemical_spot_price_dataset: str = "chemical_spot_price"
    chemical_spreads_dataset: str = "chemical_spreads"
    chemical_futures_daily_dataset: str = "chemical_futures_daily"
    futures_inventory_czce_dataset: str = "futures_inventory_czce"
    chemical_capacity_utilization_dataset: str = "chemical_capacity_utilization_10y"
    chemical_market_dataset: str = "chemical_market"
    company_panel_dataset: str = "mart/pta_company_panel"
    industry_l2_daily_dataset: str = "mart/industry_l2_daily"


@dataclass(frozen=True, slots=True)
class RegimeThresholds:
    """大宗标准化蓄水池状态机阈值。"""

    scissors_spread_min: float = 0.0
    operating_rate_max: float = 75.0
    operating_rate_top_min: float = 88.0
    export_volume_yoy_min: float = 15.0
    destocking_weeks_min: int = 3
    delta_receipt_epsilon: float = 0.01


@dataclass(frozen=True, slots=True)
class HistoryConfig:
    """历史周期大拐点检测配置。"""

    high_profit_margin: float = 600.0
    deep_loss_margin: float = 350.0
    min_episode_months: int = 2
    max_episodes: int = 6
    follow_up_months: int = 3


@dataclass(frozen=True, slots=True)
class PtaConfig:
    """PTA 全景对账管线配置。"""

    schema_version: int = 1
    title: str = _TITLE_DEFAULT
    artifact_root: str = _ARTIFACT_ROOT_DEFAULT
    inputs: InputsConfig = InputsConfig()
    regime: RegimeThresholds = RegimeThresholds()
    history: HistoryConfig = HistoryConfig()


def _str(value: Any, default: str) -> str:
    if value is None:
        return default
    return str(value)


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _integer(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_inputs(raw: Any) -> InputsConfig:
    if not isinstance(raw, dict):
        return InputsConfig()
    defaults = InputsConfig()
    return InputsConfig(
        capacity_projects=_str(raw.get("capacity_projects"), defaults.capacity_projects),
        trading_gates=_str(raw.get("trading_gates"), defaults.trading_gates),
        cost_models=_str(raw.get("cost_models"), defaults.cost_models),
        company_projections=_str(raw.get("company_projections"), defaults.company_projections),
        customs_trade_dataset=_str(
            raw.get("customs_trade_dataset"), defaults.customs_trade_dataset
        ),
        customs_trade_fallback=_str(
            raw.get("customs_trade_fallback"), defaults.customs_trade_fallback
        ),
        chemical_spot_price_dataset=_str(
            raw.get("chemical_spot_price_dataset"), defaults.chemical_spot_price_dataset
        ),
        chemical_spreads_dataset=_str(
            raw.get("chemical_spreads_dataset"), defaults.chemical_spreads_dataset
        ),
        chemical_futures_daily_dataset=_str(
            raw.get("chemical_futures_daily_dataset"), defaults.chemical_futures_daily_dataset
        ),
        futures_inventory_czce_dataset=_str(
            raw.get("futures_inventory_czce_dataset"), defaults.futures_inventory_czce_dataset
        ),
        chemical_capacity_utilization_dataset=_str(
            raw.get("chemical_capacity_utilization_dataset"),
            defaults.chemical_capacity_utilization_dataset,
        ),
        chemical_market_dataset=_str(
            raw.get("chemical_market_dataset"), defaults.chemical_market_dataset
        ),
        company_panel_dataset=_str(
            raw.get("company_panel_dataset"), defaults.company_panel_dataset
        ),
        industry_l2_daily_dataset=_str(
            raw.get("industry_l2_daily_dataset"), defaults.industry_l2_daily_dataset
        ),
    )


def _parse_regime(raw: Any) -> RegimeThresholds:
    if not isinstance(raw, dict):
        return RegimeThresholds()
    defaults = RegimeThresholds()
    return RegimeThresholds(
        scissors_spread_min=_number(raw.get("scissors_spread_min"), defaults.scissors_spread_min),
        operating_rate_max=_number(raw.get("operating_rate_max"), defaults.operating_rate_max),
        operating_rate_top_min=_number(
            raw.get("operating_rate_top_min"), defaults.operating_rate_top_min
        ),
        export_volume_yoy_min=_number(
            raw.get("export_volume_yoy_min"), defaults.export_volume_yoy_min
        ),
        destocking_weeks_min=_integer(
            raw.get("destocking_weeks_min"), defaults.destocking_weeks_min
        ),
        delta_receipt_epsilon=_number(
            raw.get("delta_receipt_epsilon"), defaults.delta_receipt_epsilon
        ),
    )


def _parse_history(raw: Any) -> HistoryConfig:
    if not isinstance(raw, dict):
        return HistoryConfig()
    defaults = HistoryConfig()
    return HistoryConfig(
        high_profit_margin=_number(raw.get("high_profit_margin"), defaults.high_profit_margin),
        deep_loss_margin=_number(raw.get("deep_loss_margin"), defaults.deep_loss_margin),
        min_episode_months=_integer(raw.get("min_episode_months"), defaults.min_episode_months),
        max_episodes=_integer(raw.get("max_episodes"), defaults.max_episodes),
        follow_up_months=_integer(raw.get("follow_up_months"), defaults.follow_up_months),
    )


def load_pta_config(config_path: Path | str | None = None) -> PtaConfig:
    """加载 PTA 管线配置；若文件缺失或解析失败，回退至内置默认值。"""
    target = Path(config_path) if config_path is not None else Path(DEFAULT_CONFIG_PATH)
    if not target.exists():
        return PtaConfig()

    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except Exception:
        return PtaConfig()

    if not isinstance(data, dict):
        return PtaConfig()

    return PtaConfig(
        schema_version=_integer(data.get("schema_version"), 1),
        title=_str(data.get("title"), _TITLE_DEFAULT),
        artifact_root=_str(data.get("artifact_root"), _ARTIFACT_ROOT_DEFAULT),
        inputs=_parse_inputs(data.get("inputs")),
        regime=_parse_regime(data.get("regime")),
        history=_parse_history(data.get("history")),
    )
