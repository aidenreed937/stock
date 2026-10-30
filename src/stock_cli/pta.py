"""精对苯二甲酸 (PTA) 全景对账管线命令行工具 (PTA CLI)。"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, cast

from stock_analytics.pipelines.artifacts import RunClass
from stock_analytics.pipelines.pta import (
    PtaCompanyProjectionEngine,
    build_financial_context,
    run_pta_pipeline,
)
from stock_core.utils.logger import logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stock_cli.pta",
        description="PTA 全景对账: NBS 产量 + 涤纶长丝/聚酯 + 海关出口 + 郑商所仓单/基差 + 恒力/桐昆双雄 SOTP 测算，"
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
        help="将产物归档落盘至 data/analytics/pta/ (run 目录 + latest + manifest)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="自定义配置文件路径 (默认 config/analytics/pta.yaml)",
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
        help="仅输出恒力石化与桐昆股份业务分部 (SOTP) 测算与情景推演表",
    )
    parser.add_argument(
        "--scenario",
        choices=("all", "trough", "mid_cycle", "peak"),
        default="all",
        help="情景筛选 (默认 all)",
    )
    parser.add_argument(
        "--symbol",
        choices=("all", "600346.SH", "601233.SH"),
        default="all",
        help="测算标的筛选 (默认 all: 恒力石化 + 桐昆股份)",
    )
    return parser


def _render_projections_markdown(
    projections_data: list[dict[str, Any]],
    sens_df_str: str | None = None,
) -> str:
    lines = [
        "## PTA 核心双雄 (恒力石化 vs 桐昆股份) 业务分部 (SOTP) 与三情景双轨估值",
        "> 周期股估值反向时钟准则：底部净利亏损/微利时 PE 分母坍塌失效，启用 PB 资产重置底线 (PB Floor) 托底；中枢与景气高峰按盈利与 PB 双轨对账。",
        "",
        "| 标的代码 | 企业简称 | 周期情景 | 营业总收入 (亿元) | 营业毛利 (亿元) | 财务费用 (亿元) | 浙石化收益 (亿元) | 归母净利润 (亿元) | 隐含 ROE | 估值方法与锚点 | 隐含 PB | 合理市值 (亿元) |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for r in projections_data:
        sym = str(r.get("symbol", ""))
        name = str(r.get("company_name", ""))
        sc_name = str(r.get("scenario_name", ""))
        rev = float(r.get("total_revenue_cny") or 0.0) / 1e8
        gp = float(r.get("total_gross_profit_cny") or 0.0) / 1e8
        fe = float(r.get("finance_expense_cny") or 0.0) / 1e8
        inv = float(r.get("equity_investment_income_cny") or 0.0) / 1e8
        np = float(r.get("net_profit_cny") or 0.0) / 1e8
        mv = float(r.get("fair_market_value_cny") or 0.0) / 1e8
        val_method = str(r.get("valuation_method", "pe_earnings"))
        t_pb = float(r.get("target_pb") or 0.0)
        t_pe = r.get("target_pe")
        imp_pb = float(r.get("implied_pb") or 0.0)
        imp_roe = float(r.get("implied_roe") or 0.0)

        if val_method == "pb_asset_floor":
            anchor_str = f"**{t_pb:.2f}x PB (重置托底)**"
        else:
            anchor_str = f"{float(t_pe):.1f}x PE" if t_pe is not None else "--"

        lines.append(
            f"| `{sym}` | **{name}** | {sc_name} | {rev:.1f} | {gp:.1f} | {fe:.1f} | {inv:.1f} | {np:.1f} | {imp_roe:.1f}% | {anchor_str} | {imp_pb:.2f}x | **{mv:.1f}** |"
        )
    lines.append("")
    if sens_df_str:
        lines.append("### 恒力石化盈利敏感性矩阵 (PTA加工费 vs PX价格)")
        lines.append("")
        lines.append(sens_df_str)
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.project:
        config_path = (
            args.config
            if args.config is not None
            else Path("config/industry/chemicals/pta/company_projections.yaml")
        )
        engine = PtaCompanyProjectionEngine(config_path=config_path)

        symbols = ["600346.SH", "601233.SH"] if args.symbol == "all" else [args.symbol]

        all_results = []
        for sym in symbols:
            ctx = build_financial_context(sym)
            res = engine.project_all_scenarios(sym, ctx)
            if args.scenario != "all":
                res = [r for r in res if r.scenario_key == args.scenario]
            all_results.extend(res)

        rows: list[dict[str, Any]] = []
        for r in all_results:
            rows.append(
                {
                    "symbol": r.symbol,
                    "company_name": r.company_name,
                    "scenario": r.scenario_key,
                    "scenario_name": r.scenario_name,
                    "total_revenue_cny": r.total_revenue_cny,
                    "total_gross_profit_cny": r.total_gross_profit_cny,
                    "finance_expense_cny": r.finance_expense_cny,
                    "equity_investment_income_cny": r.equity_investment_income_cny,
                    "net_profit_cny": r.net_profit_cny,
                    "eps_cny": r.eps_cny,
                    "fair_market_value_cny": r.fair_market_value_cny,
                    "fair_price_cny": r.fair_price_cny,
                    "target_pe": r.target_pe,
                    "target_pb": r.target_pb,
                    "implied_pb": r.implied_pb,
                    "valuation_method": r.valuation_method,
                    "implied_roe": r.implied_roe,
                }
            )

        sens_str = None
        if "600346.SH" in symbols:
            hl_ctx = build_financial_context("600346.SH")
            sens_df = engine.generate_sensitivity_matrix(
                symbol="600346.SH",
                x_name="pta_price",
                x_values=[4500.0, 5000.0, 5500.0, 6000.0, 6500.0],
                y_name="px_price",
                y_values=[6800.0, 7200.0, 7600.0, 8000.0, 8400.0],
                base_scenario="mid_cycle",
                context=hl_ctx,
            )
            sens_str = str(sens_df)

        if args.format == "json":
            proj_payload: dict[str, Any] = {
                "projections": rows,
                "sensitivity_hengli": sens_str,
            }
            sys.stdout.write(
                json.dumps(proj_payload, ensure_ascii=False, indent=2, default=str) + "\n"
            )
        else:
            content = _render_projections_markdown(rows, sens_str)
            sys.stdout.write(content + "\n")
        return 0

    output_dir = args.output_root
    tmp_ctx: tempfile.TemporaryDirectory[str] | None = None
    if output_dir is None:
        if args.save:
            output_dir = Path("data/analytics/pta")
        else:
            tmp_ctx = tempfile.TemporaryDirectory(prefix="pta_")
            output_dir = Path(tmp_ctx.name)
    try:
        result = run_pta_pipeline(
            as_of=args.as_of_date,
            config=args.config,
            output_dir=output_dir,
            run_class=cast("RunClass", args.run_class),
            update_latest=not args.no_latest,
            storage_dir=args.storage_dir,
            build_company_fallback=not args.no_company_fallback,
        )
    except Exception as exc:
        logger.error("PTA 全景管线运行失败: %s", exc)
        sys.stderr.write(f"Error: {exc}\n")
        if tmp_ctx is not None:
            tmp_ctx.cleanup()
        sys.exit(1)

    if args.format == "json":
        payload: dict[str, Any] = {
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
