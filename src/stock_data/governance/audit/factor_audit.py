"""复权因子与因子数据 (adj_factor) 领域对账审计模块。"""

from datetime import date
from typing import Any

import polars as pl

from stock_core.utils.logger import logger
from stock_data.core.settings import data_settings
from stock_data.governance.audit.benchmarks.industry import IndustryDailyBenchmarkProvider
from stock_data.storage.compat import StorageCompat


def run_adj_factor_audit(
    target_date: date, data_source: str = "tushare", quiet: bool = False
) -> dict[str, Any]:
    """审计 adj_factor (复权因子) 在全市场有效上市个股中的物理覆盖率与断点。"""
    logger.info(
        f"开始 adj_factor 复权因子对账审计，目标日期: {target_date} [数据源: {data_source}]"
    )

    # 1. 读取 stock_basic 理论上市股票池
    basic_dir = data_settings.curated_data_dir / data_source
    try:
        basic_files = [
            p
            for p in basic_dir.rglob("*.parquet")
            if "stock_basic" in p.parts and not StorageCompat.is_artifact_path(p)
        ]
        basic_df = pl.read_parquet(basic_files) if basic_files else pl.DataFrame()
        basic_df = StorageCompat.safe_cast_date_col(basic_df, "list_date")
        expected_df = basic_df.filter(pl.col("list_date") <= target_date)
        sym_col = "symbol" if "symbol" in basic_df.columns else "ts_code"
        expected_symbols = set(expected_df[sym_col].drop_nulls().unique().to_list())
    except Exception:
        expected_symbols = set()

    # 2. 读取 adj_factor 记录
    year_str = f"year={target_date.year:04d}"
    month_str = f"month={target_date.month:02d}"
    adj_files = [
        p
        for p in basic_dir.rglob("*.parquet")
        if "adj_factor" in p.parts
        and year_str in p.parts
        and month_str in p.parts
        and not StorageCompat.is_artifact_path(p)
    ]
    try:
        adj_df = pl.read_parquet(adj_files) if adj_files else pl.DataFrame()
        adj_df = StorageCompat.safe_cast_date_col(adj_df, "trade_date")
        target_adj = adj_df.filter(pl.col("trade_date") == target_date)
        actual_symbols = set(target_adj["symbol"].unique().to_list())
    except Exception as exc:
        logger.debug(f"读取 adj_factor 对账失败: {exc}")
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


def run_sw_daily_audit(
    target_date: date, data_source: str = "tushare", quiet: bool = False
) -> dict[str, Any]:
    """审计 sw_daily (申万行业日线行情) 在指定交易日的全市场行业覆盖率。"""
    logger.info(
        f"开始 sw_daily 申万行业日行情对账审计，目标日期: {target_date} [数据源: {data_source}]"
    )

    source_dir = data_settings.curated_data_dir / data_source
    year_str = f"year={target_date.year:04d}"
    month_str = f"month={target_date.month:02d}"
    sw_files = [
        p
        for p in source_dir.rglob("*.parquet")
        if "sw_daily" in p.parts
        and year_str in p.parts
        and month_str in p.parts
        and not StorageCompat.is_artifact_path(p)
    ]
    try:
        sw_df = pl.read_parquet(sw_files) if sw_files else pl.DataFrame()
        sw_df = StorageCompat.safe_cast_date_col(sw_df, "trade_date")
        target_sw = sw_df.filter(pl.col("trade_date") == target_date)
        actual_symbols = (
            set(target_sw["symbol"].unique().to_list()) if "symbol" in target_sw.columns else set()
        )
    except Exception as exc:
        logger.debug(f"读取 sw_daily 对账失败: {exc}")
        actual_symbols = set()

    # 动态获取申万一级行业基准
    provider = IndustryDailyBenchmarkProvider(data_source=data_source)
    expected_l1_symbols = set(provider._get_industry_codes())
    expected_l1_count = len(expected_l1_symbols)

    l1_symbols = actual_symbols.intersection(expected_l1_symbols)
    l1_match_count = len(l1_symbols)
    l1_coverage_rate = (l1_match_count / expected_l1_count * 100.0) if expected_l1_count else 0.0

    classification_counts: dict[str, int] = {}
    if {"classification", "industry_level"}.issubset(target_sw.columns):
        classification_counts = {
            f"{row['classification']}:{row['industry_level']}": row["len"]
            for row in target_sw.group_by(["classification", "industry_level"]).len().to_dicts()
        }
        unmapped_count = (
            target_sw.filter(pl.col("classification_status") == "unmapped").height
            if "classification_status" in target_sw.columns
            else 0
        )
    else:
        unmapped_count = len(actual_symbols - expected_l1_symbols)

    if not quiet:
        print("\n" + "=" * 65)
        print(f"       【sw_daily 申万行业日行情对账报告 ({target_date})】")
        print("=" * 65)
        print(f"申万一级行业理论数     : {expected_l1_count:>6} 个")
        print(f"申万一级行业落盘数     : {l1_match_count:>6} 个")
        print(f"申万一级行业覆盖率     : {l1_coverage_rate:>6.2f} %")
        print(f"全级次行业落盘节点总数 : {len(actual_symbols):>6} 个 (含一、二、三级全部行业)")
        print("=" * 65 + "\n")

    return {
        "target_date": target_date,
        "expected_count": expected_l1_count,
        "actual_count": l1_match_count,
        "expected_l1_count": expected_l1_count,
        "actual_l1_count": l1_match_count,
        "coverage_rate": l1_coverage_rate,
        "l1_coverage_rate": l1_coverage_rate,
        "total_industry_count": len(actual_symbols),
        "actual_symbols": sorted(list(actual_symbols)),
        "classification_counts": classification_counts,
        "unmapped_count": unmapped_count,
    }
