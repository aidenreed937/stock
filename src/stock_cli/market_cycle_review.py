"""市场跨周期复盘 CLI 薄入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from stock_analytics.pipelines.market_cycle_review import run_market_cycle_review


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成市场跨周期复盘产物")
    parser.add_argument("--start", required=True, help="起始基准日 YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="结束基准日 YYYY-MM-DD")
    parser.add_argument("--analytics-root", default="data/analytics", help="分析产物根目录")
    parser.add_argument(
        "--output-root",
        default="data/analytics/market_cycle_review",
        help="跨周期复盘产物根目录",
    )
    parser.add_argument("--skip-consistency", action="store_true", help="跳过一致性校验")
    parser.add_argument("--no-latest", action="store_true", help="不刷新 latest")
    return parser


def main(argv: list[str] | None = None) -> int:
    """解析参数并调用市场跨周期复盘管线。"""
    args = _build_parser().parse_args(argv)
    try:
        result = run_market_cycle_review(
            start=args.start,
            end=args.end,
            analytics_root=Path(args.analytics_root),
            output_root=Path(args.output_root),
            skip_consistency=args.skip_consistency,
            update_latest=not args.no_latest,
        )
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
        print(f"market_cycle_review 失败: {error}", file=sys.stderr)
        return 1
    print(f"market_cycle_review: passed dates={len(result.dates)}")
    print(f"json: {result.paths['json']}")
    print(f"markdown: {result.paths['markdown']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
