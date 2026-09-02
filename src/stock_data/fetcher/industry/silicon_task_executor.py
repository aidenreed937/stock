"""硅业分会相关端点执行器。"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import polars as pl

from stock_data.fetcher.industry.common import save_curated_fact
from stock_data.fetcher.industry.power import (
    SiliconBranchCollector,
    build_polysilicon_balance_frame,
    build_solar_supply_demand_frame,
    records_to_polysilicon_inventory_frame,
    records_to_polysilicon_supply_frame,
    records_to_pv_wafer_frame,
    records_to_silicon_wafer_monthly_frame,
)

SILICON_BRANCH_ENDPOINTS = {
    "polysilicon_supply_monthly",
    "polysilicon_inventory_monthly",
    "pv_wafer_monthly",
}


def execute_silicon_wafer_monthly(raw_path: Path, curated_path: Path) -> int:
    """采集硅业分会主表，并联动生成供给、库存、硅片和供需平衡表。"""
    collector = SiliconBranchCollector(raw_dir=raw_path)
    records = collector.collect()
    if not records:
        return 0
    df_si = records_to_silicon_wafer_monthly_frame(records)
    count = save_curated_fact(
        df_si, curated_path / "silicon_wafer_monthly.parquet", primary_keys=["report_month"]
    )
    _save_silicon_derived_frames(collector, curated_path)
    return count


def execute_silicon_branch_derived(endpoint: str, raw_path: Path, curated_path: Path) -> int:
    """执行硅业分会拆分后的派生事实端点。"""
    collector = SiliconBranchCollector(raw_dir=raw_path)
    if endpoint == "polysilicon_supply_monthly":
        return _save_records_to_curated(
            collector.collect_supply(),
            records_to_polysilicon_supply_frame,
            curated_path / "polysilicon_supply_monthly.parquet",
        )
    if endpoint == "polysilicon_inventory_monthly":
        return _save_records_to_curated(
            collector.collect_inventory(),
            records_to_polysilicon_inventory_frame,
            curated_path / "polysilicon_inventory_monthly.parquet",
        )
    return _save_records_to_curated(
        collector.collect_wafer(),
        records_to_pv_wafer_frame,
        curated_path / "pv_wafer_monthly.parquet",
    )


def execute_polysilicon_balance(raw_path: Path, curated_path: Path) -> int:
    """基于多晶硅供给、硅片需求与库存构建供需平衡表。"""
    supply_p = curated_path / "polysilicon_supply_monthly.parquet"
    wafer_p = curated_path / "pv_wafer_monthly.parquet"
    inv_p = curated_path / "polysilicon_inventory_monthly.parquet"
    if not supply_p.exists() or not wafer_p.exists():
        execute_silicon_wafer_monthly(raw_path, curated_path)
    if not supply_p.exists() or not wafer_p.exists():
        return 0
    inv_df = pl.read_parquet(inv_p) if inv_p.exists() else None
    df_bal = build_polysilicon_balance_frame(
        pl.read_parquet(supply_p), pl.read_parquet(wafer_p), inv_df
    )
    if df_bal.is_empty():
        return 0
    return save_curated_fact(
        df_bal, curated_path / "polysilicon_balance.parquet", primary_keys=["report_month"]
    )


def execute_solar_supply_demand(
    raw_path: Path,
    curated_path: Path,
    execute_task: Callable[[str, Path, Path], int],
) -> int:
    """基于 NBS 电池产量和 NEA 装机构建光伏供需剪刀差表。"""
    cell_p = curated_path / "solar_cell_production.parquet"
    install_p = curated_path / "solar_capacity.parquet"
    if not cell_p.exists():
        execute_task("solar_cell_nbs", raw_path, curated_path)
    if not install_p.exists():
        execute_task("solar_capacity", raw_path, curated_path)
    if not cell_p.exists() or not install_p.exists():
        return 0
    df_sd = build_solar_supply_demand_frame(pl.read_parquet(cell_p), pl.read_parquet(install_p))
    if df_sd.is_empty():
        return 0
    return save_curated_fact(
        df_sd, curated_path / "solar_supply_demand.parquet", primary_keys=["report_month"]
    )


def _save_silicon_derived_frames(collector: SiliconBranchCollector, curated_path: Path) -> None:
    supply = collector.collect_supply()
    inventory = collector.collect_inventory()
    wafer = collector.collect_wafer()
    df_supply = _save_optional_records(
        supply,
        records_to_polysilicon_supply_frame,
        curated_path / "polysilicon_supply_monthly.parquet",
    )
    df_inv = _save_optional_records(
        inventory,
        records_to_polysilicon_inventory_frame,
        curated_path / "polysilicon_inventory_monthly.parquet",
    )
    df_wafer = _save_optional_records(
        wafer, records_to_pv_wafer_frame, curated_path / "pv_wafer_monthly.parquet"
    )
    if df_supply is not None and df_wafer is not None:
        df_balance = build_polysilicon_balance_frame(df_supply, df_wafer, df_inv)
        if not df_balance.is_empty():
            save_curated_fact(
                df_balance,
                curated_path / "polysilicon_balance.parquet",
                primary_keys=["report_month"],
            )


def _save_records_to_curated(
    records: list[Any], transform: Callable[[Any], pl.DataFrame], path: Path
) -> int:
    if not records:
        return 0
    return save_curated_fact(transform(records), path, primary_keys=["report_month"])


def _save_optional_records(
    records: list[Any], transform: Callable[[Any], pl.DataFrame], path: Path
) -> pl.DataFrame | None:
    if not records:
        return None
    df = transform(records)
    save_curated_fact(df, path, primary_keys=["report_month"])
    return df
