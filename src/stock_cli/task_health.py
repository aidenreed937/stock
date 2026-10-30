"""CLI 入口：任务注册健康检查。"""

from __future__ import annotations

import argparse
import json
import sys

from stock_data.core.task_health import format_task_health_report, run_task_health_checks


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="只读检查任务注册、任务包、别名和 TaskSpec 契约")
    parser.add_argument(
        "--provider",
        action="append",
        default=None,
        help="只检查指定数据源；可重复传入，例如 --provider tushare --provider lixinger",
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON 结果")
    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="存在 warning 时也返回非零退出码",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    report = run_task_health_checks(args.provider)
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_task_health_report(report))

    failed = not report.ok or (args.fail_on_warning and report.warning_count > 0)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
