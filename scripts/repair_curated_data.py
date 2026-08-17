"""全库 RAW 离线数据重放、清洗与 Curated 重新落盘修复工具。"""

import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from stock_core.contracts import DatasetKey
from stock_core.utils.logger import logger
from stock_data.core.task_registry import resolve_task
from stock_data.pipeline.cleaner.bar_cleaner import BarDataCleaner
from stock_data.pipeline.cleaner.base import BaseDataCleaner
from stock_data.pipeline.cleaner.generic_cleaner import GenericCleaner
from stock_data.pipeline.normalizer.bar_normalizer import (
    BarDataNormalizer,
    infer_market_exchange_currency,
)
from stock_data.pipeline.normalizer.base import BaseDataNormalizer
from stock_data.pipeline.normalizer.generic_normalizer import GenericNormalizer
from stock_data.pipeline.normalizer.unit_normalizer import UnitNormalizer
from stock_data.storage.compat import StorageCompat
from stock_data.storage.duckdb_store import DuckDBMarketStore


@dataclass(slots=True)
class RepairContext:
    """修复上下文参数集。"""

    provider: str
    dataset: str
    market: str
    api_name: str
    cleaner: BaseDataCleaner
    normalizer: BaseDataNormalizer
    unit_norm: UnitNormalizer
    store: DuckDBMarketStore


def _is_artifact_path(path: Path) -> bool:
    return path.name.endswith((".bak.parquet", ".tmp.parquet", ".migration.tmp.parquet"))


def _parse_source_dataset_market(file_path: Path, raw_root: Path) -> tuple[str, str, str]:
    """从 RAW 路径解析 provider, dataset, market。"""
    rel = file_path.relative_to(raw_root)
    parts = rel.parts
    provider = parts[0]
    market = "MULTI"
    if len(parts) >= 3 and parts[1].startswith("market="):
        market = parts[1].split("=", 1)[1]
        dataset = parts[2]
    elif len(parts) >= 2:
        dataset = parts[1]
    else:
        dataset = file_path.stem
    return provider, dataset, market


def _resolve_endpoint_meta(prov: str, ds: str) -> tuple[str, str, list[str] | None]:
    """解析数据端点元数据与主键。"""
    meta_keys = None
    try:
        task = resolve_task(prov, ds)
        api_name = task.api_name
        profile = getattr(task, "quality_profile", "generic")
        m: Any = None
        if prov == "tushare":
            from stock_data.fetcher.tushare.registry import TUSHARE_API_REGISTRY

            m = TUSHARE_API_REGISTRY.get(api_name)
        elif prov == "lixinger":
            from stock_data.fetcher.lixinger.registry import LIXINGER_API_REGISTRY

            m = LIXINGER_API_REGISTRY.get(api_name)
        if m and getattr(m, "primary_keys", None):
            meta_keys = list(m.primary_keys)
    except Exception:
        api_name = ds
        profile = "bar" if ds in {"stock_daily_bar", "index_daily_bar", "fund_daily"} else "generic"

    return api_name, profile, meta_keys


def _process_single_raw_file(file_path: Path, ctx: RepairContext) -> int:
    """清洗并转换单个 RAW 文件落盘。"""
    raw_df = pl.read_parquet(file_path)
    if raw_df.is_empty():
        return 0

    raw_df = StorageCompat.normalize_identity_columns(raw_df)
    unit_df = ctx.unit_norm.normalize_units(raw_df)
    cleaned_df = ctx.cleaner.clean(unit_df)
    if cleaned_df.is_empty():
        return 0

    norm_df = ctx.normalizer.normalize(cleaned_df)
    if norm_df.is_empty():
        return 0

    prov = ctx.provider
    if "ts_code" in norm_df.columns:
        m_exp, ex_exp, cur_exp = infer_market_exchange_currency(pl.col("ts_code"), data_source=prov)
    elif "symbol" in norm_df.columns:
        m_exp, ex_exp, cur_exp = infer_market_exchange_currency(pl.col("symbol"), data_source=prov)
    else:
        mkt = ctx.market
        fallback_m = mkt if mkt != "MULTI" else ("CN" if prov in {"tushare", "lixinger"} else "US")
        m_exp = pl.lit(fallback_m)
        ex_exp = pl.lit("SOURCE")
        cur_exp = pl.lit("CNY" if prov in {"tushare", "lixinger"} else "USD")

    now_utc = datetime.now(UTC)
    meta_cols = [
        pl.lit(prov).alias("data_source"),
        pl.lit(ctx.api_name).alias("source_endpoint"),
        pl.lit("repair_run").alias("request_id"),
        pl.lit(now_utc).cast(pl.Datetime("us", "UTC")).alias("updated_at"),
        m_exp.alias("market"),
        ex_exp.alias("exchange"),
        cur_exp.alias("currency"),
        pl.lit("raw").alias("adjustment"),
        pl.lit("v2").alias("schema_version"),
    ]
    final_df = norm_df.with_columns(meta_cols)
    key = DatasetKey(
        provider=prov,
        dataset=ctx.dataset,
        endpoint=ctx.api_name,
        start_date=date(2000, 1, 1),
        end_date=date(2030, 1, 1),
    )
    ctx.store.save_dataset(key, final_df)
    return len(final_df)


def repair_all_raw_to_curated(
    raw_dir: str = "data/raw",
    curated_dir: str = "data/curated",
    target_endpoints: list[str] | None = None,
) -> dict[str, int]:
    """遍历 RAW 文件，重新执行 Clean/Normalize/Dedup/Write 全流程。"""
    raw_path = Path(raw_dir)
    curated_path = Path(curated_dir)
    if not raw_path.exists():
        logger.error(f"RAW 目录不存在: {raw_dir}")
        return {}

    raw_files = [f for f in raw_path.rglob("*.parquet") if not _is_artifact_path(f)]
    logger.info(f"扫描到 RAW 目录共 {len(raw_files)} 个数据文件，准备开始重放修复...")

    dataset_groups: dict[tuple[str, str, str], list[Path]] = {}
    for f in sorted(raw_files):
        prov, ds, mkt = _parse_source_dataset_market(f, raw_path)
        if target_endpoints and ds not in target_endpoints:
            continue
        dataset_groups.setdefault((prov, ds, mkt), []).append(f)

    results: dict[str, int] = {}
    for (prov, ds, mkt), files in dataset_groups.items():
        logger.info(f"===> 开始重放清洗落盘: [{prov}/{mkt}/{ds}] (共 {len(files)} 个原始文件)")
        api_name, profile, meta_keys = _resolve_endpoint_meta(prov, ds)

        cleaner = BarDataCleaner() if profile == "bar" else GenericCleaner(primary_keys=meta_keys)
        normalizer = BarDataNormalizer() if profile == "bar" else GenericNormalizer()
        unit_norm = UnitNormalizer(prov, api_name)

        store = DuckDBMarketStore(storage_dir=curated_path, data_source=prov)
        store.bind_data_source(prov)
        store.enable_batch_mode()

        ctx = RepairContext(
            provider=prov,
            dataset=ds,
            market=mkt,
            api_name=api_name,
            cleaner=cleaner,
            normalizer=normalizer,
            unit_norm=unit_norm,
            store=store,
        )

        total_rows = 0
        for f in files:
            try:
                total_rows += _process_single_raw_file(f, ctx)
            except Exception as e:
                logger.error(f"处理文件 [{f}] 发生异常: {e}")

        store.commit()
        logger.info(f"[{prov}/{ds}] 重放修复完成，共精炼落盘 {total_rows} 条记录。")
        results[f"{prov}/{ds}"] = total_rows

    return results


def main() -> None:
    endpoints = sys.argv[1:] if len(sys.argv) > 1 else None
    results = repair_all_raw_to_curated(target_endpoints=endpoints)
    print(f"\n全部修复完成，涉及数据集数: {len(results)}")
    for ds_name, count in sorted(results.items()):
        print(f"  - {ds_name:<35}: {count:,} 行")


if __name__ == "__main__":
    main()
