"""垂直产业任务契约聚合。"""

from __future__ import annotations

from stock_data.core.industry_consume_task_specs import INDUSTRY_CONSUME_TASK_SPECS
from stock_data.core.industry_energy_task_specs import INDUSTRY_ENERGY_TASK_SPECS
from stock_data.core.industry_macro_task_specs import INDUSTRY_MACRO_TASK_SPECS
from stock_data.core.industry_tech_task_specs import INDUSTRY_TECH_TASK_SPECS

INDUSTRY_TASK_ORDER: tuple[str, ...] = (
    "semiconductor_sales",
    "semiconductor_equipment",
    "semiconductor_equipment_semi",
    "semiconductor_equipment_gm",
    "semiconductor_equipment_gm_multi",
    "semiconductor_equipment_gm_amat",
    "semiconductor_equipment_gm_lrcx",
    "semiconductor_equipment_gm_klac",
    "tel_gm_quarterly",
    "nev_monthly_sales",
    "solar_capacity",
    "non_ferrous_metals",
    "pharma_license_out",
    "cloud_capex_quarterly",
    "construction_machinery",
    "shipping_indices",
    "customs_trade",
    "gacc_trade",
    "semiconductor_lead",
    "chemical_market",
    "chemical_futures_inventory",
    "chemical_futures_daily",
    "chemical_weekly_survey",
    "chemical_monthly_survey",
    "solar_price_chain",
    "solar_cell_nbs",
    "silicon_wafer_monthly",
    "polysilicon_supply_monthly",
    "polysilicon_inventory_monthly",
    "pv_wafer_monthly",
    "polysilicon_balance",
    "solar_supply_demand",
    "agriculture_pork",
    "consumer_electronics",
    "coal_market",
    "chip_lead_time",
    "foundry_capacity_utilization",
    "chemical_capacity_utilization_10y",
    "chemical_spreads",
    "chemical_commodity_index",
    "futures_hold_rank",
    "semiconductor_inventory_days",
    "semiconductor_channel_inventory",
    "semiconductor_memory_price",
    "semiconductor_memory_benchmark",
    "semiconductor_memory_taiwan_lead",
    "tsmc_advanced_packaging_revenue",
    "tsmc_cowos_capacity_estimates",
)


_INDUSTRY_TASK_SPECS_BY_NAME = {
    str(spec["task"]): spec
    for spec in (
        *INDUSTRY_TECH_TASK_SPECS,
        *INDUSTRY_ENERGY_TASK_SPECS,
        *INDUSTRY_CONSUME_TASK_SPECS,
        *INDUSTRY_MACRO_TASK_SPECS,
    )
}
_missing_tasks = [task for task in INDUSTRY_TASK_ORDER if task not in _INDUSTRY_TASK_SPECS_BY_NAME]
_extra_tasks = sorted(set(_INDUSTRY_TASK_SPECS_BY_NAME) - set(INDUSTRY_TASK_ORDER))
if _missing_tasks or _extra_tasks:
    raise ValueError(f"行业任务契约聚合不一致: missing={_missing_tasks}, extra={_extra_tasks}")

INDUSTRY_TASK_SPECS: tuple[dict[str, object], ...] = tuple(
    _INDUSTRY_TASK_SPECS_BY_NAME[task] for task in INDUSTRY_TASK_ORDER
)

__all__ = ["INDUSTRY_TASK_ORDER", "INDUSTRY_TASK_SPECS"]
