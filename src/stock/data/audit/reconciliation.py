"""A 股全市场数据完整性与停牌对账审计模块。"""

import argparse
from datetime import date, datetime, timedelta
from pathlib import Path
import sys
from typing import Any

import polars as pl

from stock.data.fetcher.tushare.client import TuShareClient
from stock.utils.logger import logger


def run_audit(target_date: date, data_source: str = "tushare", quiet: bool = False) -> dict[str, Any]:
    """对指定单日进行 A 股行情完整性审计对账。

    Args:
        target_date: 目标审计日期。
        data_source: 数据源标识 (默认 tushare)。
        quiet: 是否抑制 stdout 日报表控制台打印 (用于历史区间批量审计时静默模式)。

    Returns:
        dict[str, Any]: 单日审计结果统计字典。
    """
    logger.info(f"开始对账审计，目标日期: {target_date} [数据源: {data_source}]")

    # 1. 检查 stock_basic 基础元数据是否存在
    basic_pattern = f"data/curated/{data_source}/market=CN/stock_basic"
    try:
        basic_files = list(Path(basic_pattern).rglob("*.parquet"))
        if basic_files:
            basic_df = pl.read_parquet(basic_files)
        else:
            # 兼容 Mock 路径或空情形
            basic_df = pl.read_parquet(f"{basic_pattern}/data.parquet")
    except Exception as e:
        logger.error(f"加载 [{data_source}] stock_basic 数据集失败，请确认是否已执行过基础数据拉取: {e}")
        return {}

    # 2. 读取对应月份的 daily_bar 数据
    daily_pattern = f"data/curated/{data_source}/market=CN/stock_daily_bar/year={target_date.year:04d}/month={target_date.month:02d}/*.parquet"
    try:
        daily_df = pl.read_parquet(daily_pattern)
    except Exception:
        daily_df = pl.DataFrame()

    if daily_df.is_empty():
        logger.warning(f"本地日K行情库中未找到 {target_date} 的任何数据")
        actual_symbols: set[str] = set()
    else:
        # 确保 trade_date 转换为 date 类型进行比较
        if daily_df["trade_date"].dtype == pl.String:
            daily_df = daily_df.with_columns(
                pl.col("trade_date").str.to_date("%Y-%m-%d").alias("trade_date")
            )
        day_df = daily_df.filter(pl.col("trade_date") == target_date)
        actual_symbols = set(day_df["symbol"].unique().to_list())

    # 3. 筛选理论上在 target_date 已经上市且未退市的个股
    if "delist_date" in basic_df.columns and basic_df["delist_date"].dtype != pl.Null:
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

    suspended_symbols: list[str] = []
    unexplained_symbols: list[str] = []

    # 5. 对于缺失的个股，通过 TuShare 停牌接口校验当天是否真实停牌
    if missing_count > 0:
        logger.info(f"正在通过 TuShare 停牌接口审计这 {missing_count} 只个股的交易状态...")
        try:
            client = TuShareClient()
            trade_date_str = target_date.strftime("%Y%m%d")
            suspend_df = client.query("suspend_d", trade_date=trade_date_str)

            if suspend_df is not None and len(suspend_df) > 0:
                if hasattr(suspend_df, "get_column"):
                    suspend_set = set(suspend_df.get_column("ts_code").unique().to_list())
                else:
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

    if not quiet:
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


def get_trading_calendar(start_date: date, end_date: date) -> list[date]:
    """获取指定时间段内的开市交易日列表（优先尝试从 Fetcher 获取，失败时按工作日自动降级）。"""
    try:
        from stock.data.fetcher.tushare.facade import TuShareDataFetcher

        fetcher = TuShareDataFetcher()
        cal = fetcher.fetch_trade_cal(start_date, end_date)
        if isinstance(cal, list) and cal:
            return [d for d in cal if isinstance(d, date)]
    except Exception as e:
        logger.debug(f"无法获取数据源交易日历: {e}，使用工作日降级策略")

    cur = start_date
    dates: list[date] = []
    while cur <= end_date:
        if cur.weekday() < 5:
            dates.append(cur)
        cur += timedelta(days=1)
    return dates


def run_audit_range(
    start_date: date,
    end_date: date,
    data_source: str = "tushare",
    max_workers: int = 4,
    show_details: bool = False,
) -> dict[str, Any]:
    """对指定历史时间范围（多交易日）进行批量多线程完整性对账审计。

    Args:
        start_date: 开始日期。
        end_date: 结束日期。
        data_source: 数据源标识 (默认 tushare)。
        max_workers: 并发线程数 (默认 4)。
        show_details: 是否为每个交易日打印详细的每日报告 (默认 False)。

    Returns:
        dict[str, Any]: 历史区间汇总审计统计报告。
    """
    logger.info(
        f"开始历史时间段对账审计 (区间: {start_date} ~ {end_date}, 数据源: {data_source}, 线程数: {max_workers})..."
    )

    open_dates = get_trading_calendar(start_date, end_date)
    if not open_dates:
        logger.warning(f"在日期范围 [{start_date} ~ {end_date}] 内未查找到有效交易日")
        return {}

    logger.info(f"成功获取交易日历，共计 {len(open_dates)} 个有效交易日，开始并发审计...")

    daily_results: list[dict[str, Any]] = []

    if max_workers > 1 and len(open_dates) > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_date = {
                executor.submit(run_audit, d, data_source=data_source, quiet=not show_details): d
                for d in open_dates
            }
            for fut in as_completed(future_to_date):
                try:
                    res = fut.result()
                    if res:
                        daily_results.append(res)
                except Exception as e:
                    d = future_to_date[fut]
                    logger.error(f"交易日 [{d}] 审计抛出异常: {e}")
    else:
        for d in open_dates:
            res = run_audit(d, data_source=data_source, quiet=not show_details)
            if res:
                daily_results.append(res)

    if not daily_results:
        logger.warning("未能获取到任何有效的单日审计结果")
        return {}

    # 按交易日升序排序结果
    daily_results.sort(key=lambda x: x["date"])

    total_days = len(daily_results)
    avg_integrity_rate = (
        sum(r["integrity_rate"] for r in daily_results) / total_days
        if total_days > 0
        else 0.0
    )

    problematic_days = [r for r in daily_results if r["unexplained"] > 0]
    perfect_days_count = total_days - len(problematic_days)

    # 汇总各股票异常缺失出现的频次
    symbol_missing_counts: dict[str, int] = {}
    for r in daily_results:
        for sym in r.get("unexplained_symbols", []):
            symbol_missing_counts[sym] = symbol_missing_counts.get(sym, 0) + 1

    top_missing_symbols = sorted(
        symbol_missing_counts.items(), key=lambda x: x[1], reverse=True
    )

    print("\n" + "=" * 65)
    print(
        f"       历史时间段数据完整性对账审计汇总报告 [{start_date} ~ {end_date}] (数据源: {data_source})       "
    )
    print("=" * 65)
    print(f"1. 审计交易日总数 (Trading Days):    {total_days} 天")
    print(f"2. 完美无缺失天数 (Perfect Days):    {perfect_days_count} 天")
    print(f"3. 存在异常缺失天数 (Problem Days):   {len(problematic_days)} 天")
    print(f"4. 区间平均数据完整率 (Avg Integrity Rate): {avg_integrity_rate:.2f}%")
    print("=" * 65)

    if top_missing_symbols:
        print("\n[警告] 区间内频次最高的异常缺失股票 Top 10:")
        for sym, freq in top_missing_symbols[:10]:
            ratio = (freq / total_days) * 100.0
            print(f" - {sym}: 缺失 {freq} 个交易日 ({ratio:.1f}%)")
        print("=" * 65)
    else:
        print("\n[优秀] 恭喜！在整个历史区间内，所有交易日均实现 100% 数据完备对算。")
        print("=" * 65)

    return {
        "start_date": start_date,
        "end_date": end_date,
        "total_days": total_days,
        "perfect_days": perfect_days_count,
        "problematic_days": len(problematic_days),
        "avg_integrity_rate": avg_integrity_rate,
        "top_missing_symbols": top_missing_symbols,
        "daily_results": daily_results,
    }


def run_index_audit(
    target_date: date, data_source: str = "tushare", quiet: bool = False
) -> dict[str, Any]:
    """对指定单日进行指数观察池完整性审计对账。"""
    from stock.config.loader import load_data_config

    cfg = load_data_config()
    wl = getattr(cfg.watchlists, data_source, None)
    all_configured_indices = set(wl.indices) if (wl and hasattr(wl, "indices")) else set()

    # 指数发布/基日地图 (剔除未到发布日的预期标的)
    index_start_dates: dict[str, date] = {
        "000001.SH": date(1990, 12, 19),
        "399001.SZ": date(1994, 7, 20),
        "000300.SH": date(2005, 4, 8),  # 沪深300发布日
        "000905.SH": date(2007, 1, 15),  # 中证500发布日
        "000852.SH": date(2014, 10, 17),  # 中证1000发布日
        "000985.CSI": date(2013, 1, 15),  # 中证全指发布日
        "000922.CSI": date(2005, 1, 4),  # 中证红利发布日
        "399006.SZ": date(2010, 6, 1),  # 创业板指发布日
        "399102.SZ": date(2010, 6, 1),  # 创业板综发布日
        "000688.SH": date(2020, 7, 23),  # 科创50发布日
    }

    expected_indices = {
        sym
        for sym in all_configured_indices
        if sym not in index_start_dates or index_start_dates[sym] <= target_date
    }

    if not expected_indices:
        if not quiet:
            logger.warning(f"数据源 [{data_source}] 未配置指数观察池")
        return {}

    pattern = f"data/curated/{data_source}/market=*/index_daily*/year={target_date.year:04d}/month={target_date.month:02d}/*.parquet"
    try:
        df = pl.read_parquet(pattern)
        if not df.is_empty():
            if df["trade_date"].dtype == pl.String:
                df = df.with_columns(
                    pl.col("trade_date").str.to_date("%Y-%m-%d").alias("trade_date")
                )
            sub_df = df.filter(pl.col("trade_date") == target_date)
            actual_indices = set(sub_df["symbol"].to_list())
        else:
            actual_indices = set()
    except Exception:
        actual_indices = set()

    missing = expected_indices - actual_indices
    integrity_rate = (
        (len(actual_indices) / len(expected_indices) * 100.0) if expected_indices else 0.0
    )

    if not quiet:
        logger.info(
            f"指数审计结果 [{target_date}]: 预期 {len(expected_indices)} 个, "
            f"实际 {len(actual_indices)} 个, 缺失: {list(missing)}, 完整率: {integrity_rate:.2f}%"
        )

    return {
        "date": target_date,
        "expected_count": len(expected_indices),
        "actual_count": len(actual_indices),
        "missing_count": len(missing),
        "missing_indices": list(missing),
        "integrity_rate": integrity_rate,
    }


def run_index_audit_range(
    start_date: date,
    end_date: date,
    data_source: str = "tushare",
    max_workers: int = 4,
    show_details: bool = False,
) -> dict[str, Any]:
    """对指定时间段进行指数观察池完整性审计对账。"""
    logger.info(
        f"开始指数时间段对账审计 (区间: {start_date} ~ {end_date}, 数据源: {data_source})..."
    )

    trading_dates = get_trading_calendar(start_date, end_date)
    if not trading_dates:
        logger.error(f"获取 {start_date} ~ {end_date} 交易日历失败")
        return {}

    daily_results: list[dict[str, Any]] = []
    perfect_count = 0

    for d in trading_dates:
        res = run_index_audit(d, data_source=data_source, quiet=not show_details)
        if res:
            daily_results.append(res)
            if res["missing_count"] == 0 and res["integrity_rate"] >= 100.0:
                perfect_count += 1

    total_days = len(daily_results)
    avg_rate = (
        sum(r["integrity_rate"] for r in daily_results) / total_days if total_days > 0 else 0.0
    )

    print("\n" + "=" * 65)
    print(
        f"       指数时间段完整性对账审计汇总报告 [{start_date} ~ {end_date}] (数据源: {data_source})       "
    )
    print("=" * 65)
    print(f"1. 审计交易日总数 (Trading Days):    {total_days} 天")
    print(f"2. 完美无缺失天数 (Perfect Days):    {perfect_count} 天")
    print(f"3. 存在缺失天数 (Problem Days):     {total_days - perfect_count} 天")
    print(f"4. 区间平均数据完整率 (Avg Integrity Rate): {avg_rate:.2f}%")
    print("=" * 65 + "\n")

    return {
        "total_days": total_days,
        "perfect_days": perfect_count,
        "avg_integrity_rate": avg_rate,
        "daily_results": daily_results,
    }


from stock.data.audit.factor_audit import run_adj_factor_audit
from stock.data.audit.moneyflow_audit import run_hk_hold_audit
from stock.data.audit.valuation_audit import run_daily_basic_audit, run_sw_industry_audit


def main() -> None:
    parser = argparse.ArgumentParser(description="数据完整性对账与审计工具")
    parser.add_argument(
        "-s",
        "--source",
        "--data-source",
        dest="data_source",
        type=str,
        default="tushare",
        help="数据源标识名称 (如 tushare / yfinance / lixinger，默认: tushare)",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="stock",
        choices=["stock", "index", "daily_basic", "adj_factor", "hk_hold", "sw_industry"],
        help="对账模式 (stock: K线审计, index: 指数审计, daily_basic: 估值对账, adj_factor: 复权因子对账, hk_hold: 北向持仓, sw_industry: 申万行业成份股及估值)",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="对账目标单日 (格式: YYYY-MM-DD)",
    )
    parser.add_argument(
        "--start",
        type=str,
        default=None,
        help="历史区间对账开始日期 (格式: YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="历史区间对账结束日期 (格式: YYYY-MM-DD)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="历史区间批量对账时的并发线程数 (默认: 4)",
    )
    parser.add_argument(
        "--show-details",
        action="store_true",
        help="历史区间批量对账时是否显示每日明细",
    )
    args = parser.parse_args()

    data_source = args.data_source or "tushare"

    if args.start and args.end:
        try:
            start_d = datetime.strptime(args.start, "%Y-%m-%d").date()
            end_d = datetime.strptime(args.end, "%Y-%m-%d").date()
        except ValueError:
            logger.error("开始日期或结束日期格式不正确，必须为 YYYY-MM-DD")
            sys.exit(1)
        if args.mode == "index":
            run_index_audit_range(
                start_d,
                end_d,
                data_source=data_source,
                max_workers=args.max_workers,
                show_details=args.show_details,
            )
        else:
            run_audit_range(
                start_d,
                end_d,
                data_source=data_source,
                max_workers=args.max_workers,
                show_details=args.show_details,
            )
    else:
        target_date: date
        if args.date:
            try:
                target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
            except ValueError:
                logger.error("日期格式不正确，必须为 YYYY-MM-DD")
                sys.exit(1)
        else:
            target_date = date.today() - timedelta(days=1)

        if args.mode == "index":
            run_index_audit(target_date, data_source=data_source)
        elif args.mode == "daily_basic":
            run_daily_basic_audit(target_date, data_source=data_source)
        elif args.mode == "adj_factor":
            run_adj_factor_audit(target_date, data_source=data_source)
        elif args.mode == "hk_hold":
            run_hk_hold_audit(target_date, data_source=data_source)
        elif args.mode == "sw_industry":
            run_sw_industry_audit(target_date, data_source=args.data_source if args.data_source != "tushare" else "lixinger")
        else:
            run_audit(target_date, data_source=data_source)


if __name__ == "__main__":
    main()
