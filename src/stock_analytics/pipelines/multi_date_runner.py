"""多日期分析任务的应用编排。"""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from stock_analytics.features.store import FeatureStore
from stock_analytics.pipelines.artifact_contracts import RunClass, normalize_run_class
from stock_analytics.pipelines.artifact_store import ArtifactRunPaths, ArtifactStore
from stock_analytics.pipelines.features import build_features
from stock_analytics.pipelines.multi_date import (
    MultiDateArtifactSummary,
    _load_trade_dates,
    run_multi_date_artifacts,
)
from stock_data.catalog import DataCatalog


@dataclass(frozen=True, slots=True)
class MultiDateRunResult:
    """多日期业务管线一次运行的结果。"""

    summaries: tuple[MultiDateArtifactSummary, ...]
    messages: tuple[str, ...]
    published: bool


def run_multi_date(
    *,
    dates: Sequence[date] | None = None,
    start: date | None = None,
    end: date | None = None,
    last_n: int | None = None,
    refresh_mart: bool = False,
    mart_start: date | None = None,
    storage_dir: Path | str | None = None,
    analytics_root: Path | str = "data/analytics",
    publish_date: date | None = None,
    run_class: RunClass | str = "official",
    collect_metric_values: bool | None = None,
    no_publish_latest: bool = False,
    dry_run: bool = False,
) -> MultiDateRunResult:
    """解析日期、生成四类产物、校验并按需发布 latest。"""
    if mart_start is not None and not refresh_mart:
        raise ValueError("--mart-start 只能与 --refresh-mart 一起使用")
    selected_dates = _resolve_dates(
        dates=dates,
        start=start,
        end=end,
        last_n=last_n,
        storage_dir=storage_dir,
    )
    if publish_date is not None and publish_date not in selected_dates:
        raise ValueError("--publish-date 必须属于本次选定的日期")
    normalized_class = normalize_run_class(run_class)
    analytics_path = Path(analytics_root)
    if dry_run:
        return MultiDateRunResult(
            summaries=(),
            messages=_plan_messages(
                selected_dates,
                analytics_root=analytics_path,
                run_class=normalized_class,
                refresh_mart=refresh_mart,
                mart_start=mart_start,
                publish_date=publish_date,
                no_publish_latest=no_publish_latest,
            ),
            published=False,
        )

    messages: list[str] = []
    if refresh_mart:
        refresh_message = _refresh_mart(
            selected_dates,
            storage_dir=storage_dir,
            mart_start=mart_start,
        )
        if refresh_message:
            messages.append(refresh_message)
    summaries = run_multi_date_artifacts(
        selected_dates,
        storage_dir=storage_dir,
        analytics_root=analytics_path,
        update_latest=False,
        run_class=normalized_class,
        collect_metric_values=collect_metric_values,
    )
    messages.append(
        _validate_dates(
            selected_dates,
            analytics_root=analytics_path,
            run_class=normalized_class,
        )
    )
    if no_publish_latest:
        messages.append("已跳过 latest 发布")
        return MultiDateRunResult(summaries, tuple(messages), published=False)

    selected_publish_date = publish_date or selected_dates[-1]
    summary = next(item for item in summaries if item.as_of_date == selected_publish_date)
    messages.append(
        _publish_summary(
            summary,
            analytics_root=analytics_path,
            run_class=normalized_class,
        )
    )
    messages.append(_validate_latest(analytics_path))
    return MultiDateRunResult(summaries, tuple(messages), published=True)


def _resolve_dates(
    *,
    dates: Sequence[date] | None,
    start: date | None,
    end: date | None,
    last_n: int | None,
    storage_dir: Path | str | None,
) -> list[date]:
    storage_path = Path(storage_dir) if storage_dir is not None else None
    if dates is not None:
        if start is not None or end is not None or last_n is not None:
            raise ValueError("dates 不能与 start/end/last_n 同时使用")
        selected = sorted(set(dates))
        if len(selected) != len(dates):
            raise ValueError("dates 中不能重复指定同一交易日")
        if not selected:
            raise ValueError("至少需要一个交易日")
        return selected
    if last_n is not None:
        if start is not None or end is not None:
            raise ValueError("last_n 不能与 start/end 同时使用")
        if last_n <= 0:
            raise ValueError("last_n 必须是正整数")
        catalog = DataCatalog(data_source="tushare", storage_dir=storage_path)
        selected = sorted(catalog.latest_trade_dates(dataset="stock_daily_bar", n=last_n))
        if len(selected) < last_n:
            raise RuntimeError(
                f"本地 stock_daily_bar 只有 {len(selected)} 个交易日，少于要求的 {last_n} 个"
            )
        return selected
    if start is None or end is None:
        raise ValueError("区间模式必须同时提供 start 和 end")
    if start > end:
        raise ValueError("start 不能晚于 end")
    return list(
        _load_trade_dates(
            "stock_daily_bar",
            start,
            end,
            storage_path,
            extra_window=0,
        )
    )


def _refresh_mart(
    dates: Sequence[date],
    *,
    storage_dir: Path | str | None,
    mart_start: date | None,
) -> str | None:
    storage_path = Path(storage_dir) if storage_dir is not None else None
    previous_min_date = _market_daily_min_date(storage_path)
    build_features(
        target="all",
        start_date=mart_start or dates[0],
        end_date=dates[-1],
        storage_dir=storage_path,
    )
    current_min_date = _market_daily_min_date(storage_path)
    if previous_min_date is not None and (
        current_min_date is None or current_min_date > previous_min_date
    ):
        raise RuntimeError(
            "增量刷新后 market_daily 历史范围被截短，"
            f"刷新前={previous_min_date.isoformat()}，刷新后={current_min_date}；"
            "已拒绝继续生成产物，请检查 Mart 构建参数"
        )
    if previous_min_date is not None:
        return f"已校验 market_daily 历史起点未变化: {previous_min_date.isoformat()}"
    return None


def _market_daily_min_date(storage_dir: Path | None) -> date | None:
    mart_dir = storage_dir / "mart" if storage_dir is not None else None
    frame = FeatureStore(mart_dir=mart_dir).get_market_daily(columns=["trade_date"])
    if frame.is_empty() or "trade_date" not in frame.columns:
        return None
    value = frame["trade_date"].drop_nulls().min()
    return value if isinstance(value, date) else None


def _validate_dates(
    dates: Sequence[date],
    *,
    analytics_root: Path,
    run_class: RunClass,
) -> str:
    validator = _consistency_validator(analytics_root)
    result = validator.validate_dates([value.isoformat() for value in dates], run_class=run_class)
    if result.status != "passed":
        details = "; ".join(
            f"{issue.as_of_date} {issue.artifact}: {issue.message}" for issue in result.errors[:20]
        )
        raise RuntimeError(f"产物一致性校验失败: {details}")
    return f"已通过 {len(dates)} 个日期的一致性校验"


def _publish_summary(
    summary: MultiDateArtifactSummary,
    *,
    analytics_root: Path,
    run_class: RunClass,
) -> str:
    for artifact_type, run_dir in (
        ("market_temperature", summary.market_temperature_run_dir),
        ("industry_structure", summary.industry_structure_run_dir),
        ("investor_brief", summary.investor_brief_run_dir),
        ("quant_brief", summary.quant_brief_run_dir),
    ):
        root = analytics_root / artifact_type
        paths = ArtifactRunPaths(
            root=root,
            run_dir=run_dir,
            latest_dir=root / "latest",
            artifact_type=artifact_type,
            run_class=run_class,
        )
        ArtifactStore(paths).publish_existing()
    return f"已发布 {summary.as_of_date.isoformat()} 到四类产物 latest"


def _validate_latest(analytics_root: Path) -> str:
    result = _consistency_validator(analytics_root).validate_latest()
    if result.status != "passed":
        raise RuntimeError("latest 一致性校验失败")
    return "已通过 latest 一致性校验"


def _consistency_validator(analytics_root: Path) -> Any:
    try:
        module = importlib.import_module("scripts.report_consistency")
    except ModuleNotFoundError:
        module = importlib.import_module("report_consistency")
    return module.ConsistencyValidator(analytics_root)


def _plan_messages(
    dates: Sequence[date],
    *,
    analytics_root: Path,
    run_class: RunClass,
    refresh_mart: bool,
    mart_start: date | None,
    publish_date: date | None,
    no_publish_latest: bool,
) -> tuple[str, ...]:
    messages = [f"计划处理 {len(dates)} 个交易日，全部串行执行并共享一次 Mart 数据读取"]
    if refresh_mart:
        messages.append(
            f"增量刷新 Mart: {(mart_start or dates[0]).isoformat()} ~ {dates[-1].isoformat()}"
        )
    messages.extend(
        (
            f"分析产物根目录: {analytics_root}",
            f"运行分类: {run_class}",
            "生成四类运行目录，完成一致性校验后再发布 latest",
        )
    )
    if not no_publish_latest:
        messages.append(f"发布日期: {(publish_date or dates[-1]).isoformat()}")
    return tuple(messages)


__all__ = ["MultiDateRunResult", "run_multi_date"]
