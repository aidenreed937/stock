"""市场分析上下文查询 CLI。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from stock_analytics.pipelines.market_temperature import (
    DEFAULT_ARTIFACT_ROOT,
    MarketAnalysisContext,
    rebuild_history_index,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stock_cli.market_context",
        description="读取市场温度快照并返回面向分析问答的紧凑 JSON",
    )
    parser.add_argument(
        "--as-of",
        default="latest",
        help="观测日或 latest",
    )
    parser.add_argument("--run-id", default=None, help="指定运行 ID")
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=DEFAULT_ARTIFACT_ROOT,
        help="市场温度分析产物根目录",
    )
    parser.add_argument(
        "--questions",
        default="overview",
        help="逗号分隔的问题类型：overview,trend,risk,history-extremes,explain-date",
    )
    parser.add_argument("--compare-date", default=None, help="explain-date 的对比日期")
    parser.add_argument(
        "--rebuild-history",
        action="store_true",
        help="先从已有运行快照重建历史索引",
    )
    parser.add_argument("--format", choices=("json",), default="json")
    return parser


def main() -> None:
    """CLI 主入口。"""
    args = _build_parser().parse_args()
    try:
        artifact_root = Path(args.artifact_root)
        if args.rebuild_history:
            rebuild_history_index(artifact_root)
        context = MarketAnalysisContext.load(
            artifact_root,
            as_of=args.as_of,
            run_id=args.run_id,
        )
        result = context.query(
            _parse_questions(args.questions),
            compare_date=_parse_date(args.compare_date),
        )
    except (FileNotFoundError, ValueError) as exc:
        sys.stderr.write(f"Error: {exc}\n")
        raise SystemExit(1) from exc
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n")


def _parse_questions(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


if __name__ == "__main__":
    main()
