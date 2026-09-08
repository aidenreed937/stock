"""公司层出口交易信号管线 CLI（customs_company）。

一键执行：公司观察表（暴露度×税号段）→ 三层信号评级（出口×资金×财报），
产物落 ``data/analytics/industry/customs_company_*``。
"""

from __future__ import annotations

import argparse
import sys

from stock_analytics.pipelines.customs_company import run_customs_company_pipeline
from stock_core.utils.logger import logger, setup_logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stock_cli.customs_company",
        description="公司层出口交易信号管线: 公司观察表 → 三层信号评级 (月度抓机会)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default="config/analytics/customs_company.yaml",
        help="管线配置文件路径",
    )
    parser.add_argument(
        "--output-dir",
        dest="artifact_root",
        default=None,
        help="产物输出目录覆盖 (默认取配置 artifact_root)",
    )
    parser.add_argument(
        "--skip-signal",
        action="store_true",
        help="跳过三层信号合成 (仅公司观察表)",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    setup_logger()

    try:
        outputs = run_customs_company_pipeline(
            config_path=args.config_path,
            artifact_root=args.artifact_root,
            build_signal=not args.skip_signal,
        )
    except (ValueError, OSError) as exc:
        logger.error("公司层出口交易信号管线执行失败: %s", exc)
        sys.exit(1)

    print("已生成产物:")
    for step, path in outputs.items():
        print(f"  {step}: {path}")


if __name__ == "__main__":
    main()
