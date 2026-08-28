"""宏观系统性风险 CLI 入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from stock_analytics.pipelines.macro_risk import MacroRiskPipeline
from stock_core.utils.logger import logger, setup_logger


def main() -> None:
    parser = argparse.ArgumentParser(description="生成全市场系统性风险双轨制雷达指数。")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/analytics/macro_risk",
        help="产物输出目录",
    )
    args = parser.parse_args()
    setup_logger()

    out_dir = Path(args.output_dir)
    pipeline = MacroRiskPipeline()

    try:
        pipeline.run(output_dir=out_dir)
    except Exception as exc:
        logger.exception(f"系统性风险管线运行失败: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
