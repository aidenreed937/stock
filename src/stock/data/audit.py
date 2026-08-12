"""数据完整性对账与审计工具。"""

import argparse
from datetime import date, datetime
import sys
import polars as pl

from stock.data.storage.duckdb_store import DuckDBMarketStore
from stock.data.fetcher.tushare.client import TuShareClient
from stock.utils.logger import logger

from typing import Any


def run_audit(target_date: date) -> dict[str, Any]:
    """对指定日期进行 A 股行情完整性审计对账。"""
    logger.info(f"开始对账审计，目标日期: {target_date}")

    # 1. 检查 stock_basic 基础元数据是否存在
    basic_pattern = "data/curated/tushare/market=CN/stock_basic/*/*/*.parquet"
    try:
        basic_df = pl.read_parquet(basic_pattern)
    except Exception as e:
        logger.error(f"加载 stock_basic 数据集失败，请确认是否已执行过基础数据拉取: {e}")
        return {}

    # 2. 读取对应月份的 daily_bar 数据
    daily_pattern = f"data/curated/tushare/market=CN/stock_daily_bar/year={target_date.year:04d}/month={target_date.month:02d}/*.parquet"
    try:
        daily_df = pl.read_parquet(daily_pattern)
    except Exception:
        daily_df = pl.DataFrame()

    if daily_df.is_empty():
        logger.warning(f"本地日K行情库中未找到 {target_date} 的任何数据")
        actual_symbols = set()
    else:
        # 确保 trade_date 转换为 date 类型进行比较
        if daily_df["trade_date"].dtype == pl.String:
            daily_df = daily_df.with_columns(
                pl.col("trade_date").str.to_date("%Y-%m-%d").alias("trade_date")
            )
        day_df = daily_df.filter(pl.col("trade_date") == target_date)
        actual_symbols = set(day_df["symbol"].unique().to_list())

    # 3. 筛选理论上在 target_date 已经上市且未退市的个股
    # list_date 格式为 YYYYMMDD
    # delist_date 正常在市为空，退市股格式为 YYYYMMDD
    if "delist_date" in basic_df.columns:
        basic_df = basic_df.with_columns(
            [
                pl.col("list_date").str.to_date("%Y%m%d", strict=False).alias("list_date_d"),
                pl.col("delist_date").str.to_date("%Y%m%d", strict=False).alias("delist_date_d"),
            ]
        )
        expected_df = basic_df.filter(
            (
                (pl.col("list_date_d") >= date(1990, 12, 1))
                | (pl.col("ts_code").is_in(list(actual_symbols)))
            )
            & (pl.col("list_date_d") <= target_date)
            & (pl.col("delist_date_d").is_null() | (pl.col("delist_date_d") > target_date))
        )
    else:
        basic_df = basic_df.with_columns(
            pl.col("list_date").str.to_date("%Y%m%d", strict=False).alias("list_date_d")
        )
        expected_df = basic_df.filter(
            (
                (pl.col("list_date_d") >= date(1990, 12, 1))
                | (pl.col("ts_code").is_in(list(actual_symbols)))
            )
            & (pl.col("list_date_d") <= target_date)
        )
    expected_symbols = set(expected_df["ts_code"].unique().to_list())

    theoretical_count = len(expected_symbols)
    actual_count = len(actual_symbols)

    # 4. 计算差异个股
    missing_symbols = list(expected_symbols - actual_symbols)
    missing_count = len(missing_symbols)

    logger.info(
        f"预期上市个股数: {theoretical_count}，实际行情个股数: {actual_count}，缺失个股数: {missing_count}"
    )

    suspended_symbols = []
    unexplained_symbols = []

    # 5. 对于缺失的个股，通过 TuShare 停牌接口校验当天是否真实停牌
    if missing_count > 0:
        logger.info(f"正在通过 TuShare 停牌接口审计这 {missing_count} 只个股的交易状态...")
        try:
            client = TuShareClient()
            trade_date_str = target_date.strftime("%Y%m%d")
            suspend_df = client.query("suspend_d", trade_date=trade_date_str)

            if suspend_df is not None and not suspend_df.empty:
                suspend_set = set(suspend_df["ts_code"].unique().tolist())
                for sym in missing_symbols:
                    if sym in suspend_set:
                        suspended_symbols.append(sym)
                    else:
                        unexplained_symbols.append(sym)
            else:
                unexplained_symbols = missing_symbols
        except Exception as e:
            logger.error(f"调用 TuShare 停牌接口失败: {e}")
            unexplained_symbols = missing_symbols

    # 6. 计算最终的数据完整率
    verified_suspended_count = len(suspended_symbols)
    true_missing_count = len(unexplained_symbols)

    integrity_rate = 0.0
    if theoretical_count > 0:
        integrity_rate = (
            (actual_count + verified_suspended_count) / theoretical_count
        ) * 100.0

    print("\n" + "=" * 50)
    print(f"数据完整性对账审计报告 [{target_date}]")
    print("=" * 50)
    print(f"1. 理论已上市个股数 (Expected):  {theoretical_count}")
    print(f"2. 本地实际行情个股数 (Actual):  {actual_count}")
    print(f"3. 发现缺失股票总数 (Difference): {missing_count}")
    print(f"   - 证实停牌股票数 (Suspended): {verified_suspended_count}")
    print(f"   - 异常缺失股票数 (Unexplained): {true_missing_count}")
    print("-" * 50)
    print(f"4. 行情数据完整率 (Integrity Rate): {integrity_rate:.2f}%")
    print("=" * 50)

    if true_missing_count > 0:
        print(
            f"\n[警告] 以下 {true_missing_count} 只个股存在异常缺失，请检查网络拉取或尝试重新执行回填："
        )
        for sym in sorted(unexplained_symbols):
            name_val = expected_df.filter(pl.col("ts_code") == sym)["name"].to_list()
            name_str = name_val[0] if name_val else "未知"
            print(f" - {sym} ({name_str})")
        print("=" * 50)
    else:
        print("\n[优秀] 恭喜！当前交易日无任何异常缺失数据。")
        print("=" * 50)

    return {
        "date": target_date,
        "expected": theoretical_count,
        "actual": actual_count,
        "suspended": verified_suspended_count,
        "unexplained": true_missing_count,
        "integrity_rate": integrity_rate,
        "unexplained_symbols": unexplained_symbols,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="数据完整性对账与审计工具")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="对账目标日期 (格式: YYYY-MM-DD，默认使用最新有数据的交易日或今天前一日)",
    )
    args = parser.parse_args()

    target_date: date
    if args.date:
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            logger.error("日期格式不正确，必须为 YYYY-MM-DD")
            sys.exit(1)
    else:
        from datetime import timedelta

        target_date = date.today() - timedelta(days=1)

    run_audit(target_date)


if __name__ == "__main__":
    main()
