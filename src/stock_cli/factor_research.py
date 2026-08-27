"""因子准入评估 CLI。"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from stock_analytics.pipelines.factor_research import (
    DEFAULT_CONFIG_PATH,
    run_factor_research,
)
from stock_core.utils.logger import logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="对注册 STOCK 宽表因子执行质量检验并产出因子准入报告",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--end-date",
        dest="end_date",
        default=None,
        help="评估窗口截止日期 (YYYY-MM-DD, 默认今天)",
    )
    parser.add_argument(
        "-c",
        "--config",
        dest="config_path",
        default=str(DEFAULT_CONFIG_PATH),
        help="因子准入评估 YAML 配置路径",
    )
    parser.add_argument(
        "-o",
        "--output-root",
        dest="output_root",
        default=None,
        help="覆盖产物根目录",
    )
    parser.add_argument(
        "--storage-dir",
        default=None,
        help="Curated 数据根目录",
    )
    parser.add_argument(
        "--run-class",
        choices=("official", "backfill", "experiment"),
        default="official",
        help="产物运行分类",
    )
    parser.add_argument(
        "--no-latest",
        dest="update_latest",
        action="store_false",
        help="不刷新 data/analytics/factor_research/latest/",
    )
    return parser


def main() -> None:
    """CLI 主入口。"""
    parser = _build_parser()
    args = parser.parse_args()
    try:
        result = run_factor_research(
            end_date=_parse_date(args.end_date),
            config_path=Path(args.config_path),
            output_root=args.output_root,
            storage_dir=args.storage_dir,
            run_class=args.run_class,
            update_latest=bool(args.update_latest),
        )
    except Exception as exc:
        logger.exception("因子准入评估失败: {}", exc)
        sys.exit(1)
    sys.stdout.write(result.report_markdown)
    logger.info("因子准入评估产物已写入: {}", result.paths.run_dir.resolve())


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise SystemExit(f"无效日期格式: {value}（应为 YYYY-MM-DD）") from None


if __name__ == "__main__":
    main()
