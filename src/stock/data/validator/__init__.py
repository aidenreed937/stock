"""离线数据完整性与准确性审计工具 (Offline Data Validator)。"""

import argparse
from datetime import date
from typing import Any

import polars as pl

from stock.data.cleaner.bar_cleaner import BarDataCleaner
from stock.data.storage.duckdb_store import DuckDBMarketStore
from stock.data.task_registry import resolve_task
from stock.utils.logger import setup_logger

from stock.data.validator.rules import (
    BaseValidationRule,
    CompletenessRule,
    DistributionAuditRule,
    NullCheckRule,
    OhlcLogicRule,
    PrimaryKeyRule,
    VolatilityRule,
)


class OfflineDataValidator:
    """离线数据质量审计器，负责校验本地落盘 parquet 与 DuckDB 行情数据的完整性与准确性。"""

    def __init__(
        self,
        store: DuckDBMarketStore | None = None,
        rules: list[BaseValidationRule] | None = None,
    ) -> None:
        """初始化校验器。

        Args:
            store: DuckDB 存储实例，若为 None 则自动创建。
            rules: 校验规则链，若为 None 则默认组装日线全套校验规则。
        """
        self.store = store or DuckDBMarketStore()
        data_source = getattr(self.store, "data_source", None)
        if not isinstance(data_source, str) or not data_source:
            data_source = "tushare"
        listing_dates = BarDataCleaner.load_listing_dates(data_source)
        self.rules = (
            rules
            if rules is not None
            else [
                NullCheckRule(),
                PrimaryKeyRule(),
                OhlcLogicRule(),
                VolatilityRule(listing_dates=listing_dates),
                CompletenessRule(),
                DistributionAuditRule(),
            ]
        )

    def audit_daily_bars(
        self,
        endpoint: str = "stock_daily_bar",
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, Any]:
        """对本地存储的日线行情数据执行完整性与准确性离线审计。

        校验维度通过注入的 rules 规则链执行。

        Returns:
            dict: 包含各项审计指标与结论的报告元数据。
        """
        df = self.store.query_history(endpoint=endpoint, start_date=start_date, end_date=end_date)
        if df.is_empty():
            return {"status": "EMPTY", "message": "未检索到任何本地归档数据"}

        total_records = len(df)
        unique_dates = df["trade_date"].unique().to_list() if "trade_date" in df.columns else []
        unique_symbols = df["symbol"].unique().to_list() if "symbol" in df.columns else []

        report: dict[str, Any] = {
            "total_records": total_records,
            "unique_dates_count": len(unique_dates),
            "unique_symbols_count": len(unique_symbols),
        }

        all_passed = True
        rules = self.rules
        task = resolve_task(self.store.data_source or "tushare", endpoint)
        if task.task_name == "stock_daily_bar" and any(
            isinstance(rule, CompletenessRule) for rule in rules
        ):
            expected_counts = self._historical_expected_counts(df)
            rules = [
                CompletenessRule(
                    min_count=rule.min_count,
                    max_count=rule.max_count,
                    expected_counts=expected_counts,
                    min_coverage=rule.min_coverage,
                )
                if isinstance(rule, CompletenessRule)
                else rule
                for rule in rules
            ]
        try:
            from stock.data.fetcher.tushare.registry import TUSHARE_API_REGISTRY

            meta = TUSHARE_API_REGISTRY.get(task.api_name)
            registered_keys = (
                list(meta.primary_keys)
                if meta and all(key in df.columns for key in meta.primary_keys)
                else []
            )
            if registered_keys:
                rules = [
                    PrimaryKeyRule(keys=registered_keys),
                    *[rule for rule in self.rules if not isinstance(rule, PrimaryKeyRule)],
                ]
        except Exception:
            pass
        for rule in rules:
            res = rule.audit(df)
            for k, v in res.items():
                if k != "passed":
                    report[k] = v
            if not res.get("passed", True):
                all_passed = False

        report["status"] = "PASSED" if all_passed else "WARNING"
        return report

    def _historical_expected_counts(self, bars: pl.DataFrame) -> dict[date, int]:
        """按 stock_basic 的上市日期估算各交易日可用标的基数。"""
        basic = self.store.query_dataset(dataset="stock_basic")
        if (
            not isinstance(basic, pl.DataFrame)
            or basic.is_empty()
            or "list_date" not in basic.columns
        ):
            return {}
        trade_dates = bars.get_column("trade_date")
        if trade_dates.dtype != pl.Date:
            trade_dates = trade_dates.cast(pl.Date, strict=False)
        listed = basic.with_columns(
            pl.col("list_date")
            .cast(pl.Utf8)
            .str.to_date("%Y%m%d", strict=False)
            .alias("_list_date")
        )
        return {
            target_date: listed.filter(pl.col("_list_date") <= target_date).height
            for target_date in trade_dates.unique().to_list()
            if target_date is not None
        }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="本地存储行情数据离线质量审计工具")
    parser.add_argument(
        "--endpoint",
        type=str,
        default="stock_daily_bar",
        help="审计的项目任务名 (默认: stock_daily_bar)",
    )
    parser.add_argument("--strict", action="store_true", help="异常时以非零状态退出")
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
        if args.strict:
            raise SystemExit(1)
        return

    status_str = (
        "[PASS] 100% 审计合规" if report["status"] == "PASSED" else "[WARN] 存在异常或可疑数据"
    )
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
    print("【2. 准确性校验与数据故障诊断】")
    print(
        f"  - OHLC 物理逻辑错误数: {report['physical_errors']:>10} 行 (如 high<low 或 <=0，预期: 0)"
    )
    print(
        f"  - 涨跌幅公式推演偏差数: {report['calc_diff_errors']:>10} 行 (与 (close-pre)/pre 偏差>0.1%，预期: 0)"
    )
    print(f"  - 极端飞线/错位故障数: {report['spike_faults']:>10} 行 (如单日涨跌幅>500%，预期: 0)")
    print(f"  - 换手率物理溢出故障数: {report['turnover_faults']:>10} 行 (如换手率>300%，预期: 0)")
    print("-" * 75)
    print("【3. 按交易日数据量分布明细】")
    dist = report["daily_distribution"]
    for row in dist.iter_rows(named=True):
        d_str = str(row["trade_date"])
        c_cnt = row["count"]
        flag = "[OK]" if 3000 <= c_cnt < 6000 else "[WARN]"
        print(f"  {flag} {d_str} : {c_cnt:>6} 条记录")

    print("=" * 75)
    if args.strict and report["status"] != "PASSED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
