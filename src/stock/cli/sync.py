"""统一增量数据更新 CLI 入口 (stock.cli.sync)。"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from typing import Any

import polars as pl

from stock.data.sync import DailySyncEngine, SyncExecutionResult, SyncTaskItem
from stock.utils.logger import logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="一键极速增量数据同步与自愈 CLI")
    parser.add_argument(
        "-s",
        "--source",
        dest="source",
        type=str,
        default="tushare",
        help="数据源标识 (tushare / yfinance / lixinger / fred / all, 默认 tushare)",
    )
    parser.add_argument(
        "-d",
        "--date",
        dest="date",
        type=str,
        default=None,
        help="指定拟增量目标日期 (YYYY-MM-DD, 默认当日)",
    )
    parser.add_argument(
        "-e",
        "--endpoint",
        "--endpoints",
        dest="endpoints",
        type=str,
        default=None,
        help="指定增量端点列表 (逗号分隔，默认全量)",
    )
    parser.add_argument(
        "--force",
        dest="force",
        action="store_true",
        help="强制覆盖刷新 (忽略发布窗口与已有落盘水位)",
    )
    parser.add_argument(
        "--no-audit",
        dest="no_audit",
        action="store_true",
        help="增量完成后跳过自动质量对账门禁",
    )
    parser.add_argument(
        "-w",
        "--max-workers",
        dest="max_workers",
        type=int,
        default=4,
        help="最大并发工作线程数 (默认 4)",
    )
    return parser


def _render_summary(
    src: str,
    plan: list[SyncTaskItem],
    results: list[SyncExecutionResult],
    audit_res: dict[str, Any] | None,
) -> bool:
    """打印指定数据源的增量规划、执行报告及对账门禁结果。"""
    plan_rows = [
        {
            "数据源": p.data_source,
            "任务端点": p.endpoint,
            "标的": p.symbol or "全市场",
            "当前水位": str(p.watermark) if p.watermark else "无数据",
            "规划区间": f"{p.start_date} ~ {p.end_date}",
            "状态/原因": p.reason or p.status,
        }
        for p in plan
    ]
    if plan_rows:
        logger.info(f"[{src.upper()}] 增量同步规划与就绪状态已生成 ({len(plan_rows)} 项)")

    exec_failed = any(p.status == "FAILED" for p in plan)
    if results:
        exec_rows = []
        for r in results:
            if r.status in {"FAILED", "NO_DATA"}:
                exec_failed = True
            symbol = getattr(r, "symbol", "")
            exec_rows.append(
                {
                    "任务端点": r.endpoint,
                    "标的": symbol or "全市场",
                    "同步区间": f"{r.start_date} ~ {r.end_date}",
                    "落盘记录数": r.records,
                    "耗时(秒)": r.duration_s,
                    "执行状态": r.status,
                }
            )
        df_exec = pl.DataFrame(exec_rows)
        with pl.Config(tbl_rows=100, tbl_width_chars=120, tbl_hide_dataframe_shape=True):
            logger.info(f"\n--- [{src.upper()}] 增量执行统计报告 ---\n{df_exec}")

    if audit_res:
        rate = audit_res.get("integrity_rate", 0.0)
        status_text = "PASSED" if rate >= 99.9 else "WARNING"
        logger.info(f"[质量门禁] 自动对账结果: {status_text} (行情完整率: {rate:.2f}%)")

    return exec_failed


def main() -> None:
    """增量同步命令行主入口。"""
    parser = _build_parser()
    args = parser.parse_args()

    target_dt = date.fromisoformat(args.date) if args.date else date.today()
    ep_list = (
        [e.strip() for e in args.endpoints.split(",") if e.strip()] if args.endpoints else None
    )
    sources = ["tushare", "yfinance", "lixinger", "fred"] if args.source == "all" else [args.source]

    logger.info(f"启动极速增量数据同步: 目标日=[{target_dt}], 数据源=[{args.source}]")
    has_failure = False
    for src in sources:
        engine = DailySyncEngine(data_source=src, max_workers=args.max_workers)
        plan, results, audit_res = engine.sync_daily(
            target_date=target_dt,
            endpoints=ep_list,
            force=args.force,
            run_audit_gate=not args.no_audit,
            target_date_is_explicit=args.date is not None,
        )
        if _render_summary(src, plan, results, audit_res):
            has_failure = True

    if has_failure:
        logger.error("增量同步执行存在失败任务，请检查上述日志报告！")
        sys.exit(1)
    logger.info("增量数据同步完成，所有任务均已就绪并对齐。")


if __name__ == "__main__":
    main()
