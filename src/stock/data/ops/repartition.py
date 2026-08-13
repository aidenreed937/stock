"""Curated Parquet 的标准 Hive 动态重分区工具。"""

import argparse
from datetime import date
import json
from pathlib import Path
import shutil
import tempfile

import polars as pl

from stock.data.storage.duckdb_store import DuckDBMarketStore
from stock.utils.logger import logger


def repartition_all_curated(base_dir: str = "data/curated") -> None:
    """扫描 curated 根目录下的所有 parquet 文件，按数据真实交易日 (trade_date) 重新进行 Hive 动态分桶归位。"""
    curated_path = Path(base_dir)
    if not curated_path.exists():
        logger.warning(f"目录不存在: {base_dir}")
        return

    files = list(curated_path.rglob("*.parquet"))
    if not files:
        logger.info("未找到需要重分区的 Parquet 文件。")
        return

    logger.info(f"开始对 [{len(files)}] 个离线 Parquet 文件进行标准交易日重分区归位整理...")

    # 按数据源与数据集分组读取合并
    dataset_groups: dict[tuple[str, str], list[Path]] = {}
    for f in files:
        rel_parts = f.relative_to(curated_path).parts
        if not rel_parts:
            continue
        src = rel_parts[0]
        dataset = ""
        for i, part in enumerate(rel_parts):
            if part.startswith("market=") and i + 1 < len(rel_parts):
                dataset = rel_parts[i + 1]
                break
        if not dataset:
            dataset = rel_parts[1] if len(rel_parts) > 1 else "unknown"
        if dataset and dataset != "unknown":
            dataset_groups.setdefault((src, dataset), []).append(f)

    for (src, dataset), file_list in dataset_groups.items():
        logger.info(f"===> 正在处理 [{src}/{dataset}] (共 {len(file_list)} 个原始分区文件)...")
        dfs = []
        for fp in file_list:
            try:
                df = pl.read_parquet(fp)
                if not df.is_empty():
                    dfs.append(df)
            except Exception as e:
                logger.error(f"读取文件 [{fp}] 失败: {e}")

        if not dfs:
            continue

        merged_df = pl.concat(dfs, how="diagonal_relaxed")

        # 先写入同级临时目录并完成校验，再原子替换旧数据，避免失败造成数据丢失。
        staging = Path(tempfile.mkdtemp(prefix=f".{dataset}.repartition-", dir=curated_path))
        try:
            staged_store = DuckDBMarketStore(storage_dir=staging, data_source=src)
            staged_store.enable_batch_mode()
            staged_store.save_curated(
                df=merged_df, endpoint=dataset, target_date=date.today(), data_source=src
            )
            staged_store.commit()
            staged_files = list(staging.rglob("*.parquet"))
            if not staged_files:
                raise RuntimeError(f"重分区未生成输出文件: {src}/{dataset}")

            backup = Path(tempfile.mkdtemp(prefix=f".{dataset}.backup-", dir=curated_path))
            try:
                for fp in file_list:
                    relative = fp.relative_to(curated_path)
                    target = backup / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(fp), str(target))
                for staged in staged_files:
                    relative = staged.relative_to(staging)
                    target = curated_path / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(staged), str(target))
            except Exception:
                for moved in backup.rglob("*.parquet"):
                    relative = moved.relative_to(backup)
                    target = curated_path / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(moved), str(target))
                raise
            finally:
                shutil.rmtree(backup, ignore_errors=True)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    logger.info("全库交易日标准 Hive 重分区整理完成！")


def _active_dataset_files(base_dir: Path, source: str, dataset: str) -> list[Path]:
    """返回指定数据源和数据集当前生效的 Parquet 文件。"""
    source_dir = base_dir / source
    return sorted(
        path
        for path in source_dir.glob(f"market=*/{dataset}/**/*.parquet")
        if not path.name.endswith((".bak.parquet", ".tmp.parquet"))
    )


def _registered_keys(dataset: str, columns: list[str]) -> list[str]:
    """按注册表获取重分区前后的自然键列。"""
    try:
        from stock.data.fetcher.tushare.registry import TUSHARE_API_REGISTRY

        meta = TUSHARE_API_REGISTRY.get(dataset)
        if meta:
            aliases = {"ts_code": "symbol", "stockCode": "symbol", "date": "trade_date"}
            return [
                aliases.get(key, key)
                for key in meta.primary_keys
                if aliases.get(key, key) in columns or key in columns
            ]
    except Exception:
        logger.exception("读取数据集 [%s] 自然键注册表失败", dataset)
    return []


def _key_count(frame: pl.DataFrame, dataset: str) -> int:
    """计算数据集在标准身份列下的唯一自然键数量。"""
    normalized = DuckDBMarketStore._normalize_identity_columns(frame)
    keys = _registered_keys(dataset, normalized.columns)
    return len(normalized.unique(subset=keys)) if keys else len(normalized)


def repartition_dataset(
    base_dir: str = "data/curated", source: str = "tushare", dataset: str = "income"
) -> dict[str, int]:
    """安全重分区一个数据集，成功后将旧文件保留为 `.bak.parquet`。"""
    curated_root = Path(base_dir)
    source_files = _active_dataset_files(curated_root, source, dataset)
    if not source_files:
        return {"source_files": 0, "source_rows": 0, "output_files": 0, "output_rows": 0}

    frames = [pl.read_parquet(path) for path in source_files]
    source_frame = pl.concat(frames, how="diagonal_relaxed")
    expected_keys = _key_count(source_frame, dataset)
    staging_root = Path(tempfile.mkdtemp(prefix=f".{dataset}.repartition-", dir=curated_root))
    moved_backups: list[tuple[Path, Path]] = []
    moved_outputs: list[tuple[Path, Path]] = []
    try:
        staged_store = DuckDBMarketStore(storage_dir=staging_root, data_source=source)
        staged_store.enable_batch_mode()
        staged_store.save_curated(
            df=source_frame, endpoint=dataset, target_date=date.today(), data_source=source
        )
        staged_store.commit()

        staged_files = _active_dataset_files(staging_root, source, dataset)
        if not staged_files:
            raise RuntimeError(f"重分区未生成输出文件: {source}/{dataset}")
        staged_frame = pl.concat([pl.read_parquet(path) for path in staged_files], how="diagonal_relaxed")
        if _key_count(staged_frame, dataset) != expected_keys:
            raise RuntimeError(f"重分区自然键校验失败: {source}/{dataset}")

        for source_path in source_files:
            backup_path = source_path.with_suffix(".bak.parquet")
            if backup_path.exists():
                raise RuntimeError(f"已存在备份文件，拒绝覆盖: {backup_path}")
            source_path.rename(backup_path)
            moved_backups.append((source_path, backup_path))

        for staged_path in staged_files:
            relative = staged_path.relative_to(staging_root)
            target_path = curated_root / relative
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if target_path.exists():
                raise RuntimeError(f"目标分区仍存在未备份数据: {target_path}")
            staged_path.rename(target_path)
            moved_outputs.append((staged_path, target_path))

        return {
            "source_files": len(source_files),
            "source_rows": len(source_frame),
            "output_files": len(staged_files),
            "output_rows": len(staged_frame),
        }
    except Exception:
        for staged_path, target_path in reversed(moved_outputs):
            if target_path.exists():
                staged_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.rename(staged_path)
        for source_path, backup_path in reversed(moved_backups):
            if backup_path.exists():
                source_path.parent.mkdir(parents=True, exist_ok=True)
                backup_path.rename(source_path)
        raise
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def main() -> None:
    """运行全库或受限数据集重分区。"""
    parser = argparse.ArgumentParser(description="Curated Parquet 重分区工具")
    parser.add_argument("--base-dir", default="data/curated")
    parser.add_argument("--source", help="数据源标识，例如 tushare")
    parser.add_argument("--dataset", help="指定要重分区的数据集，例如 income")
    args = parser.parse_args()
    if bool(args.source) != bool(args.dataset):
        parser.error("--source 与 --dataset 必须同时提供")
    if args.source and args.dataset:
        print(
            json.dumps(
                repartition_dataset(args.base_dir, args.source, args.dataset), ensure_ascii=False
            )
        )
        return
    repartition_all_curated(args.base_dir)


if __name__ == "__main__":
    main()
