"""市场温度计 CLI。"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from stock_analytics.pipelines.market_temperature import run_market_temperature
from stock_core.utils.logger import logger
from stock_reporting.interpretation.market_temperature.config import DEFAULT_CONFIG_PATH


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="生成 A 股六维市场温度计 facts/scores/report 产物",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-d",
        "--date",
        dest="target_date",
        default=None,
        help="指定分析基准日期 (YYYY-MM-DD, 默认最新落盘交易日)",
    )
    parser.add_argument(
        "-c",
        "--config",
        dest="config_path",
        default=str(DEFAULT_CONFIG_PATH),
        help="市场温度计 YAML 配置路径",
    )
    parser.add_argument(
        "--compare-date",
        dest="comparison_date",
        default=None,
        help="指定前期基准日期，读取该日期已落盘产物并在人读报告中加入跨期驱动变化表",
    )
    parser.add_argument(
        "-o",
        "--output-root",
        dest="output_root",
        default=None,
        help="覆盖产物根目录",
    )
    parser.add_argument(
        "--no-latest",
        dest="update_latest",
        action="store_false",
        help="不刷新 data/analytics/market_temperature/latest",
    )
    parser.add_argument(
        "--skip-metrics",
        dest="collect_metric_values",
        action="store_false",
        default=None,
        help="只采集窗口与数据水位，不运行 MetricEngine 指标",
    )
    return parser


def main() -> None:
    """CLI 主入口。"""
    parser = _build_parser()
    args = parser.parse_args()
    target_date = _parse_date(args.target_date)
    comparison_date = _parse_date(args.comparison_date)
    try:
        result = run_market_temperature(
            target_date=target_date,
            comparison_date=comparison_date,
            config_path=Path(args.config_path),
            output_root=args.output_root,
            update_latest=bool(args.update_latest),
            collect_metric_values=args.collect_metric_values,
        )
    except Exception as exc:
        logger.exception("市场温度计生成失败: {}", exc)
        sys.exit(1)
    sys.stdout.write(result.report_markdown)
    logger.info("市场温度计产物已写入: {}", result.paths.run_dir.resolve())


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        logger.error("日期格式错误，请使用 YYYY-MM-DD: {}", value)
        sys.exit(1)


if __name__ == "__main__":
    main()
