"""按多个交易日串行生成四类市场分析产物，并在最后统一发布 latest。"""

from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
ARTIFACT_FILES: dict[str, tuple[str, ...]] = {
    "market_temperature": (
        "manifest.json",
        "facts.parquet",
        "scores.json",
        "report.md",
        "report.json",
        "human_report.md",
        "quality_report.md",
        "quality_report.json",
    ),
    "industry_structure": (
        "manifest.json",
        "facts.parquet",
        "industry_panel.parquet",
        "scores.json",
        "report.md",
        "report.json",
        "human_report.md",
        "quality_report.md",
        "quality_report.json",
    ),
    "investor_brief": ("manifest.json", "brief_report.md", "brief_report.json"),
    "quant_brief": ("manifest.json", "brief_report.md", "brief_report.json"),
}


class CommandError(RuntimeError):
    """封装子命令失败时的关键信息。"""

    def __init__(self, label: str, command: list[str], returncode: int, output: str) -> None:
        self.label = label
        self.command = command
        self.returncode = returncode
        self.output = output
        detail = output[-6000:] if output else "(无命令输出)"
        super().__init__(
            f"{label} 失败，退出码 {returncode}\n命令: {shlex.join(command)}\n输出尾部:\n{detail}"
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="按多个 A 股交易日串行生成四类分析产物，并复用一次 Mart 读取",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--dates",
        nargs="+",
        type=_parse_date,
        metavar="YYYY-MM-DD",
        help="显式指定一个或多个交易日",
    )
    source.add_argument(
        "--start",
        type=_parse_date,
        metavar="YYYY-MM-DD",
        help="从本地 stock_daily_bar 解析区间交易日的起始日期",
    )
    source.add_argument(
        "--last-n",
        type=_positive_int,
        metavar="N",
        help="从本地 stock_daily_bar 选择最近 N 个交易日",
    )
    parser.add_argument(
        "--end",
        type=_parse_date,
        metavar="YYYY-MM-DD",
        help="区间交易日的结束日期，需要与 --start 一起使用",
    )
    parser.add_argument(
        "--refresh-mart",
        action="store_true",
        help="在批量报告前按增量方式刷新全部领域 Mart；不会覆盖或删除历史数据",
    )
    parser.add_argument(
        "--mart-start",
        type=_parse_date,
        metavar="YYYY-MM-DD",
        help="--refresh-mart 的 Mart 起始日期，默认使用本次报告区间起始日",
    )
    parser.add_argument(
        "--storage-dir",
        type=Path,
        default=None,
        help="覆盖 Curated 数据目录",
    )
    parser.add_argument(
        "--publish-date",
        type=_parse_date,
        metavar="YYYY-MM-DD",
        help="发布到 latest 的日期，默认选择本次日期中的最新日期",
    )
    parser.add_argument(
        "--no-publish-latest",
        action="store_true",
        help="一致性校验后不复制任何产物到 latest",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印执行计划，不运行生成、校验或发布",
    )
    return parser


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"日期格式错误，请使用 YYYY-MM-DD: {value}") from exc


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"数量必须是正整数: {value}") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"数量必须是正整数: {value}")
    return parsed


def _resolve_dates(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> tuple[list[date], bool]:
    if args.dates is not None:
        if args.end is not None:
            parser.error("--end 只能与 --start 一起使用，不能和 --dates 同时使用")
        if len(set(args.dates)) != len(args.dates):
            parser.error("--dates 中不能重复指定同一交易日")
        return sorted(args.dates), False

    if args.last_n is not None:
        if args.end is not None:
            parser.error("--end 只能与 --start 一起使用，不能和 --last-n 同时使用")
        return _load_recent_trade_dates(args.last_n, storage_dir=args.storage_dir), True

    if args.start is None or args.end is None:
        parser.error("使用区间模式时必须同时提供 --start 和 --end")
    if args.start > args.end:
        parser.error("--start 不能晚于 --end")
    return _load_trade_dates(args.start, args.end, storage_dir=args.storage_dir), True


def _load_trade_dates(start: date, end: date, *, storage_dir: Path | None = None) -> list[date]:
    """从本地 Curated stock_daily_bar 解析指定自然日区间内的交易日。"""
    from stock_data.catalog import DataCatalog

    catalog = DataCatalog("tushare", storage_dir or REPO_ROOT / "data" / "curated")
    latest = catalog.latest_trade_dates(dataset="stock_daily_bar", n=1)
    if not latest:
        raise RuntimeError("本地 stock_daily_bar 没有可用交易日，无法解析批量日期")

    scan_count = max((latest[0] - start).days + 1, 1)
    available = catalog.latest_trade_dates(dataset="stock_daily_bar", n=scan_count)
    selected = sorted(value for value in available if start <= value <= end)
    if not selected:
        raise RuntimeError(f"区间 {start.isoformat()} 至 {end.isoformat()} 没有本地交易日")
    return selected


def _load_recent_trade_dates(n: int, *, storage_dir: Path | None = None) -> list[date]:
    """从本地 Curated stock_daily_bar 选择最近 N 个交易日。"""
    from stock_data.catalog import DataCatalog

    catalog = DataCatalog("tushare", storage_dir or REPO_ROOT / "data" / "curated")
    available = sorted(catalog.latest_trade_dates(dataset="stock_daily_bar", n=n))
    if len(available) < n:
        raise RuntimeError(
            f"本地 stock_daily_bar 只有 {len(available)} 个交易日，少于要求的 {n} 个"
        )
    return available


def _run_command(command: list[str], label: str) -> None:
    print(f"[{label}] {shlex.join(command)}", flush=True)
    completed = subprocess.run(  # noqa: S603 - command is a fixed make argument list
        command, cwd=REPO_ROOT, text=True, check=False
    )
    if completed.returncode != 0:
        raise CommandError(label, command, completed.returncode, "命令输出已直接打印")


def _market_daily_min_date(storage_dir: Path | None) -> date | None:
    """读取 market_daily 历史最早日期，用于增量刷新后的防截短校验。"""
    from stock_analytics.features.store import FeatureStore

    mart_dir = storage_dir / "mart" if storage_dir is not None else None
    frame = FeatureStore(mart_dir=mart_dir).get_market_daily(columns=["trade_date"])
    if frame.is_empty() or "trade_date" not in frame.columns:
        return None
    value = frame["trade_date"].drop_nulls().min()
    return value if isinstance(value, date) else None


def _build_dates(
    dates: list[date],
    *,
    storage_dir: Path | None,
    refresh_mart: bool,
    mart_start: date | None,
) -> None:
    if refresh_mart:
        previous_min_date = _market_daily_min_date(storage_dir)
        effective_mart_start = mart_start or dates[0]
        command = [
            "make",
            "features-build",
            "TARGET=all",
            f"START={effective_mart_start.isoformat()}",
            f"END={dates[-1].isoformat()}",
        ]
        if storage_dir is not None:
            command.append(f"STORAGE_DIR={storage_dir}")
        _run_command(command, "增量刷新 Mart")
        current_min_date = _market_daily_min_date(storage_dir)
        if previous_min_date is not None and (
            current_min_date is None or current_min_date > previous_min_date
        ):
            raise RuntimeError(
                "增量刷新后 market_daily 历史范围被截短，"
                f"刷新前={previous_min_date.isoformat()}，刷新后={current_min_date}；"
                "已拒绝继续生成产物，请检查 Mart 构建参数"
            )
        if previous_min_date is not None:
            print(f"已校验 market_daily 历史起点未变化: {previous_min_date.isoformat()}")

    from stock_analytics.pipelines.multi_date import run_multi_date_artifacts

    run_multi_date_artifacts(
        dates,
        storage_dir=storage_dir,
        update_latest=False,
    )
    for target_date in dates:
        print(f"已完成 {target_date.isoformat()} 的四类产物")


def _consistency_commands(dates: list[date], range_mode: bool) -> list[list[str]]:
    if range_mode:
        return [
            [
                "make",
                "report-consistency",
                f"START={dates[0].isoformat()}",
                f"END={dates[-1].isoformat()}",
            ]
        ]
    return [
        ["make", "report-consistency", f"DATE={target_date.isoformat()}"] for target_date in dates
    ]


def _run_consistency(dates: list[date], range_mode: bool) -> None:
    failures: list[str] = []
    for command in _consistency_commands(dates, range_mode):
        label = "区间一致性校验" if range_mode else f"{command[-1]} 一致性校验"
        try:
            _run_command(command, label)
        except CommandError as exc:
            failures.append(str(exc))
    if failures:
        raise RuntimeError("产物一致性校验失败:\n" + "\n\n".join(failures))
    print("已通过生成日期的一致性校验")


def _latest_run_dir(artifact_root: Path, target_date: date) -> Path:
    run_root = artifact_root / "runs" / f"as_of={target_date.isoformat()}"
    run_dirs = sorted(path for path in run_root.glob("run_*") if path.is_dir())
    if not run_dirs:
        raise RuntimeError(f"未找到 {artifact_root.name} {target_date.isoformat()} 的运行目录")
    return run_dirs[-1]


def _publish_latest(target_date: date) -> None:
    """将选定日期的完整运行目录文件复制到四个独立 latest 目录。"""
    sources: list[tuple[Path, Path]] = []
    analytics_root = REPO_ROOT / "data" / "analytics"
    for artifact, filenames in ARTIFACT_FILES.items():
        artifact_root = analytics_root / artifact
        run_dir = _latest_run_dir(artifact_root, target_date)
        latest_dir = artifact_root / "latest"
        for filename in filenames:
            source = run_dir / filename
            if not source.exists():
                raise RuntimeError(f"{source} 不存在，拒绝发布不完整的 latest")
            sources.append((source, latest_dir / filename))

    for source, target in sources:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    print(f"已发布 {target_date.isoformat()} 到四个产物 latest")


def _print_plan(dates: list[date], range_mode: bool, args: argparse.Namespace) -> None:
    print(f"计划处理 {len(dates)} 个交易日，全部串行执行并共享一次 Mart 数据读取")
    if args.refresh_mart:
        mart_start = args.mart_start.isoformat() if args.mart_start else dates[0].isoformat()
        print(
            "  $ "
            + shlex.join(
                [
                    "make",
                    "features-build",
                    "TARGET=all",
                    f"START={mart_start}",
                    f"END={dates[-1].isoformat()}",
                ]
            )
        )
    print("  串行调用 run_multi_date_artifacts(dates)，复用一次 Mart 与数据集缓存")

    for command in _consistency_commands(dates, range_mode):
        print(f"$ {shlex.join(command)}")
    if not args.no_publish_latest:
        publish_date = args.publish_date or dates[-1]
        print(f"发布 latest: {publish_date.isoformat()}")
        print("$ make report-consistency")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.no_publish_latest and args.publish_date is not None:
        parser.error("--no-publish-latest 不能与 --publish-date 同时使用")
    if not args.refresh_mart and args.mart_start is not None:
        parser.error("--mart-start 只能与 --refresh-mart 一起使用")

    try:
        dates, range_mode = _resolve_dates(args, parser)
        if args.publish_date is not None and args.publish_date not in dates:
            parser.error("--publish-date 必须属于本次选定的日期")
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"日期解析失败: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        _print_plan(dates, range_mode, args)
        return 0

    try:
        _build_dates(
            dates,
            storage_dir=args.storage_dir,
            refresh_mart=args.refresh_mart,
            mart_start=args.mart_start,
        )
        _run_consistency(dates, range_mode)
        if args.no_publish_latest:
            print("已跳过 latest 发布")
            return 0

        _publish_latest(args.publish_date or dates[-1])
        _run_command(["make", "report-consistency"], "latest 一致性校验")
        print("已通过 latest 一致性校验")
    except (CommandError, OSError, RuntimeError) as exc:
        print(f"批量产物生成失败: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
