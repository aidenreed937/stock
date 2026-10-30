"""钛白粉全景对账管线命令行工具 (TiO2 CLI)。"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, cast

from stock_analytics.pipelines.artifacts import RunClass
from stock_analytics.pipelines.tio2 import run_tio2_pipeline
from stock_core.utils.logger import logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stock_cli.tio2",
        description="钛白粉全景对账: GACC 海关出口 + 生意社 100ppi 现货出厂价 + 寡头门禁 + 公司面板，"
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
        help="将产物归档落盘至 data/analytics/tio2/ (run 目录 + latest + manifest)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="自定义配置文件路径 (默认 config/analytics/tio2.yaml)",
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
    parser.add_argument(
        "--project",
        "-p",
        action="store_true",
        help="仅输出龙佰集团与钛能化学业务分部 (SOTP) 测算与情景推演表",
    )
    parser.add_argument(
        "--scenario",
        choices=("all", "trough", "mid_cycle", "peak"),
        default="all",
        help="情景筛选 (默认 all)",
    )
    parser.add_argument(
        "--no-dynamic-financials",
        action="store_true",
        help="强制禁用动态财报事实装配，使用 YAML 静态兜底配置",
    )
    parser.add_argument(
        "--cost-lag-days",
        type=int,
        default=0,
        help="原材料采购入库与先进先出(FIFO)成本结转时滞天数(默认0天为边际即时现货)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.project:
        from stock_analytics.pipelines.tio2.projections import CompanyProjectionEngine
        from stock_analytics.pipelines.tio2.report import _render_projections_section
        from stock_data.catalog import DataCatalog

        cat = None
        if not args.no_dynamic_financials:
            try:
                cat = DataCatalog(data_source="tushare", storage_dir=args.storage_dir)
            except Exception as e:
                logger.debug(f"无法初始化 DataCatalog，使用静态配置: {e}")

        engine = CompanyProjectionEngine(
            config_path=args.config,
            catalog=cat,
            cost_lag_days=args.cost_lag_days,
        )
        results = engine.project_all()
        if args.scenario != "all":
            results = [r for r in results if r.scenario_key == args.scenario]
        lb_grid = engine.generate_profit_sensitivity_grid("002601.SZ")
        zh_grid = engine.generate_profit_sensitivity_grid("002145.SZ")

        if args.format == "json":
            df = engine.to_dataframe(results)
            proj_payload: dict[str, Any] = {
                "projections": df.to_dicts(),
                "lb_sensitivity": lb_grid.to_dicts(),
                "zh_sensitivity": zh_grid.to_dicts(),
            }
            sys.stdout.write(
                json.dumps(proj_payload, ensure_ascii=False, indent=2, default=str) + "\n"
            )
        else:
            content = _render_projections_section(results, lb_grid, zh_grid)
            sys.stdout.write(content + "\n")
        return 0

    output_dir = args.output_root
    tmp_ctx: tempfile.TemporaryDirectory[str] | None = None
    if output_dir is None:
        if args.save:
            output_dir = Path("data/analytics/tio2")
        else:
            tmp_ctx = tempfile.TemporaryDirectory(prefix="tio2_")
            output_dir = Path(tmp_ctx.name)
    try:
        result = run_tio2_pipeline(
            as_of=args.as_of_date,
            config=args.config,
            output_dir=output_dir,
            run_class=cast("RunClass", args.run_class),
            update_latest=not args.no_latest,
            storage_dir=args.storage_dir,
            build_company_fallback=not args.no_company_fallback,
        )
    except Exception as exc:
        logger.error("钛白粉全景管线运行失败: %s", exc)
        sys.stderr.write(f"Error: {exc}\n")
        if tmp_ctx is not None:
            tmp_ctx.cleanup()
        return 1

    if args.format == "json":
        payload: dict[str, Any] = {
            "as_of_date": str(result.as_of_date),
            "run_dir": str(result.paths.run_dir),
            "latest_dir": str(result.paths.latest_dir),
            "panorama": (
                result.panorama.tail(12).to_dicts() if not result.panorama.is_empty() else []
            ),
            "quarterly_projections": (
                result.quarterly_projections.to_dicts()
                if result.quarterly_projections is not None
                and not result.quarterly_projections.is_empty()
                else []
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
