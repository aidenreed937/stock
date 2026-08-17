"""sw_daily 申万行业日行情数据清洗与去重工具。

负责统一 symbol/index_id 字段，消除冗余记录，并保障行业日行情主键唯一。
"""

import argparse
import shutil
from pathlib import Path
from typing import Any

import polars as pl

from stock_core.utils.date import parse_mixed_date
from stock_core.utils.logger import logger

_CURATED_DIR = Path("data/curated/tushare/market=CN/sw_daily")


def _is_artifact(path: Path) -> bool:
    return path.name.endswith((".bak.parquet", ".tmp.parquet", ".migration.tmp.parquet"))


def clean_partition_sw_daily(
    curated_path: Path,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """清洗单个分区的 sw_daily 数据。"""
    df = pl.read_parquet(curated_path)
    before_count = len(df)

    cleaned = df
    # 1. 统一 symbol 字段
    if "index_id" in cleaned.columns and "symbol" in cleaned.columns:
        cleaned = cleaned.with_columns(
            pl.coalesce([pl.col("symbol"), pl.col("index_id")]).alias("symbol")
        )
    elif "index_id" in cleaned.columns and "symbol" not in cleaned.columns:
        cleaned = cleaned.rename({"index_id": "symbol"})

    # 2. 统一 trade_date 为 Date
    date_col = "trade_date" if "trade_date" in cleaned.columns else "date"
    if date_col in cleaned.columns:
        cleaned = cleaned.with_columns(parse_mixed_date(date_col).alias("trade_date"))
        if date_col != "trade_date":
            cleaned = cleaned.drop(date_col)

    # 3. 按 (symbol, trade_date) 去重
    # 优先保留非 repair_run 记录（即 legacy 原始记录，字段更全）
    if "request_id" in cleaned.columns:
        cleaned = (
            cleaned.with_columns(
                (pl.col("request_id") != "repair_run").cast(pl.UInt8).alias("_priority")
            )
            .sort(["symbol", "trade_date", "_priority"])
            .unique(subset=["symbol", "trade_date"], keep="last", maintain_order=True)
            .drop("_priority")
        )
    else:
        cleaned = cleaned.sort(["symbol", "trade_date"]).unique(
            subset=["symbol", "trade_date"], keep="last", maintain_order=True
        )

    after_count = len(cleaned)
    removed_count = before_count - after_count
    has_changes = not cleaned.equals(df)

    if apply and has_changes:
        tmp = curated_path.with_suffix(".tmp.parquet")
        bak = curated_path.with_suffix(".bak.parquet")
        cleaned.write_parquet(tmp)
        if not bak.exists():
            shutil.copy2(curated_path, bak)
        tmp.replace(curated_path)

    return {
        "path": str(curated_path),
        "before": before_count,
        "after": after_count,
        "removed": removed_count,
        "changed": has_changes,
    }


def repair_all_sw_daily(
    curated_root: str | Path = _CURATED_DIR,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """遍历并修复全量 sw_daily 数据。"""
    cur_base = Path(curated_root)
    files = (
        sorted([p for p in cur_base.rglob("*.parquet") if not _is_artifact(p)])
        if cur_base.exists()
        else []
    )

    total_before = 0
    total_after = 0
    total_removed = 0
    changed_files = 0

    for path in files:
        res = clean_partition_sw_daily(path, apply=apply)
        total_before += res["before"]
        total_after += res["after"]
        total_removed += res["removed"]
        if res.get("changed", False) or res["removed"] > 0:
            changed_files += 1

    logger.info(
        f"sw_daily 修复完成 [apply={apply}]: 处理文件 {len(files)} 个, "
        f"影响文件 {changed_files} 个, 总行数: {total_before:,} -> {total_after:,}, "
        f"剔除重复行: {total_removed:,}"
    )

    return {
        "files_processed": len(files),
        "files_changed": changed_files,
        "before": total_before,
        "after": total_after,
        "removed": total_removed,
        "applied": apply,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="sw_daily 申万行业行情清洗与去重工具")
    parser.add_argument(
        "--curated-root",
        default=str(_CURATED_DIR),
        help="Curated sw_daily 根目录",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="执行实际写入与替换备份 (默认只读预览)",
    )
    args = parser.parse_args()

    repair_all_sw_daily(args.curated_root, apply=args.apply)


if __name__ == "__main__":
    main()
