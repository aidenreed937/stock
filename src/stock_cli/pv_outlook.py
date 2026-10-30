"""光伏景气前瞻仪表盘命令行工具 (PV Outlook CLI)。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from stock_analytics.pipelines.pv_outlook import run_pv_outlook
from stock_core.utils.logger import logger
from stock_data.core.runtime import DataRuntimeContext


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stock_cli.pv_outlook",
        description="光伏景气前瞻仪表盘: 周度价格链价差 + 月度装机/库存/供需水位 + 数据缺口矩阵 + 外部核验事实",
    )
    parser.add_argument(
        "--as-of",
        "-d",
        dest="as_of_date",
        type=lambda s: date.fromisoformat(s),
        default=None,
        help="基准日期 (YYYY-MM-DD，默认为最新交易日)",
    )
    parser.add_argument(
        "--format",
        "-f",
        dest="output_format",
        choices=["markdown", "json"],
        default="markdown",
        help="输出格式: markdown (人类可读报告) 或 json (结构化快照)",
    )
    parser.add_argument(
        "--save",
        "-s",
        action="store_true",
        help="将产物归档落盘至 data/analytics/pv_outlook/ (run 目录 + latest + manifest)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="自定义配置文件路径 (默认 config/analytics/pv_outlook.yaml)",
    )
    parser.add_argument(
        "--storage-dir",
        type=Path,
        default=None,
        help="自定义数据根目录 (默认使用项目内置 data/)",
    )
    parser.add_argument(
        "--no-latest",
        action="store_true",
        help="落盘时不同步更新 latest 目录",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    output_dir = Path("data/analytics/pv_outlook") if args.save else None
    runtime = DataRuntimeContext.from_root(args.storage_dir) if args.storage_dir else None
    try:
        result = run_pv_outlook(
            as_of=args.as_of_date,
            output_dir=output_dir,
            update_latest=not args.no_latest,
            config=args.config,
            runtime=runtime,
        )
    except Exception as exc:
        logger.error(f"光伏前瞻仪表盘运行失败: {exc}")
        sys.stderr.write(f"Error: {exc}\n")
        sys.exit(1)

    if args.output_format == "json":
        payload = {
            "as_of_date": str(result.as_of_date),
            "outlook_stage": result.manifest.get("outlook_stage"),
            "gap_summary": result.manifest.get("gap_summary"),
            "readings": result.snapshot.to_dicts(),
            "gap_matrix": result.gap_matrix.to_dicts(),
        }
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(result.report_markdown + "\n")


if __name__ == "__main__":
    main()
