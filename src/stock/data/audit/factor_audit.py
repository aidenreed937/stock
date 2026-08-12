"""复权因子与因子数据 (adj_factor) 领域对账审计模块。"""

from datetime import date
from pathlib import Path
from typing import Any
import polars as pl
from stock.utils.logger import logger


def run_adj_factor_audit(
    target_date: date, data_source: str = "tushare", quiet: bool = False
) -> dict[str, Any]:
    """审计 adj_factor (复权因子) 在全市场有效上市个股中的物理覆盖率与断点。"""
    logger.info(f"开始 adj_factor 复权因子对账审计，目标日期: {target_date} [数据源: {data_source}]")

    # 1. 读取 stock_basic 理论上市股票池
    basic_pattern = f"data/curated/{data_source}/market=CN/stock_basic"
    try:
        basic_files = list(Path(basic_pattern).rglob("*.parquet"))
        basic_df = pl.read_parquet(basic_files) if basic_files else pl.DataFrame()
        target_date_str = target_date.strftime("%Y%m%d")
        expected_df = basic_df.filter(pl.col("list_date") <= target_date_str)
        sym_col = "symbol" if "symbol" in basic_df.columns else "ts_code"
        expected_symbols = set(expected_df[sym_col].unique().to_list())
    except Exception:
        expected_symbols = set()

    # 2. 读取 adj_factor 记录
    adj_pattern = f"data/curated/{data_source}/market=CN/adj_factor/year={target_date.year:04d}/month={target_date.month:02d}/*.parquet"
    try:
        adj_df = pl.read_parquet(adj_pattern)
        if "trade_date" in adj_df.columns and adj_df["trade_date"].dtype == pl.String:
            adj_df = adj_df.with_columns(
                pl.col("trade_date").str.to_date("%Y-%m-%d").alias("trade_date")
            )
        target_adj = adj_df.filter(pl.col("trade_date") == target_date)
        actual_symbols = set(target_adj["symbol"].unique().to_list())
    except Exception:
        actual_symbols = set()

    match_count = len(expected_symbols.intersection(actual_symbols))
    missing_symbols = expected_symbols - actual_symbols
    coverage_rate = (match_count / len(expected_symbols) * 100.0) if expected_symbols else 0.0

    if not quiet:
        print("\n" + "=" * 65)
        print(f"       【adj_factor 复权因子全市场覆盖率报告 ({target_date})】")
        print("=" * 65)
        print(f"理论在册上市股票总数   : {len(expected_symbols):>6} 只")
        print(f"实际落盘复权因子个股数 : {len(actual_symbols):>6} 只")
        print(f"复权因子物理覆盖率     : {coverage_rate:>6.2f} %")
        if missing_symbols:
            print(f"缺失复权因子的股票数   : {len(missing_symbols):>6} 只")
        print("=" * 65 + "\n")

    return {
        "target_date": target_date,
        "expected_count": len(expected_symbols),
        "actual_count": len(actual_symbols),
        "coverage_rate": coverage_rate,
        "missing_symbols": sorted(list(missing_symbols)),
    }
