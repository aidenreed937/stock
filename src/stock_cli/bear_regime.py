"""熊市区间识别管线 CLI 入口（可重复运行，产物经 ArtifactStore 落盘）。

用法:
    uv run python -m stock_cli.bear_regime                  # 最新交易日
    uv run python -m stock_cli.bear_regime --as-of 2024-09-23
    uv run python -m stock_cli.bear_regime --output-dir data/analytics/bear_regime
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from stock_analytics.pipelines.bear_regime import BearRegimePipeline
from stock_core.utils.logger import logger, setup_logger


def _parse_date(v: str | None) -> date | None:
    return date.fromisoformat(v) if v else None


def main() -> None:
    parser = argparse.ArgumentParser(description="运行双引擎熊市区间识别管线。")
    parser.add_argument("--config", type=str, default="config/analytics/bear_regime.yaml")
    parser.add_argument(
        "--nav-csv", type=str, default="data/analytics/macro_strategy/multi_strategy_nav.csv"
    )
    parser.add_argument("--risk-root", type=str, default="data/analytics/macro_risk")
    parser.add_argument("--output-dir", type=str, default="data/analytics/bear_regime")
    parser.add_argument("--as-of", type=_parse_date, default=None, help="基准日期 YYYY-MM-DD")
    parser.add_argument("--no-publish-latest", action="store_true", help="不更新 latest 视图")
    parser.add_argument(
        "--run-class", type=str, default="official", choices=["official", "backfill", "experiment"]
    )
    args = parser.parse_args()
    setup_logger()

    pipeline = BearRegimePipeline(config_path=args.config)
    try:
        result = pipeline.run(
            as_of=args.as_of,
            nav_csv=args.nav_csv,
            risk_root=args.risk_root,
            output_dir=args.output_dir,
            update_latest=not args.no_publish_latest,
            run_class=args.run_class,
        )
    except Exception as exc:
        logger.exception("熊市识别管线运行失败: %s", exc)
        sys.exit(1)

    if result.empty:
        print("未识别出熊市区间（当前阈值下无触发）。")
        return
    print(f"识别完成，共 {result['熊市区间'].nunique()} 个熊市区间：")
    for eng in result["识别引擎"].unique():
        segs = result[result["识别引擎"] == eng]["熊市区间"].unique()
        print(f"  [{eng}] {', '.join(segs)}")
    print(f"产物落盘: {args.output_dir}")


if __name__ == "__main__":
    main()
