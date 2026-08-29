"""申万行业多策略跨周期稳定性审计 CLI 入口。"""

from __future__ import annotations

import argparse
import sys

from stock_core.utils.logger import logger, setup_logger
from stock_strategy.industry.audit import run_industry_strategy_audit


def main() -> None:
    parser = argparse.ArgumentParser(
        description="执行申万行业策略 6 大宏观范式分段回溯、4 大危机压力测试与滚动持有期稳定性审计。"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/analytics/industry_strategy/audit",
        help="审计产物输出目录",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config/strategy/industry_rotation.yaml",
        help="策略配置文件路径",
    )
    parser.add_argument(
        "--factor-root",
        type=str,
        default="data/analytics/industry_structure",
        help="行业因子产物根目录",
    )
    parser.add_argument(
        "--macro-risk-root",
        type=str,
        default="data/analytics/macro_risk",
        help="宏观风险产物根目录",
    )
    parser.add_argument(
        "--assert-guardrails",
        action="store_true",
        help="断言所有跨周期稳定性与最大回撤门禁均通过 (CI 自动化阻断)",
    )
    args = parser.parse_args()
    setup_logger()

    try:
        res = run_industry_strategy_audit(
            config_path=args.config,
            factor_root=args.factor_root,
            macro_risk_root=args.macro_risk_root,
            output_dir=args.output_dir,
            assert_guardrails=args.assert_guardrails,
        )
        print(f"审计报告 Markdown: {res['report_markdown']}")
        print(f"审计图表 PNG: {res['chart_png']}")
        print("\n--- 门禁结果汇总 ---")
        for g in res["guardrails"]:
            tag = "✅ PASS" if g["passed"] else "❌ FAIL"
            print(f"  [{tag}] {g['metric']}: 要求 {g['threshold']}, 实际 {g['actual']}")
    except Exception as exc:
        logger.error(f"审计运行失败: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
