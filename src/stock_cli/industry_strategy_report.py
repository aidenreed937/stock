"""申万行业多策略对比报告 CLI 入口。"""

from __future__ import annotations

import argparse

from stock_core.utils.logger import setup_logger
from stock_strategy.industry.report import build_multi_industry_comparison_report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="生成申万行业多策略 (动量/逆向/剪刀差/元路由) 与基准的资金曲线对比报告。"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/analytics/industry_strategy",
        help="报告产物输出目录",
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
        "--config",
        type=str,
        default="config/strategy/industry_rotation.yaml",
        help="策略配置文件路径",
    )
    args = parser.parse_args()
    setup_logger()

    result = build_multi_industry_comparison_report(
        output_dir=args.output_dir,
        factor_root=args.factor_root,
        macro_risk_root=args.macro_risk_root,
        config_path=args.config,
    )
    print(f"Markdown: {result['markdown']}")
    print(f"资金曲线图: {result['png']}")
    print(f"净值 CSV: {result['csv']}")


if __name__ == "__main__":
    main()
