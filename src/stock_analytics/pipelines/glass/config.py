"""玻璃全景基本面对账管线配置。

配置来源: ``config/analytics/glass.yaml``；文件缺失或字段非法时回退默认值。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = "config/analytics/glass.yaml"
_ARTIFACT_ROOT_DEFAULT = "data/analytics/glass"
_TITLE_DEFAULT = "玻璃 (Glass / FG & PVG) 全景基本面对账研报"


@dataclass(frozen=True, slots=True)
class InputsConfig:
    """管线输入源定位。"""

    capacity_furnaces: str = "config/industry/chemicals/glass/capacity_furnaces.yaml"
    trading_gates: str = "config/industry/chemicals/glass/trading_gates.yaml"
    cost_models: str = "config/industry/chemicals/glass/cost_models.yaml"
    companies: str = "config/industry/chemicals/glass/companies.yaml"
    nbs_plate_glass_csv: str = "data/raw/industry/chemicals/nbs/nbs_plate_glass_monthly.csv"
    nbs_soda_ash_csv: str = "data/raw/industry/chemicals/nbs/nbs_soda_ash_monthly.csv"
    customs_trade_dataset: str = "customs_trade_gacc"
    customs_trade_fallback: str = "customs_trade"
    futures_inventory_dataset: str = "futures_inventory"
    futures_daily_dataset: str = "futures_daily"
    chemical_weekly_survey_dataset: str = "chemical_weekly_survey"
    chemical_spot_price_dataset: str = "chemical_spot_price"
    solar_price_chain_dataset: str = "solar_price_chain"
    solar_supply_demand_dataset: str = "solar_supply_demand"


@dataclass(frozen=True, slots=True)
class RegimeThresholds:
    """中游蓄水池状态机阈值。"""

    basis_speculative_cny: float = -30.0
    destocking_shipment_rate: float = 98.0
    passive_shipment_rate: float = 95.0
    active_destocking_operating_rate: float = 76.0


@dataclass(frozen=True, slots=True)
class GlassConfig:
    """玻璃全景对账管线配置。"""

    schema_version: int = 1
    title: str = _TITLE_DEFAULT
    artifact_root: str = _ARTIFACT_ROOT_DEFAULT
    inputs: InputsConfig = InputsConfig()
    regime: RegimeThresholds = RegimeThresholds()


def load_glass_config(path: Path | str | None = None) -> GlassConfig:
    target = Path(path) if path is not None else Path(DEFAULT_CONFIG_PATH)
    if not target.exists():
        return GlassConfig()
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except Exception:
        return GlassConfig()
    if not isinstance(raw, dict):
        return GlassConfig()

    inputs_raw = raw.get("inputs", {})
    regime_raw = raw.get("regime", {})
    _default_inputs = InputsConfig()

    inputs = InputsConfig(
        capacity_furnaces=str(
            inputs_raw.get("capacity_furnaces", _default_inputs.capacity_furnaces)
        ),
        trading_gates=str(inputs_raw.get("trading_gates", _default_inputs.trading_gates)),
        cost_models=str(inputs_raw.get("cost_models", _default_inputs.cost_models)),
        companies=str(inputs_raw.get("companies", _default_inputs.companies)),
        nbs_plate_glass_csv=str(
            inputs_raw.get("nbs_plate_glass_csv", _default_inputs.nbs_plate_glass_csv)
        ),
        nbs_soda_ash_csv=str(inputs_raw.get("nbs_soda_ash_csv", _default_inputs.nbs_soda_ash_csv)),
        customs_trade_dataset=str(
            inputs_raw.get("customs_trade_dataset", _default_inputs.customs_trade_dataset)
        ),
        customs_trade_fallback=str(
            inputs_raw.get("customs_trade_fallback", _default_inputs.customs_trade_fallback)
        ),
        futures_inventory_dataset=str(
            inputs_raw.get("futures_inventory_dataset", _default_inputs.futures_inventory_dataset)
        ),
        futures_daily_dataset=str(
            inputs_raw.get("futures_daily_dataset", _default_inputs.futures_daily_dataset)
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
        solar_price_chain_dataset=str(
            inputs_raw.get("solar_price_chain_dataset", _default_inputs.solar_price_chain_dataset)
        ),
        solar_supply_demand_dataset=str(
            inputs_raw.get(
                "solar_supply_demand_dataset", _default_inputs.solar_supply_demand_dataset
            )
        ),
    )

    regime = RegimeThresholds(
        basis_speculative_cny=float(regime_raw.get("basis_speculative_cny", -30.0)),
        destocking_shipment_rate=float(regime_raw.get("destocking_shipment_rate", 98.0)),
        passive_shipment_rate=float(regime_raw.get("passive_shipment_rate", 95.0)),
        active_destocking_operating_rate=float(
            regime_raw.get("active_destocking_operating_rate", 76.0)
        ),
    )

    return GlassConfig(
        schema_version=int(raw.get("schema_version", 1)),
        title=str(raw.get("title", _TITLE_DEFAULT)),
        artifact_root=str(raw.get("artifact_root", _ARTIFACT_ROOT_DEFAULT)),
        inputs=inputs,
        regime=regime,
    )


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "GlassConfig",
    "InputsConfig",
    "RegimeThresholds",
    "load_glass_config",
]
