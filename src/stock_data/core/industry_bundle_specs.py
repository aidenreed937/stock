"""垂直产业任务包定义。"""

from __future__ import annotations

from stock_data.core.industry_task_specs import INDUSTRY_TASK_SPECS

SEMICONDUCTOR_TASKS: tuple[str, ...] = (
    "semiconductor_sales",
    "semiconductor_lead",
    "semiconductor_inventory_days",
    "semiconductor_channel_inventory",
    "semiconductor_equipment",
    "semiconductor_equipment_semi",
    "foundry_capacity_utilization",
    "chip_lead_time",
    "tsmc_advanced_packaging_revenue",
    "tsmc_cowos_capacity_estimates",
    "semiconductor_memory_price",
    "semiconductor_memory_benchmark",
    "semiconductor_memory_taiwan_lead",
)

SEMICONDUCTOR_EQUIPMENT_GM_TASKS: tuple[str, ...] = (
    "semiconductor_equipment_gm_amat",
    "semiconductor_equipment_gm_lrcx",
    "semiconductor_equipment_gm_klac",
    "tel_gm_quarterly",
)

CHEMICAL_TASKS: tuple[str, ...] = (
    "chemical_market",
    "chemical_futures_inventory",
    "chemical_futures_daily",
    "chemical_weekly_survey",
    "chemical_monthly_survey",
    "futures_hold_rank",
    "chemical_commodity_index",
)

INDUSTRY_TASK_BUNDLE_TASKS: dict[str, tuple[str, ...]] = {
    # 半导体黄金表 13 个在线/存证端点独立编排；设备商 GM 三张
    # curated-only 表不纳入增量同步包，仍按显式离线解析脚本维护。
    "semiconductor_bundle": SEMICONDUCTOR_TASKS,
    "semiconductor_equipment_gm_bundle": SEMICONDUCTOR_EQUIPMENT_GM_TASKS,
    "industry_tech_bundle": (
        "semiconductor_sales",
        "semiconductor_lead",
        "semiconductor_equipment",
        "semiconductor_equipment_semi",
        "chip_lead_time",
        "foundry_capacity_utilization",
        "semiconductor_inventory_days",
        "semiconductor_channel_inventory",
        "semiconductor_memory_price",
        "semiconductor_memory_benchmark",
        "semiconductor_memory_taiwan_lead",
        "cloud_capex_quarterly",
        "consumer_electronics",
    ),
    "chemical_industry_bundle": CHEMICAL_TASKS,
    "industry_energy_bundle": (
        "solar_capacity",
        "solar_price_chain",
        "solar_cell_nbs",
        "silicon_wafer_monthly",
        "polysilicon_supply_monthly",
        "polysilicon_inventory_monthly",
        "pv_wafer_monthly",
        "polysilicon_balance",
        "solar_supply_demand",
        "non_ferrous_metals",
        "coal_market",
    ),
    "industry_consume_bundle": (
        "agriculture_pork",
        "pharma_license_out",
    ),
    "industry_macro_bundle": (
        "shipping_indices",
        "construction_machinery",
        "nev_monthly_sales",
    ),
    "industry_gacc_bundle": ("gacc_trade",),
    "industry_monthly_bundle": (
        "semiconductor_sales",
        "semiconductor_lead",
        "semiconductor_equipment",
        "semiconductor_memory_price",
        "semiconductor_memory_benchmark",
        "semiconductor_memory_taiwan_lead",
        "foundry_capacity_utilization",
        "nev_monthly_sales",
        "solar_capacity",
        "solar_cell_nbs",
        "silicon_wafer_monthly",
        "polysilicon_supply_monthly",
        "polysilicon_inventory_monthly",
        "pv_wafer_monthly",
        "polysilicon_balance",
        "solar_supply_demand",
        "non_ferrous_metals",
        "pharma_license_out",
        "cloud_capex_quarterly",
        "construction_machinery",
        "shipping_indices",
    ),
    "industry_all_bundle": (
        "semiconductor_sales",
        "nev_monthly_sales",
        "solar_capacity",
        "solar_cell_nbs",
        "silicon_wafer_monthly",
        "polysilicon_supply_monthly",
        "polysilicon_inventory_monthly",
        "pv_wafer_monthly",
        "polysilicon_balance",
        "solar_supply_demand",
        "non_ferrous_metals",
        "pharma_license_out",
        "cloud_capex_quarterly",
        "construction_machinery",
        "shipping_indices",
        "semiconductor_lead",
        "semiconductor_equipment",
        "semiconductor_equipment_semi",
        "chip_lead_time",
        "foundry_capacity_utilization",
        "semiconductor_inventory_days",
        "semiconductor_channel_inventory",
        "semiconductor_memory_price",
        "semiconductor_memory_benchmark",
        "semiconductor_memory_taiwan_lead",
        "chemical_market",
        "chemical_weekly_survey",
        "chemical_futures_inventory",
        "chemical_futures_daily",
        "futures_hold_rank",
        "chemical_commodity_index",
        "solar_price_chain",
        "agriculture_pork",
        "consumer_electronics",
        "coal_market",
        "semiconductor_equipment_gm_amat",
        "semiconductor_equipment_gm_lrcx",
        "semiconductor_equipment_gm_klac",
        "tel_gm_quarterly",
    ),
}


def build_industry_task_bundles() -> dict[str, tuple[str, ...]]:
    """生成行业任务包，并校验任务包成员均来自行业任务注册表。"""
    registered_tasks = {str(item["task"]) for item in INDUSTRY_TASK_SPECS}
    missing = {
        task
        for tasks in INDUSTRY_TASK_BUNDLE_TASKS.values()
        for task in tasks
        if task not in registered_tasks
    }
    if missing:
        raise ValueError(f"行业任务包引用了未注册任务: {sorted(missing)}")
    return dict(INDUSTRY_TASK_BUNDLE_TASKS)


__all__ = ["CHEMICAL_TASKS", "INDUSTRY_TASK_BUNDLE_TASKS", "build_industry_task_bundles"]
