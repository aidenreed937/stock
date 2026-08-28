"""宏观风控多策略对比报告 CLI 入口。"""

from __future__ import annotations

import argparse

from stock_core.utils.logger import setup_logger
from stock_strategy.macro_report import build_multi_strategy_comparison_report


def main() -> None:
    parser = argparse.ArgumentParser(description="生成多策略 (V3/V4/V5) 与基准的资金曲线对比报告。")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/analytics/macro_strategy",
        help="报告产物输出目录",
    )
    parser.add_argument(
        "--risk-root",
        type=str,
        default="data/analytics/macro_risk",
        help="宏观风险产物根目录",
    )
    args = parser.parse_args()
    setup_logger()

    result = build_multi_strategy_comparison_report(
        output_dir=args.output_dir,
        risk_root=args.risk_root,
    )
    print(f"Markdown: {result['markdown']}")
    print(f"资金曲线图: {result['png']}")
    print(f"净值 CSV: {result['csv']}")


if __name__ == "__main__":
    main()
