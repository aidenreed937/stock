"""CLI 入口：宏观风控多策略跨周期稳定性审计。

用法:
    uv run python -m stock_cli.macro_strategy_audit
    uv run python -m stock_cli.macro_strategy_audit --assert-guardrails
    uv run python -m stock_cli.macro_strategy_audit --output-dir data/analytics/macro_strategy/audit
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from stock_core.utils.logger import logger
from stock_strategy.macro.audit import (
    assert_stability_guardrails,
    run_full_stability_audit,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="宏观风控多策略跨周期稳定性审计工具 (6大范式 + 4大危机压力测试 + 滚动窗口)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config/strategy/macro_risk.yaml",
        help="策略配置文件路径 (默认: config/strategy/macro_risk.yaml)",
    )
    parser.add_argument(
        "--risk-root",
        type=str,
        default="data/analytics/macro_risk",
        help="宏观风险产物根目录 (默认: data/analytics/macro_risk)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/analytics/macro_strategy/audit",
        help="审计产物输出目录 (默认: data/analytics/macro_strategy/audit)",
    )
    parser.add_argument(
        "--data-source",
        type=str,
        default="tushare",
        help="数据源 (默认: tushare)",
    )
    parser.add_argument(
        "--assert-guardrails",
        action="store_true",
        help="运行 CI 策略防退化回归门禁断言，若核心指标退化则以非 0 退出",
    )
    parser.add_argument(
        "--walk-forward",
        action="store_true",
        help="运行 Walk-Forward 滚动 3Y 样本内 -> 1Y 样本外检验",
    )
    parser.add_argument(
        "--no-charts",
        action="store_true",
        help="跳过 Matplotlib 图表生成",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_file():
        logger.error("配置文件不存在: %s", config_path)
        sys.exit(1)

    print(f"正在启动多策略跨周期稳定性审计 (配置: {config_path})...")
    try:
        result = run_full_stability_audit(
            config_path=config_path,
            risk_root=args.risk_root,
            output_dir=args.output_dir,
            data_source=args.data_source,
            generate_charts=not args.no_charts,
        )
    except Exception as exc:
        logger.error("稳定性审计失败: %s", exc)
        sys.exit(1)

    print(f"\n✅ 稳定性审计完成！产物已输出至: {args.output_dir}")
    print(f"  - 完整审计研报: {result.report_path}")
    if result.chart_path:
        print(f"  - 4合1对比图表: {result.chart_path}")
    print(f"  - 范式对账 CSV: {Path(args.output_dir) / 'regime_comparison.csv'}")
    print(f"  - 压力测试 CSV: {Path(args.output_dir) / 'stress_test_comparison.csv'}")
    print(f"  - 滚动统计 CSV: {Path(args.output_dir) / 'rolling_stability_stats.csv'}")

    if args.walk_forward:
        print("\n正在执行 Walk-Forward 滚动样本外 (OOS) 检验...")
        from stock_data.catalog import DataCatalog
        from stock_strategy.macro.assembly import assemble_macro_panel, load_price_panel
        from stock_strategy.macro.report import load_all_strategy_specs
        from stock_strategy.macro.walk_forward import (
            render_walk_forward_markdown,
            run_walk_forward_analysis,
        )

        catalog = DataCatalog(data_source=args.data_source)
        macro_panel = assemble_macro_panel(
            catalog=catalog,
            benchmark_symbol="000985.CSI",
            risk_root=Path(args.risk_root),
        )
        specs = load_all_strategy_specs(config_path)

        all_syms: set[str] = set()
        for spec in specs.values():
            all_syms.update(spec.get("symbols", []))
        price_panel = load_price_panel(catalog=catalog, symbols=sorted(all_syms))

        wf_results = []
        for name, spec in specs.items():
            wf_res = run_walk_forward_analysis(
                strategy_name=name,
                strategy_spec=spec,
                macro_panel=macro_panel,
                price_panel=price_panel,
                train_years=3,
                test_years=1,
            )
            if wf_res is not None:
                wf_results.append(wf_res)

        if wf_results:
            wf_md = render_walk_forward_markdown(wf_results)
            print("\n" + wf_md)
            wf_path = Path(args.output_dir) / "walk_forward_report.md"
            wf_path.write_text(wf_md, encoding="utf-8")
            print(f"  - Walk-Forward 研报已落盘: {wf_path}")

    if args.assert_guardrails:
        print("\n正在执行策略防退化回归门禁断言 (CI Guardrails)...")
        try:
            assert_stability_guardrails(result)
            print("  ✅ 所有稳定性回归断言全部通过 (V4 3Y胜率 >= 80%, V6 2024踩踏回撤 >= -10%)！")
        except AssertionError as err:
            logger.error("❌ 策略稳定性门禁断言失败: %s", err)
            sys.exit(1)


if __name__ == "__main__":
    main()
