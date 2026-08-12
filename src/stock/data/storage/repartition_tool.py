"""全库 Parquet 数据标准 Hive 动态重分区工具。"""

from datetime import date
from pathlib import Path
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
        parts = f.relative_to(curated_path).parts
        if len(parts) >= 3:
            src = parts[0]
            dataset = parts[2]
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

        # 删除旧的不标准大分区文件
        for fp in file_list:
            try:
                fp.unlink(missing_ok=True)
            except Exception:
                pass

        # 使用 DuckDBMarketStore 重新以 Batch 攒批模式保存，触发动态 trade_date 年月路由
        store = DuckDBMarketStore(data_source=src)
        store.enable_batch_mode()
        try:
            store.save_curated(
                df=merged_df, endpoint=dataset, target_date=date.today(), data_source=src
            )
        finally:
            store.commit()

    logger.info("全库交易日标准 Hive 重分区整理完成！")


if __name__ == "__main__":
    repartition_all_curated("data/curated")
