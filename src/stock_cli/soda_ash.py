"""纯碱全景对账管线命令行工具 (Soda Ash CLI)。"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import cast

from stock_analytics.pipelines.artifacts import RunClass
from stock_analytics.pipelines.soda_ash import run_soda_ash_pipeline
from stock_core.utils.logger import logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stock_cli.soda_ash",
        description="纯碱全景对账: NBS 产量 + 海关出口 + 郑商所仓单/龙虎榜 + 厂库/价差 + 公司面板，"
        "产出全景事实表与数据驱动研报（ArtifactStore + manifest）",
    )
    parser.add_argument(
        "--as-of",
        "-d",
        dest="as_of_date",
        type=lambda s: date.fromisoformat(s),
        default=None,
        help="基准日期 (YYYY-MM-DD，默认为最新报告月首日)",
    )
    parser.add_argument(
        "--save",
        "-s",
        action="store_true",
        help="将产物归档落盘至 data/analytics/soda_ash/ (run 目录 + latest + manifest)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="自定义配置文件路径 (默认 config/analytics/soda_ash.yaml)",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="产物输出根目录覆盖（默认取配置 artifact_root）",
    )
    parser.add_argument(
        "--run-class",
        choices=("official", "backfill", "experiment"),
        default="official",
        help="运行分类（默认 official）",
    )
    parser.add_argument(
        "--no-latest",
        action="store_true",
        help="落盘时不同步更新 latest 目录",
    )
    parser.add_argument(
        "--storage-dir",
        type=Path,
        default=None,
        help="自定义数据根目录 (默认使用项目内置 data/)",
    )
    parser.add_argument(
        "--no-company-fallback",
        action="store_true",
        help="公司面板 Mart 缺失时不触发回退构建",
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=("markdown", "json"),
        default="markdown",
        help="输出格式: markdown (研报) 或 json (结构化摘要)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    output_dir = args.output_root
    tmp_ctx: tempfile.TemporaryDirectory[str] | None = None
    if output_dir is None:
        if args.save:
            output_dir = Path("data/analytics/soda_ash")
        else:
            tmp_ctx = tempfile.TemporaryDirectory(prefix="soda_ash_")
            output_dir = Path(tmp_ctx.name)
    try:
        result = run_soda_ash_pipeline(
            as_of=args.as_of_date,
            config_path=args.config,
            output_dir=output_dir,
            run_class=cast("RunClass", args.run_class),
            update_latest=not args.no_latest,
            storage_dir=args.storage_dir,
            build_company_fallback=not args.no_company_fallback,
        )
    except Exception as exc:
        logger.error("纯碱全景管线运行失败: %s", exc)
        sys.stderr.write(f"Error: {exc}\n")
        if tmp_ctx is not None:
            tmp_ctx.cleanup()
        return 1

    if args.format == "json":
        payload = {
            "as_of_date": str(result.as_of_date),
            "run_dir": str(result.paths.run_dir),
            "latest_dir": str(result.paths.latest_dir),
            "panorama": (
                result.panorama.tail(12).to_dicts() if not result.panorama.is_empty() else []
            ),
            "manifest": result.manifest,
        }
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n")
    else:
        sys.stdout.write(result.report_markdown + "\n")

    if tmp_ctx is not None:
        tmp_ctx.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
