"""分析报告一致性校验 CLI 薄入口。"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from stock_analytics.pipelines.report_consistency import ConsistencyValidator, ValidationResult


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="校验分析报告与上游事实/规则的一致性")
    parser.add_argument("--analytics-root", default="data/analytics", help="分析产物根目录")
    parser.add_argument("--date", help="只校验指定基准日 YYYY-MM-DD")
    parser.add_argument("--start", help="批量校验起始基准日 YYYY-MM-DD")
    parser.add_argument("--end", help="批量校验结束基准日 YYYY-MM-DD")
    parser.add_argument("--output", help="可选 JSON 校验报告输出路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    """解析参数并执行一致性校验。"""
    args = _build_parser().parse_args(argv)
    validator = ConsistencyValidator(Path(args.analytics_root))
    dates = _target_dates(args, validator)
    result = validator.validate_dates(dates) if dates is not None else validator.validate_latest()
    _print_result(result)
    _write_output(result, args.output)
    return 0 if result.status == "passed" else 1


def _target_dates(
    args: argparse.Namespace,
    validator: ConsistencyValidator,
) -> list[str] | None:
    if args.date:
        return [date.fromisoformat(args.date).isoformat()]
    if args.start or args.end:
        start = date.fromisoformat(args.start).isoformat() if args.start else None
        end = date.fromisoformat(args.end).isoformat() if args.end else None
        return validator.available_dates(start, end)
    return None


def _print_result(result: ValidationResult) -> None:
    print(f"report_consistency: {result.status}")
    print(f"checked_dates: {len(result.checked_dates)}")
    print(f"errors: {len(result.errors)}")
    print(f"warnings: {len(result.warnings)}")
    for issue in result.errors[:50]:
        print(f"[ERROR] {issue.as_of_date} {issue.artifact} {issue.check}: {issue.message}")
    for issue in result.warnings[:50]:
        print(f"[WARN] {issue.as_of_date} {issue.artifact} {issue.check}: {issue.message}")


def _write_output(result: ValidationResult, output: str | None) -> None:
    if not output:
        return
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": result.status,
        "checked_dates": result.checked_dates,
        "errors": [asdict(issue) for issue in result.errors],
        "warnings": [asdict(issue) for issue in result.warnings],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
