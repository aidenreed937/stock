"""光伏/多晶硅产业 RAW → Curated 离线重放计划（不触发网络采集）。

Curated/RAW 路径取自 :mod:`stock_data.fetcher.industry.power.registry`。

其中 5 张派生表（多晶硅供给/库存、硅片、平衡表、供需剪刀差）**由 Curated 主表重建**，
重放时必须晚于其上游主表，故用 :data:`POWER_REPLAY_ORDER` 声明依赖顺序
（重放脚本会把非 power 指标先按名排序，再按本序追加 power 指标）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from stock_data.fetcher.industry.replay_support import identity_frame, replay_entry

__all__ = ["POWER_REPLAY_ORDER", "build_power_replay_plan"]

# 派生表依赖 Curated 主表，重放顺序不可随意调整。
POWER_REPLAY_ORDER = (
    "solar_capacity",
    "solar_cell_nbs",
    "solar_price_chain",
    "silicon_wafer_monthly",
    "polysilicon_supply_monthly",
    "polysilicon_inventory_monthly",
    "pv_wafer_monthly",
    "polysilicon_balance",
    "solar_supply_demand",
)


def _load_solar_capacity(raw_root: Path) -> list[Any]:
    """从光伏 NEA RAW CSV 读取装机记录。"""
    from stock_data.fetcher.industry.power.collectors.nea import SolarCollector
    from stock_data.fetcher.industry.power.paths import PowerRawPaths

    paths = PowerRawPaths(raw_root)
    return SolarCollector(raw_dir=raw_root).load_from_raw_csv(paths.solar_capacity_csv)


def _load_solar_cell(raw_root: Path) -> list[Any]:
    """从光伏 NBS RAW CSV 读取电池片产量记录。"""
    from stock_data.fetcher.industry.power.collectors.nbs import NbsSolarCellCollector

    return NbsSolarCellCollector(raw_dir=raw_root).collect()


def _load_solar_price(raw_root: Path) -> list[Any]:
    """从 InfoLink RAW CSV 读取价格链记录。"""
    from stock_data.fetcher.industry.power.collectors.infolink import PvPriceChainCollector
    from stock_data.fetcher.industry.power.paths import PowerRawPaths

    paths = PowerRawPaths(raw_root)
    return PvPriceChainCollector(raw_dir=raw_root).load_from_raw_csv(paths.pv_price_chain_csv)


def _load_silicon(raw_root: Path) -> list[Any]:
    """从硅业分会 RAW CSV 读取硅料/硅片主表记录。"""
    from stock_data.fetcher.industry.power.collectors.silicon import SiliconBranchCollector

    return SiliconBranchCollector(raw_dir=raw_root).collect()


def _load_supply_from_curated(raw_root: Path, curated_root: Path) -> pl.DataFrame:
    """只从硅料/硅片 Curated 主表重建多晶硅供给派生表。"""
    del raw_root
    from stock_data.fetcher.industry.power.transforms import (
        build_polysilicon_supply_from_silicon_frame,
    )

    path = curated_root / "silicon_wafer_monthly.parquet"
    if not path.exists():
        return pl.DataFrame()
    return build_polysilicon_supply_from_silicon_frame(pl.read_parquet(path))


def _load_inventory_from_curated(raw_root: Path, curated_root: Path) -> pl.DataFrame:
    """只从硅料/硅片 Curated 主表重建库存派生表。"""
    del raw_root
    from stock_data.fetcher.industry.power.transforms import (
        build_polysilicon_inventory_from_silicon_frame,
    )

    path = curated_root / "silicon_wafer_monthly.parquet"
    if not path.exists():
        return pl.DataFrame()
    return build_polysilicon_inventory_from_silicon_frame(pl.read_parquet(path))


def _load_wafer_from_curated(raw_root: Path, curated_root: Path) -> pl.DataFrame:
    """只从硅料/硅片 Curated 主表重建硅片派生表。"""
    del raw_root
    from stock_data.fetcher.industry.power.transforms import build_pv_wafer_from_silicon_frame

    path = curated_root / "silicon_wafer_monthly.parquet"
    if not path.exists():
        return pl.DataFrame()
    return build_pv_wafer_from_silicon_frame(pl.read_parquet(path))


def _load_balance_from_curated(raw_root: Path, curated_root: Path) -> pl.DataFrame:
    """只从多晶硅供给、硅片和库存 Curated 表重建平衡表。"""
    del raw_root
    from stock_data.fetcher.industry.power.workflows import (
        build_polysilicon_balance_from_curated,
    )

    return build_polysilicon_balance_from_curated(
        curated_root / "polysilicon_supply_monthly.parquet",
        curated_root / "pv_wafer_monthly.parquet",
        curated_root / "polysilicon_inventory_monthly.parquet",
        (
            curated_root / "customs_trade.parquet",
            curated_root / "customs_trade_gacc.parquet",
        ),
    )


def _load_supply_demand_from_curated(raw_root: Path, curated_root: Path) -> pl.DataFrame:
    """只从电池片产量和光伏装机 Curated 表重建供需剪刀差。"""
    del raw_root
    from stock_data.fetcher.industry.power.transforms import (
        build_solar_supply_demand_frame,
    )

    cell_path = curated_root / "solar_cell_production.parquet"
    capacity_path = curated_root / "solar_capacity.parquet"
    if not cell_path.exists() or not capacity_path.exists():
        return pl.DataFrame()
    return build_solar_supply_demand_frame(
        pl.read_parquet(cell_path),
        pl.read_parquet(capacity_path),
    )


def build_power_replay_plan() -> dict[str, dict[str, Any]]:
    """构建光伏/多晶硅产业的离线重放计划（metric -> 执行计划）。"""
    from stock_data.fetcher.industry.power.registry import ENDPOINT_SPECS
    from stock_data.fetcher.industry.power.transforms import (
        records_to_raw_silicon_wafer_monthly_frame,
        records_to_raw_solar_cell_nbs_frame,
        records_to_raw_solar_frame,
        records_to_raw_solar_price_chain_frame,
        records_to_silicon_wafer_monthly_frame,
        records_to_solar_cell_nbs_frame,
        records_to_solar_frame,
        records_to_solar_price_chain_frame,
    )

    return {
        "solar_capacity": replay_entry(
            "solar_capacity",
            loader=_load_solar_capacity,
            to_frame=records_to_solar_frame,
            raw_to_frame=records_to_raw_solar_frame,
            primary_keys=["report_month"],
            specs=ENDPOINT_SPECS,
        ),
        "solar_cell_nbs": replay_entry(
            "solar_cell_nbs",
            loader=_load_solar_cell,
            to_frame=records_to_solar_cell_nbs_frame,
            raw_to_frame=records_to_raw_solar_cell_nbs_frame,
            primary_keys=["report_month"],
            specs=ENDPOINT_SPECS,
        ),
        "silicon_wafer_monthly": replay_entry(
            "silicon_wafer_monthly",
            loader=_load_silicon,
            to_frame=records_to_silicon_wafer_monthly_frame,
            raw_to_frame=records_to_raw_silicon_wafer_monthly_frame,
            primary_keys=["report_month"],
            specs=ENDPOINT_SPECS,
        ),
        "solar_price_chain": replay_entry(
            "solar_price_chain",
            loader=_load_solar_price,
            to_frame=records_to_solar_price_chain_frame,
            raw_to_frame=records_to_raw_solar_price_chain_frame,
            primary_keys=["report_date"],
            specs=ENDPOINT_SPECS,
        ),
        "polysilicon_supply_monthly": replay_entry(
            "polysilicon_supply_monthly",
            loader=_load_supply_from_curated,
            to_frame=identity_frame,
            primary_keys=["report_month"],
            specs=ENDPOINT_SPECS,
            loader_uses_curated=True,
        ),
        "polysilicon_inventory_monthly": replay_entry(
            "polysilicon_inventory_monthly",
            loader=_load_inventory_from_curated,
            to_frame=identity_frame,
            primary_keys=["report_month"],
            specs=ENDPOINT_SPECS,
            loader_uses_curated=True,
        ),
        "pv_wafer_monthly": replay_entry(
            "pv_wafer_monthly",
            loader=_load_wafer_from_curated,
            to_frame=identity_frame,
            primary_keys=["report_month"],
            specs=ENDPOINT_SPECS,
            loader_uses_curated=True,
        ),
        "polysilicon_balance": replay_entry(
            "polysilicon_balance",
            loader=_load_balance_from_curated,
            to_frame=identity_frame,
            primary_keys=["report_month"],
            specs=ENDPOINT_SPECS,
            loader_uses_curated=True,
        ),
        "solar_supply_demand": replay_entry(
            "solar_supply_demand",
            loader=_load_supply_demand_from_curated,
            to_frame=identity_frame,
            primary_keys=["report_month"],
            specs=ENDPOINT_SPECS,
            loader_uses_curated=True,
        ),
    }
