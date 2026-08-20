"""全市场聚合监控配置驱动产物管线。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl

from stock_analytics.pipelines.market_aggregate.artifacts import (
    MarketAggregateArtifactPayload,
    MarketAggregateRunPaths,
    build_run_paths,
    write_artifacts,
)
from stock_analytics.pipelines.market_aggregate.trend import (
    build_short_term_trend,
    build_trend_facts,
)
from stock_analytics.realtime.cache import MarketAggregateCache
from stock_analytics.realtime.market_aggregate_monitor import MarketAggregateMonitor
from stock_core.contracts import MarketDataCatalog
from stock_core.exceptions import DataFetchError
from stock_data.catalog import DataCatalog
from stock_data.fetcher.realtime.base import normalize_local_symbol
from stock_data.fetcher.realtime.market_aggregate import (
    BaseMarketAggregateFetcher,
    TencentMarketAggregateFetcher,
)
from stock_data.fetcher.realtime.market_aggregate_recorder import (
    MarketAggregateSnapshotRecorder,
)
from stock_reporting.interpretation.market_aggregate.config import (
    DEFAULT_CONFIG_PATH,
    MarketAggregateConfig,
    load_market_aggregate_config,
)
from stock_reporting.templates.market_aggregate import (
    build_quality_report,
    build_report_json,
    render_human_report_markdown,
    render_quality_report_markdown,
    render_report_markdown,
    render_table_markdown,
)

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class MarketAggregateRunResult:
    """全市场聚合监控一次运行结果。"""

    as_of_date: date
    paths: MarketAggregateRunPaths
    manifest: dict[str, Any]
    snapshot: Any
    freshness: str
    age_seconds: float
    facts: pl.DataFrame
    report_markdown: str
    table_markdown: str
    human_report_markdown: str
    report_json: dict[str, Any]
    quality_report_markdown: str
    quality_report_json: dict[str, Any]
    short_term_trend: dict[str, Any]


def run_market_aggregate(
    *,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    output_root: Path | str | None = None,
    update_latest: bool = True,
    record_raw: bool = False,
    raw_root: Path | str | None = None,
    batch_size: int | None = None,
    strong_move_pct: float | None = None,
    fetcher: BaseMarketAggregateFetcher | None = None,
    catalog: MarketDataCatalog | None = None,
    now: datetime | None = None,
) -> MarketAggregateRunResult:
    """执行一次配置驱动的全市场聚合抓取、报告渲染和产物写入。"""
    config = load_market_aggregate_config(config_path).with_artifact_root(output_root)
    config = config.with_runtime_overrides(
        batch_size=batch_size,
        strong_move_pct=strong_move_pct,
    )
    catalog_for_history = catalog
    if fetcher is None:
        catalog_for_history = catalog or DataCatalog(data_source="tushare")
        symbols = _load_market_symbols(config.universe.dataset, catalog=catalog_for_history)
        actual_fetcher: BaseMarketAggregateFetcher = TencentMarketAggregateFetcher(
            symbols=symbols,
            batch_size=config.fetch.batch_size,
            timeout_seconds=config.fetch.timeout_seconds,
            max_retries=config.fetch.max_retries,
            retry_backoff_seconds=config.fetch.retry_backoff_seconds,
            strong_move_threshold_pct=config.thresholds.strong_move_pct,
        )
    else:
        actual_fetcher = fetcher
    recorder = _build_recorder(config, record_raw=record_raw, raw_root=raw_root)
    monitor = MarketAggregateMonitor(
        actual_fetcher,
        cache=MarketAggregateCache(
            fresh_ttl_seconds=config.cache.fresh_ttl_seconds,
            max_age_seconds=config.cache.max_age_seconds,
        ),
        recorder=recorder,
    )
    cached = monitor.run(now=now)
    snapshot = cached.snapshot
    paths = build_run_paths(snapshot.quote_date, config.artifact_root)
    manifest = _build_manifest(config, paths, snapshot, cached.freshness.value, cached.age_seconds)
    snapshot_payload = snapshot.model_dump(mode="json")
    snapshot_payload["quote_date"] = snapshot.quote_date.isoformat()
    facts = pl.DataFrame([snapshot_payload])
    short_term_trend = build_short_term_trend(
        catalog_for_history,
        snapshot,
        prior_trade_days=config.trend.history_days,
        strong_move_threshold_pct=config.thresholds.strong_move_pct,
        bars_dataset=config.trend.bars_dataset,
        market_value_dataset=config.trend.market_value_dataset,
    )
    trend_facts = build_trend_facts(short_term_trend)
    quality_report_json = build_quality_report(
        config=config,
        manifest=manifest,
        snapshot=snapshot,
        freshness=cached.freshness.value,
        age_seconds=cached.age_seconds,
    )
    report_json = build_report_json(
        config=config,
        manifest=manifest,
        snapshot=snapshot,
        freshness=cached.freshness.value,
        age_seconds=cached.age_seconds,
        quality_report=quality_report_json,
        trend=short_term_trend,
    )
    report_markdown = render_report_markdown(
        config=config,
        manifest=manifest,
        snapshot=snapshot,
        freshness=cached.freshness.value,
        age_seconds=cached.age_seconds,
        quality_report=quality_report_json,
        trend=short_term_trend,
    )
    table_markdown = render_table_markdown(
        config=config,
        manifest=manifest,
        snapshot=snapshot,
        freshness=cached.freshness.value,
        age_seconds=cached.age_seconds,
        quality_report=quality_report_json,
    )
    human_report_markdown = render_human_report_markdown(
        config=config,
        manifest=manifest,
        snapshot=snapshot,
        freshness=cached.freshness.value,
        age_seconds=cached.age_seconds,
        quality_report=quality_report_json,
        trend=short_term_trend,
    )
    quality_report_markdown = render_quality_report_markdown(
        config=config,
        quality_report=quality_report_json,
    )
    write_artifacts(
        paths,
        MarketAggregateArtifactPayload(
            manifest=manifest,
            snapshot=snapshot_payload,
            facts=facts,
            trend=trend_facts,
            report_markdown=report_markdown,
            report_json=report_json,
            human_report_markdown=human_report_markdown,
            quality_report_markdown=quality_report_markdown,
            quality_report_json=quality_report_json,
        ),
        update_latest=update_latest,
    )
    return MarketAggregateRunResult(
        as_of_date=snapshot.quote_date,
        paths=paths,
        manifest=manifest,
        snapshot=snapshot,
        freshness=cached.freshness.value,
        age_seconds=cached.age_seconds,
        facts=facts,
        report_markdown=report_markdown,
        table_markdown=table_markdown,
        human_report_markdown=human_report_markdown,
        report_json=report_json,
        quality_report_markdown=quality_report_markdown,
        quality_report_json=quality_report_json,
        short_term_trend=short_term_trend,
    )


def _build_recorder(
    config: MarketAggregateConfig,
    *,
    record_raw: bool,
    raw_root: Path | str | None,
) -> MarketAggregateSnapshotRecorder | None:
    if not record_raw:
        return None
    if raw_root is None:
        from stock_data.core.settings import data_settings

        root = (
            data_settings.runtime_context.raw_root / "realtime" / "market_aggregate" / config.source
        )
    else:
        root = Path(raw_root)
    return MarketAggregateSnapshotRecorder(
        root=root,
        source=config.source,
        flush_interval_seconds=config.raw.flush_interval_seconds,
    )


def _load_market_symbols(
    dataset: str,
    *,
    catalog: MarketDataCatalog | None = None,
) -> tuple[str, ...]:
    """从本地 stock_basic 读取在市沪深股票，不用观察池替代全市场。"""
    try:
        frame = (catalog or DataCatalog(data_source="tushare")).load_dataset(dataset)
    except (OSError, TypeError, ValueError) as exc:
        raise DataFetchError(
            "腾讯全市场聚合需要本地 stock_basic，请先运行：make backfill ENDPOINT=stock_basic"
        ) from exc

    if frame.is_empty():
        raise DataFetchError(
            "腾讯全市场聚合未找到本地 stock_basic，请先运行：make backfill ENDPOINT=stock_basic"
        )

    symbol_column = "symbol" if "symbol" in frame.columns else "ts_code"
    if symbol_column not in frame.columns:
        raise DataFetchError("本地 stock_basic 缺少 symbol/ts_code 标识列")

    symbols: list[str] = []
    seen: set[str] = set()
    for row in frame.iter_rows(named=True):
        list_status = row.get("list_status")
        if list_status is not None and str(list_status).upper() != "L":
            continue
        raw_symbol = row.get(symbol_column)
        if raw_symbol is None:
            continue
        raw_value = str(raw_symbol).strip()
        exchange = _exchange_suffix(row.get("exchange"))
        if "." not in raw_value and exchange:
            raw_value = f"{raw_value}.{exchange}"
        try:
            symbol = normalize_local_symbol(raw_value)
        except ValueError:
            continue
        if not symbol.endswith((".SH", ".SZ")) or symbol in seen:
            continue
        symbols.append(symbol)
        seen.add(symbol)

    if not symbols:
        raise DataFetchError("本地 stock_basic 没有可用于腾讯聚合的沪深在市股票")
    return tuple(symbols)


def _exchange_suffix(value: object) -> str | None:
    mapping = {
        "SH": "SH",
        "SZ": "SZ",
        "SSE": "SH",
        "SZSE": "SZ",
        "XSHG": "SH",
        "XSHE": "SZ",
    }
    return mapping.get(str(value).strip().upper()) if value is not None else None


def _build_manifest(
    config: MarketAggregateConfig,
    paths: MarketAggregateRunPaths,
    snapshot: Any,
    freshness: str,
    age_seconds: float,
) -> dict[str, Any]:
    return {
        "schema_version": config.schema_version,
        "title": config.title,
        "run_id": paths.run_dir.name,
        "generated_at": datetime.now(_SHANGHAI_TZ).isoformat(timespec="seconds"),
        "quote_date": snapshot.quote_date.isoformat(),
        "quote_at": snapshot.quote_at.isoformat() if snapshot.quote_at else None,
        "received_at": snapshot.received_at.isoformat(),
        "source": snapshot.source,
        "scope": snapshot.scope,
        "status": snapshot.status,
        "freshness": freshness,
        "age_seconds": age_seconds,
        "reported_count": snapshot.reported_count,
        "returned_count": snapshot.returned_count,
        "coverage_ratio": snapshot.coverage_ratio,
        "artifact_root": str(paths.root),
        "files": {
            "manifest": paths.manifest.name,
            "snapshot": paths.snapshot.name,
            "facts": paths.facts.name,
            "trend": paths.trend.name,
            "report_md": paths.report_md.name,
            "report_json": paths.report_json.name,
            "human_report_md": paths.human_report_md.name,
            "quality_report_md": paths.quality_report_md.name,
            "quality_report_json": paths.quality_report_json.name,
        },
    }


__all__ = ["MarketAggregateRunResult", "run_market_aggregate"]
