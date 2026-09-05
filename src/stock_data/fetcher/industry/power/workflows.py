"""光伏与硅料产业端点附加执行逻辑。"""

from pathlib import Path
from typing import Any

import polars as pl

from stock_data.fetcher.industry.common import save_curated_fact
from stock_data.fetcher.industry.contracts import IndustryRunContext
from stock_data.fetcher.industry.power.collectors.silicon import SiliconBranchCollector
from stock_data.fetcher.industry.power.schemas import (
    POLYSILICON_BALANCE_MONTHLY_SCHEMA,
    POLYSILICON_INVENTORY_MONTHLY_SCHEMA,
    POLYSILICON_SUPPLY_MONTHLY_SCHEMA,
    PV_WAFER_MONTHLY_SCHEMA,
    SILICON_WAFER_MONTHLY_SCHEMA,
)
from stock_data.fetcher.industry.power.transforms.balance import (
    build_polysilicon_balance_frame,
)
from stock_data.fetcher.industry.power.transforms.polysilicon import (
    build_polysilicon_inventory_from_silicon_frame,
    build_polysilicon_supply_from_silicon_frame,
    build_pv_wafer_from_silicon_frame,
)
from stock_data.fetcher.industry.power.transforms.silicon import (
    build_solar_supply_demand_frame,
    empty_solar_supply_demand,
    records_to_silicon_wafer_monthly_frame,
)

SILICON_BRANCH_ENDPOINTS = {
    "polysilicon_supply_monthly",
    "polysilicon_inventory_monthly",
    "pv_wafer_monthly",
}


def execute_silicon_wafer_monthly(raw_path: Path, curated_path: Path) -> int:
    """兼容入口：采集并落盘硅业分会主表。"""
    collector = SiliconBranchCollector(raw_dir=raw_path)
    records = collector.collect()
    if not records:
        return 0
    df_si = records_to_silicon_wafer_monthly_frame(records)
    return save_curated_fact(
        df_si, curated_path / "silicon_wafer_monthly.parquet", primary_keys=["report_month"]
    )


def execute_silicon_branch_derived(endpoint: str, raw_path: Path, curated_path: Path) -> int:
    """兼容入口：从硅业分会 Curated 主表构建拆分派生事实。"""
    del raw_path
    silicon_path = curated_path / "silicon_wafer_monthly.parquet"
    if not silicon_path.exists():
        return 0
    silicon_df = pl.read_parquet(silicon_path)
    if endpoint == "polysilicon_supply_monthly":
        return save_curated_fact(
            build_polysilicon_supply_from_silicon_frame(silicon_df),
            curated_path / "polysilicon_supply_monthly.parquet",
            primary_keys=["report_month"],
        )
    if endpoint == "polysilicon_inventory_monthly":
        return save_curated_fact(
            build_polysilicon_inventory_from_silicon_frame(silicon_df),
            curated_path / "polysilicon_inventory_monthly.parquet",
            primary_keys=["report_month"],
        )
    return save_curated_fact(
        build_pv_wafer_from_silicon_frame(silicon_df),
        curated_path / "pv_wafer_monthly.parquet",
        primary_keys=["report_month"],
    )


def execute_polysilicon_balance(raw_path: Path, curated_path: Path) -> int:
    """兼容入口：只从已落盘 Curated 派生表构建供需平衡。"""
    del raw_path
    df_bal = build_polysilicon_balance_from_curated(
        curated_path / "polysilicon_supply_monthly.parquet",
        curated_path / "pv_wafer_monthly.parquet",
        curated_path / "polysilicon_inventory_monthly.parquet",
    )
    if df_bal.is_empty():
        return 0
    return save_curated_fact(
        df_bal, curated_path / "polysilicon_balance.parquet", primary_keys=["report_month"]
    )


def _read_curated(path: Path, schema: dict[str, Any]) -> pl.DataFrame:
    if not path.exists():
        return pl.DataFrame(schema=schema)
    return pl.read_parquet(path)


def read_silicon_curated(context: IndustryRunContext) -> pl.DataFrame:
    """读取硅业分会 Curated 主表，供派生 endpoint 使用。"""
    return _read_curated(
        context.curated_dir / "silicon_wafer_monthly.parquet", SILICON_WAFER_MONTHLY_SCHEMA
    )


def build_polysilicon_balance_from_curated(
    supply_path: Path,
    wafer_path: Path,
    inventory_path: Path | None = None,
) -> pl.DataFrame:
    """只消费 Curated 供给、硅片和库存表构建多晶硅平衡表。"""
    supply_df = _read_curated(supply_path, POLYSILICON_SUPPLY_MONTHLY_SCHEMA)
    wafer_df = _read_curated(wafer_path, PV_WAFER_MONTHLY_SCHEMA)
    if supply_df.is_empty() or wafer_df.is_empty():
        return pl.DataFrame(schema=POLYSILICON_BALANCE_MONTHLY_SCHEMA)
    inventory_df = (
        _read_curated(inventory_path, POLYSILICON_INVENTORY_MONTHLY_SCHEMA)
        if inventory_path is not None
        else None
    )
    return build_polysilicon_balance_frame(supply_df, wafer_df, inventory_df)


def collect_polysilicon_balance(context: IndustryRunContext) -> pl.DataFrame:
    """读取 Curated 派生输入并返回平衡表。"""
    return build_polysilicon_balance_from_curated(
        context.curated_dir / "polysilicon_supply_monthly.parquet",
        context.curated_dir / "pv_wafer_monthly.parquet",
        context.curated_dir / "polysilicon_inventory_monthly.parquet",
    )


def collect_solar_supply_demand(context: IndustryRunContext) -> pl.DataFrame:
    """读取 Curated 电池片与装机表并返回供需剪刀差表。"""
    cell_df = _read_curated(context.curated_dir / "solar_cell_production.parquet", {})
    install_df = _read_curated(context.curated_dir / "solar_capacity.parquet", {})
    if cell_df.is_empty() or install_df.is_empty():
        return empty_solar_supply_demand()
    return build_solar_supply_demand_frame(cell_df, install_df)


def _save_silicon_derived_frames(collector: SiliconBranchCollector, curated_path: Path) -> None:
    """兼容内部入口：从 Curated 主表生成拆分派生表。"""
    del collector
    silicon_path = curated_path / "silicon_wafer_monthly.parquet"
    if not silicon_path.exists():
        return
    silicon_df = pl.read_parquet(silicon_path)
    for builder, filename in (
        (
            build_polysilicon_supply_from_silicon_frame,
            "polysilicon_supply_monthly.parquet",
        ),
        (
            build_polysilicon_inventory_from_silicon_frame,
            "polysilicon_inventory_monthly.parquet",
        ),
        (build_pv_wafer_from_silicon_frame, "pv_wafer_monthly.parquet"),
    ):
        frame = builder(silicon_df)
        if not frame.is_empty():
            save_curated_fact(frame, curated_path / filename, primary_keys=["report_month"])
