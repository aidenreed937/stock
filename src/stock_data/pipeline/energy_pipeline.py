"""全球能源多源数据 2-Tier ETL 统一同步与黄金表落盘管道。"""

from __future__ import annotations

import logging
from pathlib import Path

import polars as pl

from stock_data.fetcher.energy import (
    DEFAULT_CURATED_ENERGY_DIR,
    DEFAULT_RAW_ENERGY_DIR,
    records_to_energy_audit_frame,
    records_to_macro_energy_baseline_frame,
    records_to_oil_gas_balance_frame,
    records_to_power_generation_frame,
    records_to_renewable_capacity_frame,
    save_curated_energy_fact,
)

logger = logging.getLogger(__name__)


def init_energy_curated_store(
    curated_dir: Path | str = DEFAULT_CURATED_ENERGY_DIR,
) -> dict[str, Path]:
    """初始化 Curated 黄金表 Parquet 框架结构 (若不存在则创建空架构表).

    Returns:
        dict[str, Path]: 各黄金表名称到文件路径的映射
    """
    curated_path = Path(curated_dir)
    curated_path.mkdir(parents=True, exist_ok=True)

    tables: dict[str, tuple[str, pl.DataFrame, list[str], list[str]]] = {
        "global_oil_gas_balance": (
            "global_oil_gas_balance.parquet",
            records_to_oil_gas_balance_frame([]),
            ["geo_code", "period", "product", "flow_type", "source"],
            ["trade_date", "geo_code", "product"],
        ),
        "global_power_generation": (
            "global_power_generation.parquet",
            records_to_power_generation_frame([]),
            ["geo_code", "period", "technology", "source"],
            ["trade_date", "geo_code", "technology"],
        ),
        "global_renewable_capacity": (
            "global_renewable_capacity.parquet",
            records_to_renewable_capacity_frame([]),
            ["geo_code", "year", "technology", "source"],
            ["year", "geo_code", "technology"],
        ),
        "global_energy_macro_baseline": (
            "global_energy_macro_baseline.parquet",
            records_to_macro_energy_baseline_frame([]),
            ["geo_code", "year", "energy_type", "flow_type", "source"],
            ["year", "geo_code", "energy_type"],
        ),
        "energy_cross_source_audit": (
            "energy_cross_source_audit.parquet",
            records_to_energy_audit_frame([]),
            ["audit_date", "audit_rule", "geo_code", "period", "product"],
            ["audit_date", "geo_code"],
        ),
    }

    result_paths: dict[str, Path] = {}
    for key, (filename, empty_df, keys, sort_keys) in tables.items():
        file_path = curated_path / filename
        if not file_path.exists():
            save_curated_energy_fact(
                new_df=empty_df,
                target_parquet_path=file_path,
                primary_keys=keys,
                sort_keys=sort_keys,
                export_csv=True,
            )
        result_paths[key] = file_path

    return result_paths


def sync_all_energy_data(
    raw_dir: Path | str = DEFAULT_RAW_ENERGY_DIR,
    curated_dir: Path | str = DEFAULT_CURATED_ENERGY_DIR,
    sources: list[str] | None = None,
) -> dict[str, int]:
    """统一同步并落盘全球能源多源黄金事实表。

    Args:
        raw_dir: RAW 快照存储目录
        curated_dir: Curated 黄金事实存储目录
        sources: 可选指定同步源列表 (如 ["ei", "jodi", "eia", "ember", "irena", "cn_nea"])

    Returns:
        dict[str, int]: 各表最新落盘行数
    """
    raw_path = Path(raw_dir)
    curated_path = Path(curated_dir)
    raw_path.mkdir(parents=True, exist_ok=True)
    curated_path.mkdir(parents=True, exist_ok=True)

    # 确保存储框架初始化
    init_energy_curated_store(curated_dir=curated_path)

    results: dict[str, int] = {}
    target_sources = set(sources) if sources else None

    logger.info("开始执行全球能源多源数据同步, 目标源: %s", target_sources or "全部")
    # 各具体采集器在后续批次逐步装配接入

    return results
