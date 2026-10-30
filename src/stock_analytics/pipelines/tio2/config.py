"""钛白粉全景基本面对账管线配置。

配置来源: ``config/analytics/tio2.yaml``；文件缺失或字段非法时回退默认值。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = "config/analytics/tio2.yaml"

_ARTIFACT_ROOT_DEFAULT = "data/analytics/tio2"
_TITLE_DEFAULT = "钛白粉 (TiO2) 全景基本面对账研报"


@dataclass(frozen=True, slots=True)
class InputsConfig:
    """管线输入源定位。"""

    capacity_projects: str = "config/industry/chemicals/tio2/capacity_projects.yaml"
    trading_gates: str = "config/industry/chemicals/tio2/trading_gates.yaml"
    cost_models: str = "config/industry/chemicals/tio2/cost_models.yaml"
    company_projections: str = "config/industry/chemicals/tio2/company_projections.yaml"
    customs_trade_dataset: str = "customs_trade_gacc"
    customs_trade_fallback: str = "customs_trade"
    chemical_spot_price_dataset: str = "chemical_spot_price"
    chemical_spreads_dataset: str = "chemical_spreads"
    chemical_weekly_survey_dataset: str = "chemical_weekly_survey"
    chemical_monthly_survey_dataset: str = "chemical_monthly_survey"
    company_panel_dataset: str = "mart/tio2_company_panel"
    industry_l2_daily_dataset: str = "mart/industry_l2_daily"


@dataclass(frozen=True, slots=True)
class RegimeThresholds:
    """寡头蓄水池状态机阈值。"""

    destocking_export_yoy: float = 15.0
    passive_export_yoy: float = -5.0
    active_destocking_operating_rate: float = 75.0
    delta_inv_epsilon: float = 0.01


@dataclass(frozen=True, slots=True)
class HistoryConfig:
    """历史周期大拐点检测配置。"""

    high_profit_margin: float = 2000.0
    deep_loss_margin: float = -500.0
    min_episode_months: int = 2
    max_episodes: int = 6
    follow_up_months: int = 3


@dataclass(frozen=True, slots=True)
class Tio2Config:
    """钛白粉全景对账管线配置。"""

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
        chemical_weekly_survey_dataset=_str(
            raw.get("chemical_weekly_survey_dataset"), defaults.chemical_weekly_survey_dataset
        ),
        chemical_monthly_survey_dataset=_str(
            raw.get("chemical_monthly_survey_dataset"), defaults.chemical_monthly_survey_dataset
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
        destocking_export_yoy=_number(
            raw.get("destocking_export_yoy"), defaults.destocking_export_yoy
        ),
        passive_export_yoy=_number(raw.get("passive_export_yoy"), defaults.passive_export_yoy),
        active_destocking_operating_rate=_number(
            raw.get("active_destocking_operating_rate"), defaults.active_destocking_operating_rate
        ),
        delta_inv_epsilon=_number(raw.get("delta_inv_epsilon"), defaults.delta_inv_epsilon),
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


def load_tio2_config(path: Path | str | None = None) -> Tio2Config:
    """加载钛白粉管线配置。"""
    config_path = Path(path) if path is not None else Path(DEFAULT_CONFIG_PATH)
    if not config_path.exists():
        return Tio2Config()
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return Tio2Config()
    if not isinstance(raw, dict):
        return Tio2Config()

    defaults = Tio2Config()
    return Tio2Config(
        schema_version=_integer(raw.get("schema_version"), defaults.schema_version),
        title=_str(raw.get("title"), defaults.title),
        artifact_root=_str(raw.get("artifact_root"), defaults.artifact_root),
        inputs=_parse_inputs(raw.get("inputs")),
        regime=_parse_regime(raw.get("regime")),
        history=_parse_history(raw.get("history")),
    )
