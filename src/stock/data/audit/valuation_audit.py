"""估值指标数据 (daily_basic) 领域对账审计模块。"""

from datetime import date
from pathlib import Path
from typing import Any
import polars as pl
from stock.data.storage.compat import StorageCompat
from stock.utils.logger import logger


def run_daily_basic_audit(
    target_date: date, data_source: str = "tushare", quiet: bool = False
) -> dict[str, Any]:
    """对比审计 daily_basic (每日估值指标) 与 stock_daily_bar (K线行情) 的 1-to-1 对齐匹配率。"""
    logger.info(f"开始 daily_basic 估值对账审计，目标日期: {target_date} [数据源: {data_source}]")

    # 1. 读取行情 K 线记录
    daily_dir = Path(
        f"data/curated/{data_source}/market=CN/stock_daily_bar/"
        f"year={target_date.year:04d}/month={target_date.month:02d}"
    )
    daily_files = (
        [p for p in daily_dir.glob("*.parquet") if not StorageCompat.is_artifact_path(p)]
        if daily_dir.exists()
        else []
    )
    try:
        daily_df = pl.read_parquet(daily_files) if daily_files else pl.DataFrame()
        daily_df = StorageCompat.safe_cast_date_col(daily_df, "trade_date")
        bar_df = daily_df.filter(pl.col("trade_date") == target_date)
        bar_symbols = set(bar_df["symbol"].unique().to_list())
    except Exception as exc:
        logger.debug(f"读取 stock_daily_bar 对账失败: {exc}")
        bar_symbols = set()

    # 2. 读取每日指标 daily_basic 记录
    basic_dir = Path(
        f"data/curated/{data_source}/market=CN/daily_basic/"
        f"year={target_date.year:04d}/month={target_date.month:02d}"
    )
    basic_files = (
        [p for p in basic_dir.glob("*.parquet") if not StorageCompat.is_artifact_path(p)]
        if basic_dir.exists()
        else []
    )
    try:
        db_df = pl.read_parquet(basic_files) if basic_files else pl.DataFrame()
        db_df = StorageCompat.safe_cast_date_col(db_df, "trade_date")
        target_db = db_df.filter(pl.col("trade_date") == target_date)
        basic_symbols = set(target_db["symbol"].unique().to_list())
    except Exception as exc:
        logger.debug(f"读取 daily_basic 对账失败: {exc}")
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


def run_sw_industry_audit(
    target_date: date, data_source: str = "lixinger", quiet: bool = False
) -> dict[str, Any]:
    """审计申万 2021 版行业成分股图谱 (sw_2021_constituents) 与行业全历史估值序列 (sw_2021_fundamental)。"""
    logger.info(f"开始申万行业图谱与估值对账审计，目标日期: {target_date} [数据源: {data_source}]")

    # 1. 检查 sw_2021_constituents 行业图谱落盘
    const_path = f"data/curated/{data_source}/market=CN/sw_2021_constituents/data.parquet"
    try:
        const_df = pl.read_parquet(const_path)
        const_count = const_df["symbol"].n_unique() if "symbol" in const_df.columns else 0
    except Exception:
        const_count = 0

    # 2. 检查 sw_2021_fundamental 在 target_date 的估值记录
    fund_path = f"data/curated/{data_source}/market=CN/sw_2021_fundamental/data.parquet"
    try:
        fund_df = pl.read_parquet(fund_path)
        fund_df = StorageCompat.safe_cast_date_col(fund_df, "trade_date")
        target_fund = fund_df.filter(pl.col("trade_date") == target_date)
        ind_symbols = set(target_fund["symbol"].unique().to_list()) if "symbol" in target_fund.columns else set()
    except Exception as exc:
        logger.debug(f"读取 sw_2021_fundamental 对账失败: {exc}")
        ind_symbols = set()

    expected_ind_count = 31  # 申万 2021 版一级行业固定为 31 个
    match_count = len(ind_symbols)
    coverage_rate = (match_count / expected_ind_count * 100.0) if expected_ind_count else 0.0

    if not quiet:
        print("\n" + "=" * 65)
        print(f"      【申万 2021 行业成份股图谱与行业估值对账报告 ({target_date})】")
        print("=" * 65)
        print(f"已落盘申万行业节点总数 : {const_count:>6} 个 (包含一、二、三级全部行业)")
        print(f"理论申万一级行业总数   : {expected_ind_count:>6} 个")
        print(f"当日完成估值对账行业数 : {match_count:>6} 个")
        print(f"申万行业估值覆盖率     : {coverage_rate:>6.2f} %")
        print("=" * 65 + "\n")

    return {
        "target_date": target_date,
        "constituents_industry_count": const_count,
        "expected_primary_industry_count": expected_ind_count,
        "actual_industry_count": match_count,
        "coverage_rate": coverage_rate,
    }
