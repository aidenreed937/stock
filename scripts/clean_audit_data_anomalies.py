#!/usr/bin/env python3
"""清洗 Parquet 脏数据与冗余记录工具。"""

import logging
from pathlib import Path

import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def clean_index_daily_bar(base_dir: Path) -> None:
    """清洗 tushare index_daily_bar 中 repair_run 且被误认为 US_EXCHANGE 的行。"""
    target_dir = base_dir / "curated" / "tushare" / "market=CN" / "index_daily_bar"
    if not target_dir.exists():
        logger.warning(f"目录 {target_dir} 不存在，跳过。")
        return

    total_removed = 0
    for p in target_dir.rglob("*.parquet"):
        if p.name.endswith(".bak.parquet") or p.name.endswith(".tmp.parquet"):
            continue

        df = pl.read_parquet(p)
        if "request_id" not in df.columns or "exchange" not in df.columns:
            continue

        # 找出那些因为 repair_run 导致的非法记录
        bad_mask = (pl.col("request_id") == "repair_run") & (pl.col("exchange") == "US_EXCHANGE")
        clean_df = df.filter(~bad_mask)

        removed_count = len(df) - len(clean_df)
        if removed_count > 0:
            logger.info(f"清理 {p.relative_to(base_dir)}: 移除 {removed_count} 行脏数据。")
            clean_df.write_parquet(p)
            total_removed += removed_count

    logger.info(f"[index_daily_bar] 总计移除: {total_removed} 行")


def clean_yfinance_index_daily_bar(base_dir: Path) -> None:
    """清理 yfinance market=US index_daily_bar 中的非美股冗余行。"""
    target_file = (
        base_dir / "curated" / "yfinance" / "market=US" / "index_daily_bar" / "data.parquet"
    )
    if not target_file.exists():
        logger.warning(f"文件 {target_file} 不存在，跳过。")
        return

    df = pl.read_parquet(target_file)
    original_len = len(df)

    # 仅保留真正的美股指数
    valid_symbols = {"^DJI", "^GSPC", "^IXIC"}
    clean_df = df.filter(pl.col("symbol").is_in(valid_symbols))

    # 去除文件内可能存在的自身重复（同一 symbol + trade_date 重复行）
    clean_df = clean_df.unique(subset=["symbol", "trade_date"], keep="last")

    removed_count = original_len - len(clean_df)
    if removed_count > 0:
        logger.info(f"清理 {target_file.relative_to(base_dir)}: 移除 {removed_count} 行冗余数据。")
        clean_df.write_parquet(target_file)

    logger.info(
        f"[yfinance index_daily_bar] 原始行数: {original_len}, "
        f"清洗后行数: {len(clean_df)}, 移除冗余: {removed_count} 行"
    )


def clean_macro_indicators(base_dir: Path) -> None:
    """清理 yfinance 宏观指标在 market=US 下的冗余副本，保留 GLOBAL。"""
    us_dir = base_dir / "curated" / "yfinance" / "market=US" / "macro_indicators"

    if us_dir.exists():
        for p in us_dir.rglob("*"):
            if p.is_file():
                logger.info(f"删除冗余文件: {p.relative_to(base_dir)}")
                p.unlink()
        try:
            us_dir.rmdir()
            logger.info(f"删除空目录: {us_dir.relative_to(base_dir)}")
        except Exception as e:
            logger.warning(f"无法删除目录 {us_dir}: {e}")
    else:
        logger.info("[macro_indicators] 没有发现 US 下的冗余副本。")


def main() -> None:
    base_dir = Path("data")
    if not base_dir.exists():
        logger.error("在当前工作目录下未找到 data 目录！")
        return

    logger.info("=== 开始执行数据清洗 ===")
    clean_index_daily_bar(base_dir)
    clean_yfinance_index_daily_bar(base_dir)
    clean_macro_indicators(base_dir)
    logger.info("=== 数据清洗完成 ===")


if __name__ == "__main__":
    main()
