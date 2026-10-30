"""聚氯乙烯 (PVC / V) 全景基本面对账管线配置模块。

负责从 ``config/analytics/pvc.yaml`` 读取并解析管线输入、阈值与参数配置。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = "config/analytics/pvc.yaml"

_ARTIFACT_ROOT_DEFAULT = "data/analytics/pvc"
_TITLE_DEFAULT = "聚氯乙烯 (PVC / V) 全景基本面对账研报"


@dataclass(frozen=True, slots=True)
class InputsConfig:
    """管线输入源定位。"""

    capacity_projects: str = "config/industry/chemicals/pvc/capacity_projects.yaml"
    trading_gates: str = "config/industry/chemicals/pvc/trading_gates.yaml"
    cost_models: str = "config/industry/chemicals/pvc/cost_models.yaml"
    companies: str = "config/industry/chemicals/pvc/companies.yaml"
    customs_trade_dataset: str = "customs_trade_gacc"
    futures_inventory_dataset: str = "futures_inventory"
    futures_daily_dataset: str = "futures_daily"
    chemical_basis_inventory_dataset: str = "mart/chemical_basis_inventory_mart"
    chemical_weekly_survey_dataset: str = "chemical_weekly_survey"
    chemical_spot_price_dataset: str = "chemical_spot_price"
    chemical_spreads_dataset: str = "chemical_spreads"


@dataclass(frozen=True, slots=True)
class RegimeThresholds:
    """PVC 蓄水池状态机与交易门禁阈值。"""

    scissors_spread_min: float = 0.0
    operating_rate_max: float = 75.0
    operating_rate_top_min: float = 86.0
    export_volume_yoy_min: float = 15.0
    destocking_weeks_min: int = 3
    basis_rate_min: float = 0.0


@dataclass(frozen=True, slots=True)
class HistoryConfig:
    """历史大拐点检测配置。"""

    high_profit_margin: float = 600.0
    deep_loss_margin: float = -300.0
    min_episode_months: int = 2
    max_episodes: int = 6
    follow_up_months: int = 3


@dataclass(frozen=True, slots=True)
class PVCConfig:
    """聚氯乙烯全景对账管线配置对象。"""

    schema_version: int = 1
    title: str = _TITLE_DEFAULT
    artifact_root: str = _ARTIFACT_ROOT_DEFAULT
    inputs: InputsConfig = InputsConfig()
    regime: RegimeThresholds = RegimeThresholds()
    history: HistoryConfig = HistoryConfig()


def load_pvc_config(path: Path | str | None = None) -> PVCConfig:
    """加载并解析 PVC 管线配置文件。"""
    config_file = Path(path or DEFAULT_CONFIG_PATH)
    if not config_file.exists():
        return PVCConfig()

    try:
        raw: dict[str, Any] = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    except Exception:
        return PVCConfig()

    inputs_raw = raw.get("inputs") or {}
    regime_raw = raw.get("regime") or {}
    history_raw = raw.get("history") or {}
    _default_inputs = InputsConfig()

    return PVCConfig(
        schema_version=int(raw.get("schema_version", 1)),
        title=str(raw.get("title", _TITLE_DEFAULT)),
        artifact_root=str(raw.get("artifact_root", _ARTIFACT_ROOT_DEFAULT)),
        inputs=InputsConfig(
            capacity_projects=str(
                inputs_raw.get("capacity_projects", _default_inputs.capacity_projects)
            ),
            trading_gates=str(inputs_raw.get("trading_gates", _default_inputs.trading_gates)),
            cost_models=str(inputs_raw.get("cost_models", _default_inputs.cost_models)),
            companies=str(inputs_raw.get("companies", _default_inputs.companies)),
            customs_trade_dataset=str(
                inputs_raw.get("customs_trade_dataset", _default_inputs.customs_trade_dataset)
            ),
            futures_inventory_dataset=str(
                inputs_raw.get(
                    "futures_inventory_dataset", _default_inputs.futures_inventory_dataset
                )
            ),
            futures_daily_dataset=str(
                inputs_raw.get("futures_daily_dataset", _default_inputs.futures_daily_dataset)
            ),
            chemical_basis_inventory_dataset=str(
                inputs_raw.get(
                    "chemical_basis_inventory_dataset",
                    _default_inputs.chemical_basis_inventory_dataset,
                )
            ),
            chemical_weekly_survey_dataset=str(
                inputs_raw.get(
                    "chemical_weekly_survey_dataset", _default_inputs.chemical_weekly_survey_dataset
                )
            ),
            chemical_spot_price_dataset=str(
                inputs_raw.get(
                    "chemical_spot_price_dataset", _default_inputs.chemical_spot_price_dataset
                )
            ),
            chemical_spreads_dataset=str(
                inputs_raw.get("chemical_spreads_dataset", _default_inputs.chemical_spreads_dataset)
            ),
        ),
        regime=RegimeThresholds(
            scissors_spread_min=float(regime_raw.get("scissors_spread_min", 0.0)),
            operating_rate_max=float(regime_raw.get("operating_rate_max", 75.0)),
            operating_rate_top_min=float(regime_raw.get("operating_rate_top_min", 86.0)),
            export_volume_yoy_min=float(regime_raw.get("export_volume_yoy_min", 15.0)),
            destocking_weeks_min=int(regime_raw.get("destocking_weeks_min", 3)),
            basis_rate_min=float(regime_raw.get("basis_rate_min", 0.0)),
        ),
        history=HistoryConfig(
            high_profit_margin=float(history_raw.get("high_profit_margin", 600.0)),
            deep_loss_margin=float(history_raw.get("deep_loss_margin", -300.0)),
            min_episode_months=int(history_raw.get("min_episode_months", 2)),
            max_episodes=int(history_raw.get("max_episodes", 6)),
            follow_up_months=int(history_raw.get("follow_up_months", 3)),
        ),
    )
