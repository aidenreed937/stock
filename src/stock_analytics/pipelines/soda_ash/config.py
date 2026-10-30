"""纯碱全景基本面对账管线配置。

配置来源: ``config/analytics/soda_ash.yaml``；文件缺失或字段非法时回退默认值
（与半导体/光伏管线配置风格一致），保证测试与离线场景可零配置运行。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = "config/analytics/soda_ash.yaml"

_ARTIFACT_ROOT_DEFAULT = "data/analytics/soda_ash"
_TITLE_DEFAULT = "纯碱 (Soda Ash / SA) 全景基本面对账研报"


@dataclass(frozen=True, slots=True)
class InputsConfig:
    """管线输入源定位（容量事件/NBS raw CSV + Curated 数据集名）。"""

    capacity_projects: str = "config/industry/chemicals/soda_ash/capacity_projects.yaml"
    trading_gates: str = "config/industry/chemicals/soda_ash/trading_gates.yaml"
    cost_models: str = "config/industry/chemicals/soda_ash/cost_models.yaml"
    nbs_soda_ash_csv: str = "data/raw/industry/chemicals/nbs/nbs_soda_ash_monthly.csv"
    nbs_plate_glass_csv: str = "data/raw/industry/chemicals/nbs/nbs_plate_glass_monthly.csv"
    customs_trade_dataset: str = "customs_trade_gacc"
    customs_trade_fallback: str = "customs_trade"
    futures_inventory_dataset: str = "futures_inventory"
    futures_hold_rank_dataset: str = "futures_hold_rank"
    futures_daily_dataset: str = "futures_daily"
    chemical_spreads_dataset: str = "chemical_spreads"
    chemical_weekly_survey_dataset: str = "chemical_weekly_survey"
    chemical_spot_price_dataset: str = "chemical_spot_price"
    company_panel_dataset: str = "mart/soda_ash_company_panel"


@dataclass(frozen=True, slots=True)
class RegimeThresholds:
    """中游蓄水池状态机阈值（延续 MVP 版本口径）。"""

    basis_speculative_cny: float = -40.0
    receipt_speculative_delta: float = 200.0
    destocking_shipment_rate: float = 99.0
    passive_shipment_rate: float = 97.0
    balanced_shipment_min: float = 95.0
    balanced_shipment_max: float = 103.0
    active_destocking_operating_rate: float = 75.0
    delta_inv_epsilon: float = 0.01


@dataclass(frozen=True, slots=True)
class HistoryConfig:
    """历史周期大拐点检测配置（报告第四节，数据驱动）。"""

    high_profit_margin: float = 800.0
    deep_loss_margin: float = -200.0
    min_episode_months: int = 2
    max_episodes: int = 6
    follow_up_months: int = 3


@dataclass(frozen=True, slots=True)
class SodaAshConfig:
    """纯碱全景对账管线配置。"""

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
        nbs_soda_ash_csv=_str(raw.get("nbs_soda_ash_csv"), defaults.nbs_soda_ash_csv),
        nbs_plate_glass_csv=_str(raw.get("nbs_plate_glass_csv"), defaults.nbs_plate_glass_csv),
        customs_trade_dataset=_str(
            raw.get("customs_trade_dataset"), defaults.customs_trade_dataset
        ),
        customs_trade_fallback=_str(
            raw.get("customs_trade_fallback"), defaults.customs_trade_fallback
        ),
        futures_inventory_dataset=_str(
            raw.get("futures_inventory_dataset"), defaults.futures_inventory_dataset
        ),
        futures_hold_rank_dataset=_str(
            raw.get("futures_hold_rank_dataset"), defaults.futures_hold_rank_dataset
        ),
        futures_daily_dataset=_str(
            raw.get("futures_daily_dataset"), defaults.futures_daily_dataset
        ),
        chemical_spreads_dataset=_str(
            raw.get("chemical_spreads_dataset"), defaults.chemical_spreads_dataset
        ),
        chemical_weekly_survey_dataset=_str(
            raw.get("chemical_weekly_survey_dataset"),
            defaults.chemical_weekly_survey_dataset,
        ),
        chemical_spot_price_dataset=_str(
            raw.get("chemical_spot_price_dataset"), defaults.chemical_spot_price_dataset
        ),
        company_panel_dataset=_str(
            raw.get("company_panel_dataset"), defaults.company_panel_dataset
        ),
    )


def _parse_regime(raw: Any) -> RegimeThresholds:
    if not isinstance(raw, dict):
        return RegimeThresholds()
    return RegimeThresholds(
        basis_speculative_cny=_number(raw.get("basis_speculative_cny"), -40.0),
        receipt_speculative_delta=_number(raw.get("receipt_speculative_delta"), 200.0),
        destocking_shipment_rate=_number(raw.get("destocking_shipment_rate"), 99.0),
        passive_shipment_rate=_number(raw.get("passive_shipment_rate"), 97.0),
        balanced_shipment_min=_number(raw.get("balanced_shipment_min"), 95.0),
        balanced_shipment_max=_number(raw.get("balanced_shipment_max"), 103.0),
        active_destocking_operating_rate=_number(raw.get("active_destocking_operating_rate"), 75.0),
        delta_inv_epsilon=_number(raw.get("delta_inv_epsilon"), 0.01),
    )


def _parse_history(raw: Any) -> HistoryConfig:
    if not isinstance(raw, dict):
        return HistoryConfig()
    return HistoryConfig(
        high_profit_margin=_number(raw.get("high_profit_margin"), 800.0),
        deep_loss_margin=_number(raw.get("deep_loss_margin"), -200.0),
        min_episode_months=_integer(raw.get("min_episode_months"), 2),
        max_episodes=_integer(raw.get("max_episodes"), 6),
        follow_up_months=_integer(raw.get("follow_up_months"), 3),
    )


def load_soda_ash_config(config_path: Path | str = DEFAULT_CONFIG_PATH) -> SodaAshConfig:
    """从 YAML 读取纯碱管线配置；文件缺失或不可解析时使用全默认值。"""
    path = Path(config_path)
    if not path.exists():
        return SodaAshConfig()

    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return SodaAshConfig()
    if not isinstance(payload, dict):
        return SodaAshConfig()

    return SodaAshConfig(
        schema_version=_integer(payload.get("schema_version"), 1),
        title=_str(payload.get("title"), _TITLE_DEFAULT),
        artifact_root=_str(payload.get("artifact_root"), _ARTIFACT_ROOT_DEFAULT),
        inputs=_parse_inputs(payload.get("inputs")),
        regime=_parse_regime(payload.get("regime")),
        history=_parse_history(payload.get("history")),
    )


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "HistoryConfig",
    "InputsConfig",
    "RegimeThresholds",
    "SodaAshConfig",
    "load_soda_ash_config",
]
