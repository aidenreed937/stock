"""估值指标数据 (daily_basic) 领域对账审计模块。"""

from datetime import date
from typing import Any
import polars as pl
from stock.utils.logger import logger


def run_daily_basic_audit(
    target_date: date, data_source: str = "tushare", quiet: bool = False
) -> dict[str, Any]:
    """对比审计 daily_basic (每日估值指标) 与 stock_daily_bar (K线行情) 的 1-to-1 对齐匹配率。"""
    logger.info(f"开始 daily_basic 估值对账审计，目标日期: {target_date} [数据源: {data_source}]")

    # 1. 读取行情 K 线记录
    daily_pattern = f"data/curated/{data_source}/market=CN/stock_daily_bar/year={target_date.year:04d}/month={target_date.month:02d}/*.parquet"
    try:
        daily_df = pl.read_parquet(daily_pattern)
        if "trade_date" in daily_df.columns and daily_df["trade_date"].dtype == pl.String:
            daily_df = daily_df.with_columns(
                pl.col("trade_date").str.to_date("%Y-%m-%d").alias("trade_date")
            )
        bar_df = daily_df.filter(pl.col("trade_date") == target_date)
        bar_symbols = set(bar_df["symbol"].unique().to_list())
    except Exception:
        bar_symbols = set()

    # 2. 读取每日指标 daily_basic 记录
    basic_pattern = f"data/curated/{data_source}/market=CN/daily_basic/year={target_date.year:04d}/month={target_date.month:02d}/*.parquet"
    try:
        db_df = pl.read_parquet(basic_pattern)
        if "trade_date" in db_df.columns and db_df["trade_date"].dtype == pl.String:
            db_df = db_df.with_columns(
                pl.col("trade_date").str.to_date("%Y-%m-%d").alias("trade_date")
            )
        target_db = db_df.filter(pl.col("trade_date") == target_date)
        basic_symbols = set(target_db["symbol"].unique().to_list())
    except Exception:
        basic_symbols = set()

    match_count = len(bar_symbols.intersection(basic_symbols))
    missing_in_basic = bar_symbols - basic_symbols
    integrity_rate = (match_count / len(bar_symbols) * 100.0) if bar_symbols else 0.0

    if not quiet:
        print("\n" + "=" * 65)
        print(f"      【daily_basic 每日指标 vs K线行情对账报告 ({target_date})】")
        print("=" * 65)
        print(f"K 线行情在盘交易个股数 : {len(bar_symbols):>6} 只")
        print(f"估值指标 (daily_basic) 股数: {len(basic_symbols):>6} 只")
        print(f"完全对齐匹配个股数     : {match_count:>6} 只")
        print(f"对齐匹配率             : {integrity_rate:>6.2f} %")
        if missing_in_basic:
            print(
                f"有 K线但缺失估值指标股数: {len(missing_in_basic):>6} 只 (如: {sorted(list(missing_in_basic))[:5]})"
            )
        print("=" * 65 + "\n")

    return {
        "target_date": target_date,
        "bar_count": len(bar_symbols),
        "basic_count": len(basic_symbols),
        "match_count": match_count,
        "integrity_rate": integrity_rate,
        "missing_symbols": sorted(list(missing_in_basic)),
    }
