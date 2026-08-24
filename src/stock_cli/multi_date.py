"""多日期市场分析产物 CLI。"""

from __future__ import annotations

import argparse
import importlib
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from stock_analytics.features import FeatureStore
from stock_analytics.pipelines.artifact_contracts import RunClass, normalize_run_class
from stock_analytics.pipelines.artifact_store import ArtifactRunPaths, ArtifactStore
from stock_analytics.pipelines.multi_date import (
    MultiDateArtifactSummary,
    run_multi_date_artifacts,
)
from stock_cli.features import build_features
from stock_core.utils.logger import logger
from stock_data.catalog import DataCatalog

if TYPE_CHECKING:
    from scripts.report_consistency import ConsistencyValidator
else:
    try:
        _report_consistency = importlib.import_module("scripts.report_consistency")
    except ModuleNotFoundError:  # pragma: no cover - 支持直接按文件路径执行
        _report_consistency = importlib.import_module("report_consistency")
    ConsistencyValidator = _report_consistency.ConsistencyValidator


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class _ArtifactSummary:
    artifact_type: str
    run_dir: Path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="按多个 A 股交易日串行生成并发布四类分析产物",
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
        help="在批量报告前按增量方式刷新全部领域 Mart",
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
        "--analytics-root",
        type=Path,
        default=Path("data/analytics"),
        help="四类分析产物的共同根目录",
    )
    parser.add_argument(
        "--publish-date",
        type=_parse_date,
        metavar="YYYY-MM-DD",
        help="发布到 latest 的日期，默认选择本次日期中的最新日期",
    )
    parser.add_argument(
        "--run-class",
        choices=("official", "backfill", "experiment"),
        default="official",
        help="产物运行分类",
    )
    parser.add_argument(
        "--skip-metrics",
        dest="collect_metric_values",
        action="store_false",
        default=None,
        help="只采集窗口与数据水位，不运行 MetricEngine 指标",
    )
    parser.add_argument(
        "--no-publish-latest",
        action="store_true",
        help="一致性校验后不发布任何 latest",
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
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> list[date]:
    if args.dates is not None:
        if args.end is not None:
            parser.error("--end 只能与 --start 一起使用，不能和 --dates 同时使用")
        if len(set(args.dates)) != len(args.dates):
            parser.error("--dates 中不能重复指定同一交易日")
        return sorted(args.dates)

    if args.last_n is not None:
        if args.end is not None:
            parser.error("--end 只能与 --start 一起使用，不能和 --last-n 同时使用")
        return _load_recent_trade_dates(args.last_n, storage_dir=args.storage_dir)

    if args.start is None or args.end is None:
        parser.error("使用区间模式时必须同时提供 --start 和 --end")
    if args.start > args.end:
        parser.error("--start 不能晚于 --end")
    return _load_trade_dates(args.start, args.end, storage_dir=args.storage_dir)


def _load_trade_dates(start: date, end: date, *, storage_dir: Path | None) -> list[date]:
    """从本地 Curated stock_daily_bar 解析区间交易日。"""
    catalog = DataCatalog(
        data_source="tushare",
        storage_dir=storage_dir or REPO_ROOT / "data" / "curated",
    )
    latest = catalog.latest_trade_dates(dataset="stock_daily_bar", n=1)
    if not latest:
        raise RuntimeError("本地 stock_daily_bar 没有可用交易日，无法解析批量日期")
    scan_count = max((latest[0] - start).days + 1, 1)
    available = catalog.latest_trade_dates(dataset="stock_daily_bar", n=scan_count)
    selected = sorted(value for value in available if start <= value <= end)
    if not selected:
        raise RuntimeError(f"区间 {start.isoformat()} 至 {end.isoformat()} 没有本地交易日")
    return selected


def _load_recent_trade_dates(n: int, *, storage_dir: Path | None) -> list[date]:
    """从本地 Curated stock_daily_bar 选择最近 N 个交易日。"""
    catalog = DataCatalog(
        data_source="tushare",
        storage_dir=storage_dir or REPO_ROOT / "data" / "curated",
    )
    available = sorted(catalog.latest_trade_dates(dataset="stock_daily_bar", n=n))
    if len(available) < n:
        raise RuntimeError(
            f"本地 stock_daily_bar 只有 {len(available)} 个交易日，少于要求的 {n} 个"
        )
    return available


def _market_daily_min_date(storage_dir: Path | None) -> date | None:
    mart_dir = storage_dir / "mart" if storage_dir is not None else None
    frame = FeatureStore(mart_dir=mart_dir).get_market_daily(columns=["trade_date"])
    if frame.is_empty() or "trade_date" not in frame.columns:
        return None
    value = frame["trade_date"].drop_nulls().min()
    return value if isinstance(value, date) else None


def _refresh_mart(
    dates: list[date],
    *,
    storage_dir: Path | None,
    mart_start: date | None,
) -> None:
    previous_min_date = _market_daily_min_date(storage_dir)
    build_features(
        target="all",
        start_date=mart_start or dates[0],
        end_date=dates[-1],
        storage_dir=storage_dir,
    )
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


def _run_generation(
    dates: list[date],
    *,
    storage_dir: Path | None,
    analytics_root: Path,
    run_class: RunClass,
    collect_metric_values: bool | None,
) -> tuple[MultiDateArtifactSummary, ...]:
    return run_multi_date_artifacts(
        dates,
        storage_dir=storage_dir,
        analytics_root=analytics_root,
        update_latest=False,
        run_class=run_class,
        collect_metric_values=collect_metric_values,
    )


def _validate_dates(
    dates: list[date],
    *,
    analytics_root: Path,
    run_class: RunClass,
) -> None:
    result = ConsistencyValidator(analytics_root).validate_dates(
        [value.isoformat() for value in dates],
        run_class=run_class,
    )
    if result.status == "passed":
        print(f"已通过 {len(dates)} 个日期的一致性校验")
        return
    for issue in result.errors[:20]:
        print(f"[ERROR] {issue.as_of_date} {issue.artifact}: {issue.message}", file=sys.stderr)
    raise RuntimeError("产物一致性校验失败")


def _summary_artifacts(
    summary: MultiDateArtifactSummary,
) -> tuple[_ArtifactSummary, ...]:
    return tuple(
        _ArtifactSummary(artifact_type, run_dir)
        for artifact_type, run_dir in (
            ("market_temperature", summary.market_temperature_run_dir),
            ("industry_structure", summary.industry_structure_run_dir),
            ("investor_brief", summary.investor_brief_run_dir),
            ("quant_brief", summary.quant_brief_run_dir),
        )
    )


def _publish_summary(
    summary: MultiDateArtifactSummary,
    *,
    analytics_root: Path,
    run_class: RunClass,
) -> None:
    for item in _summary_artifacts(summary):
        root = analytics_root / item.artifact_type
        paths = ArtifactRunPaths(
            root=root,
            run_dir=item.run_dir,
            latest_dir=root / "latest",
            artifact_type=item.artifact_type,
            run_class=run_class,
        )
        ArtifactStore(paths).publish_existing()
    print(f"已发布 {summary.as_of_date.isoformat()} 到四类产物 latest")


def _validate_latest(analytics_root: Path) -> None:
    result = ConsistencyValidator(analytics_root).validate_latest()
    if result.status != "passed":
        raise RuntimeError("latest 一致性校验失败")
    print("已通过 latest 一致性校验")


def _print_plan(
    dates: list[date],
    *,
    args: argparse.Namespace,
) -> None:
    print(f"计划处理 {len(dates)} 个交易日，全部串行执行并共享一次 Mart 数据读取")
    if args.refresh_mart:
        print(
            f"增量刷新 Mart: {(args.mart_start or dates[0]).isoformat()} ~ {dates[-1].isoformat()}"
        )
    print(f"分析产物根目录: {args.analytics_root}")
    print(f"运行分类: {args.run_class}")
    print("生成四类运行目录，完成一致性校验后再发布 latest")
    if not args.no_publish_latest:
        print(f"发布日期: {(args.publish_date or dates[-1]).isoformat()}")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.mart_start is not None and not args.refresh_mart:
        parser.error("--mart-start 只能与 --refresh-mart 一起使用")

    try:
        dates = _resolve_dates(args, parser)
        if args.publish_date is not None and args.publish_date not in dates:
            parser.error("--publish-date 必须属于本次选定的日期")
        run_class = normalize_run_class(args.run_class)
        if args.dry_run:
            _print_plan(dates, args=args)
            return 0

        if args.refresh_mart:
            _refresh_mart(
                dates,
                storage_dir=args.storage_dir,
                mart_start=args.mart_start,
            )
        summaries = _run_generation(
            dates,
            storage_dir=args.storage_dir,
            analytics_root=args.analytics_root,
            run_class=run_class,
            collect_metric_values=args.collect_metric_values,
        )
        _validate_dates(dates, analytics_root=args.analytics_root, run_class=run_class)
        if args.no_publish_latest:
            print("已跳过 latest 发布")
            return 0

        publish_date = args.publish_date or dates[-1]
        summary = next(item for item in summaries if item.as_of_date == publish_date)
        _publish_summary(summary, analytics_root=args.analytics_root, run_class=run_class)
        _validate_latest(args.analytics_root)
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        logger.error("多日期产物生成失败: {}", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
