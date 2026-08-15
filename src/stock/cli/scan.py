"""A 股全市场量化全景体检与扫描 CLI (stock.cli.scan)。

架构特性:
    1. 领域引擎驱动: 由 MarketScanEngine 负责全流程量化计算、分位数评估与研判合成；
    2. 数据与报告物化解耦: 产物按日组织在 reports/scan/{YYYY-MM-DD}/ 目录下；
    3. 支持缓存复用与强制重算: 修改报告仅需毫秒级重绘，无需重复跑库计算。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from stock.analytics.engine import MarketScanEngine
from stock.cli.scan_report import (
    format_console_report,
    format_investor_report,
    format_pro_report,
)
from stock.data.catalog import DataCatalog
from stock.utils.logger import logger

if TYPE_CHECKING:
    from stock.analytics.models import DailyMarketScanSummary


def _build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        description="A 股量化宏观/中观/微观全景体检与扫描 CLI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-d",
        "--date",
        dest="target_date",
        type=str,
        default=None,
        help="指定体检分析基准日期 (YYYY-MM-DD, 默认最新落盘交易日)",
    )
    parser.add_argument(
        "-s",
        "--symbol",
        dest="symbol",
        type=str,
        default="000300",
        help="宏观股债收益比基准指数代码 (默认 000300 沪深300)",
    )
    parser.add_argument(
        "-f",
        "--format",
        dest="format",
        choices=["investor", "console", "pro", "json"],
        default="investor",
        help="输出格式 (investor: 投资者通俗版, console: 终端卡片, pro: 专业版, json: 纯JSON)",
    )
    parser.add_argument(
        "-r",
        "--recompute",
        dest="recompute",
        action="store_true",
        help="强制重新计算底层各维度量化指标并刷新 data.json (忽略已物化缓存)",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="output",
        type=str,
        default=None,
        help="将体检报告保存至指定文件路径",
    )
    parser.add_argument(
        "--save",
        dest="auto_save",
        action="store_true",
        help="自动在 reports/scan/{YYYY-MM-DD}/ 目录下保存 data.json, report.md 与 report_pro.md",
    )
    return parser


def run_market_scan(
    target_date: date | None = None,
    symbol: str = "000300",
    *,
    recompute: bool = False,
    engine: MarketScanEngine | None = None,
) -> DailyMarketScanSummary:
    """执行全流程三层量化体检并返回强类型 DailyMarketScanSummary 聚合根。"""
    scan_engine = engine or MarketScanEngine()

    if target_date is None:
        try:
            cat = DataCatalog(data_source="tushare")
            df_basic = cat.load_dataset("daily_basic")
            if not df_basic.is_empty():
                max_d = df_basic["trade_date"].max()
                target_date = max_d if isinstance(max_d, date) else date.fromisoformat(str(max_d))
        except Exception as e:
            logger.debug("自动解析全市场最新基准日失败，将交由各分析器按需降级: %s", e)

    summary, is_cache = scan_engine.get_or_compute(
        target_date=target_date,
        index_symbol=symbol,
        recompute=recompute,
    )
    if is_cache:
        logger.info(
            "⚡ 命中本地已物化数据: reports/scan/%s/data.json (秒级加载)", summary.trade_date
        )
    return summary


def _save_scan_artifacts(
    summary: DailyMarketScanSummary,
    output_text: str,
    args: argparse.Namespace,
    engine: MarketScanEngine,
) -> None:
    """按日目录保存数据与报告产物。"""
    dt_str = summary.trade_date.strftime("%Y-%m-%d")
    target_dir = Path("reports/scan") / dt_str

    if args.auto_save:
        target_dir.mkdir(parents=True, exist_ok=True)
        # 1. 保存强类型数据文件 data.json
        engine.save_data(summary, base_dir="reports/scan")

        # 2. 保存投资者通俗版报告 report.md 与专业版报告 report_pro.md
        report_path = target_dir / "report.md"
        report_pro_path = target_dir / "report_pro.md"
        report_path.write_text(format_investor_report(summary), encoding="utf-8")
        report_pro_path.write_text(format_pro_report(summary), encoding="utf-8")

        logger.info("体检产物已归档至目录: %s", target_dir.resolve())

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_text, encoding="utf-8")
        logger.info("体检报告已保存至: %s", out_path.resolve())


def main() -> None:
    """CLI 主入口。"""
    parser = _build_parser()
    args = parser.parse_args()

    target_d = None
    if args.target_date:
        try:
            target_d = date.fromisoformat(args.target_date)
        except ValueError:
            logger.error("日期格式错误，请使用 YYYY-MM-DD 格式: %s", args.target_date)
            sys.exit(1)

    engine = MarketScanEngine()
    logger.info(
        "开始执行三层量化扫描 (日期: %s, 标的: %s, 强制重算: %s)...",
        target_d or "最新",
        args.symbol,
        args.recompute,
    )
    try:
        summary = run_market_scan(
            target_date=target_d,
            symbol=args.symbol,
            recompute=args.recompute,
            engine=engine,
        )
    except Exception as e:
        logger.exception("量化全景扫描执行失败: %s", e)
        sys.exit(1)

    if args.format == "pro":
        output_text = format_pro_report(summary)
    elif args.format == "json":
        output_text = summary.model_dump_json(indent=2)
    elif args.format == "console":
        output_text = format_console_report(summary)
    else:
        output_text = format_investor_report(summary)

    sys.stdout.write(output_text + "\n")
    _save_scan_artifacts(summary, output_text, args, engine)


if __name__ == "__main__":
    main()
