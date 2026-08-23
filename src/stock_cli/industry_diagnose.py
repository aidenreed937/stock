"""中观产业量化诊断命令行工具 (Industry Diagnostics CLI)。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from stock_analytics.pipelines.industry_diagnostics.pipeline import (
    run_industry_diagnostics,
)
from stock_core.utils.logger import logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stock_cli.industry_diagnose",
        description="中观产业量化诊断 CLI: 一键聚合申万行业行情、PE/PB 估值分位、成份股龙头梯队与产业链图谱",
    )
    parser.add_argument(
        "--industry",
        "-i",
        required=True,
        type=str,
        help="行业名称或代码 (如: 食品饮料, 白酒, 电力设备, 801120.SI)",
    )
    parser.add_argument(
        "--as-of",
        "-d",
        dest="as_of_date",
        type=lambda s: date.fromisoformat(s),
        default=None,
        help="诊断基准日期 (YYYY-MM-DD，默认为最新交易日)",
    )
    parser.add_argument(
        "--format",
        "-f",
        dest="output_format",
        choices=["json", "markdown"],
        default="markdown",
        help="输出格式: markdown (人类友好研报) 或 json (LLM 低 Token 结构化)",
    )
    parser.add_argument(
        "--save",
        "-s",
        action="store_true",
        help="是否将诊断产物归档落盘至 data/analytics/industry_diagnostics/ 目录",
    )
    parser.add_argument(
        "--storage-dir",
        type=Path,
        default=None,
        help="自定义数据根目录 (默认使用项目内置 data/)",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        result = run_industry_diagnostics(
            industry=args.industry,
            target_date=args.as_of_date,
            storage_dir=args.storage_dir,
        )
    except Exception as exc:
        logger.error(f"行业诊断失败: {exc}")
        sys.stderr.write(f"Error: {exc}\n")
        sys.exit(1)

    # 1. 命令行输出
    if args.output_format == "json":
        sys.stdout.write(json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(result.to_markdown() + "\n")

    # 2. 可选落盘归档
    if args.save:
        base_dir = args.storage_dir or Path("data")
        save_dir = (
            base_dir / "analytics" / "industry_diagnostics" / "runs" / f"as_of={result.as_of_date}"
        )
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = save_dir / f"{result.industry_code}.json"
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info(f"行业诊断产物已保存至: {save_path}")


if __name__ == "__main__":
    main()
