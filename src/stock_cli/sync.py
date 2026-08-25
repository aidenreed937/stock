"""统一增量数据更新 CLI 兼容入口。"""

from __future__ import annotations

import argparse
import sys
from datetime import date

import polars as pl

from stock_core.utils.logger import logger
from stock_data.pipeline.sync_runner import SyncSourceRun, run_sync


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("并发工作线程数必须大于 0")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="一键极速增量数据同步与自愈 CLI")
    parser.add_argument(
        "-s",
        "--source",
        default="tushare",
        help="数据源标识 (tushare / yfinance / lixinger / fred / alphavantage / all)",
    )
    parser.add_argument("-d", "--date", help="指定拟增量目标日期 (YYYY-MM-DD, 默认当日)")
    parser.add_argument("-e", "--endpoint", "--endpoints", dest="endpoints")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-audit", action="store_true")
    parser.add_argument("-w", "--max-workers", type=_positive_int, default=None)
    return parser


def _render_summary(run: SyncSourceRun) -> bool:
    """输出单个数据源的执行报告。"""
    source = run.source
    if run.plan:
        logger.info(f"[{source.upper()}] 增量同步规划与就绪状态已生成 ({len(run.plan)} 项)")
    if run.results:
        rows = [
            {
                "任务端点": result.endpoint,
                "标的": getattr(result, "symbol", "") or "全市场",
                "同步区间": f"{result.start_date} ~ {result.end_date}",
                "落盘记录数": result.records,
                "耗时(秒)": result.duration_s,
                "执行状态": result.status,
                "原因": result.error or "",
            }
            for result in run.results
        ]
        frame = pl.DataFrame(rows)
        with pl.Config(tbl_rows=100, tbl_width_chars=120, tbl_hide_dataframe_shape=True):
            logger.info(f"\n--- [{source.upper()}] 增量执行统计报告 ---\n{frame}")
    if run.audit_result:
        rate = run.audit_result.get("integrity_rate", 0.0)
        status = "PASSED" if rate >= 99.9 else "WARNING"
        logger.info(f"[质量门禁] 自动对账结果: {status} (行情完整率: {rate:.2f}%)")
    return run.has_failure


def main() -> None:
    """解析参数并调用增量同步 Facade。"""
    args = _build_parser().parse_args()
    target_date = date.fromisoformat(args.date) if args.date else date.today()
    endpoints = (
        [endpoint.strip() for endpoint in args.endpoints.split(",") if endpoint.strip()]
        if args.endpoints
        else None
    )
    logger.info(f"启动极速增量数据同步: 目标日=[{target_date}], 数据源=[{args.source}]")
    runs = run_sync(
        source=args.source,
        target_date=target_date,
        endpoints=endpoints,
        force=args.force,
        run_audit_gate=not args.no_audit,
        max_workers=args.max_workers,
        target_date_is_explicit=args.date is not None,
    )
    if any(_render_summary(run) for run in runs):
        logger.error("增量同步执行存在失败任务，请检查上述日志报告！")
        sys.exit(1)
    logger.info("增量数据同步完成，所有任务均已就绪并对齐。")


if __name__ == "__main__":
    main()
