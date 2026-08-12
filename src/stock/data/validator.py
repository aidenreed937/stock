"""离线数据完整性与准确性审计工具 (Offline Data Validator)。"""

import argparse
from datetime import date
from typing import Any

import polars as pl

from stock.data.storage.duckdb_store import DuckDBMarketStore
from stock.utils.logger import logger, setup_logger


class OfflineDataValidator:
    """离线数据质量审计器，负责校验本地落盘 parquet 与 DuckDB 行情数据的完整性与准确性。"""

    def __init__(self, store: DuckDBMarketStore | None = None) -> None:
        """初始化校验器。

        Args:
            store: DuckDB 存储实例，若为 None 则自动创建。
        """
        self.store = store or DuckDBMarketStore()

    def audit_daily_bars(
        self, endpoint: str = "daily", start_date: date | None = None, end_date: date | None = None
    ) -> dict[str, Any]:
        """对本地存储的日线行情数据执行完整性与准确性离线审计。

        校验维度包括:
        1. 时间轴完整性 (包含天数、唯一交易日数)。
        2. 截断与覆盖率异常检测 (每天记录数是否在合规区间 [3000, 6000])。
        3. 主键唯一性 (symbol + trade_date 组合重复率)。
        4. 物理与逻辑准确性 (空值率、价格非正值、OHLC 物理关系错误数)。
        5. 涨跌幅一致性 (pct_chg 与 (close - pre_close)/pre_close 对齐度)。

        Returns:
            dict: 包含各项审计指标与结论的报告元数据。
        """
        df = self.store.query_history(endpoint=endpoint, start_date=start_date, end_date=end_date)
        if df.is_empty():
            return {"status": "EMPTY", "message": "未检索到任何本地归档数据"}

        total_records = len(df)
        unique_dates = df["trade_date"].unique().to_list()
        unique_symbols = df["symbol"].unique().to_list()

        # 1. 每日记录数分布统计与截断/缺失检测
        date_counts = df.group_by("trade_date").agg(pl.count("symbol").alias("count")).sort("trade_date")
        anomaly_dates = date_counts.filter((pl.col("count") < 3000) | (pl.col("count") >= 6000))
        truncated_dates = date_counts.filter(pl.col("count") >= 6000)

        # 2. 主键重复数校验
        dup_count = total_records - len(df.unique(subset=["symbol", "trade_date"]))

        # 3. 核心关键列空值校验
        null_counts = {
            col: df[col].null_count()
            for col in ["symbol", "trade_date", "close", "open", "high", "low"]
            if col in df.columns
        }
        total_nulls = sum(null_counts.values())

        # 4. OHLC 物理逻辑错误数校验
        physical_errors = df.filter(
            (pl.col("open") <= 0)
            | (pl.col("high") <= 0)
            | (pl.col("low") <= 0)
            | (pl.col("close") <= 0)
            | (pl.col("high") < pl.col("low"))
            | (pl.col("high") < pl.col("open"))
            | (pl.col("high") < pl.col("close"))
            | (pl.col("low") > pl.col("open"))
            | (pl.col("low") > pl.col("close"))
        )
        physical_error_count = len(physical_errors)

        # 5. 涨跌幅计算偏差度校验 (仅在包含 pre_close 时计算)
        calc_diff_count = 0
        if "pre_close" in df.columns and "pct_chg" in df.columns:
            diff_df = df.filter(pl.col("pre_close") > 0).with_columns(
                (((pl.col("close") - pl.col("pre_close")) / pl.col("pre_close") * 100) - pl.col("pct_chg"))
                .abs()
                .alias("diff")
            )
            # 允许 0.1% 内的尾数舍入浮点误差
            calc_diff_count = len(diff_df.filter(pl.col("diff") > 0.1))

        passed = (
            dup_count == 0
            and total_nulls == 0
            and physical_error_count == 0
            and len(truncated_dates) == 0
        )

        return {
            "status": "PASSED" if passed else "WARNING",
            "total_records": total_records,
            "unique_dates_count": len(unique_dates),
            "unique_symbols_count": len(unique_symbols),
            "duplicate_records": dup_count,
            "total_nulls": total_nulls,
            "null_details": null_counts,
            "physical_errors": physical_error_count,
            "calc_diff_errors": calc_diff_count,
            "truncated_dates_count": len(truncated_dates),
            "anomaly_dates_count": len(anomaly_dates),
            "daily_distribution": date_counts,
        }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="本地存储行情数据离线质量审计工具")
    parser.add_argument("--endpoint", type=str, default="daily", help="审计的数据接口名 (默认: daily)")
    return parser.parse_args()


def main() -> None:
    """CLI 命令行入口点。"""
    setup_logger()
    args = _parse_args()
    validator = OfflineDataValidator()
    report = validator.audit_daily_bars(endpoint=args.endpoint)

    print("=" * 75)
    print(f"       离线数据完整性与准确性审计报告 [{args.endpoint.upper()}]       ")
    print("=" * 75)

    if report["status"] == "EMPTY":
        print("[WARN] 未检测到任何本地落盘数据！")
        print("=" * 75)
        return

    status_str = "[PASS] 100% 审计合规" if report["status"] == "PASSED" else "[WARN] 存在异常或可疑数据"
    print(f"总体结论        : {status_str}")
    print(f"本地记录总条数  : {report['total_records']:>10,} 行")
    print(f"交易日覆盖天数  : {report['unique_dates_count']:>10} 天")
    print(f"涉及股票代码数  : {report['unique_symbols_count']:>10} 只")
    print("-" * 75)
    print("【1. 完整性校验】")
    print(f"  - 主键重复数  : {report['duplicate_records']:>10} 行 (预期: 0)")
    print(f"  - 核心字段空值: {report['total_nulls']:>10} 个 (预期: 0)")
    print(f"  - 截断日数量  : {report['truncated_dates_count']:>10} 天 (条数>=6000，预期: 0)")
    print(f"  - 异常日数量  : {report['anomaly_dates_count']:>10} 天 (条数<3000，预期: 0)")
    print("-" * 75)
    print("【2. 准确性校验】")
    print(f"  - OHLC 物理逻辑错误数: {report['physical_errors']:>10} 行 (如 high<low 或 <=0，预期: 0)")
    print(f"  - 涨跌幅公式推演偏差数: {report['calc_diff_errors']:>10} 行 (与 (close-pre)/pre 偏差>0.1%，预期: 0)")
    print("-" * 75)
    print("【3. 按交易日数据量分布明细】")
    dist = report["daily_distribution"]
    for row in dist.iter_rows(named=True):
        d_str = str(row["trade_date"])
        c_cnt = row["count"]
        flag = "[OK]" if 3000 <= c_cnt < 6000 else "[WARN]"
        print(f"  {flag} {d_str} : {c_cnt:>6} 条记录")

    print("=" * 75)


if __name__ == "__main__":
    main()
