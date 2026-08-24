"""全市场聚合监控 Manifest 构建。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from stock_analytics.pipelines.manifest import build_manifest_base
from stock_analytics.pipelines.market_aggregate.artifacts import MarketAggregateRunPaths

if TYPE_CHECKING:
    from stock_reporting.interpretation.market_aggregate.config import MarketAggregateConfig


def build_market_aggregate_manifest(
    config: MarketAggregateConfig,
    paths: MarketAggregateRunPaths,
    snapshot: Any,
    freshness: str,
    age_seconds: float,
    *,
    config_path: Path | str | None = None,
) -> dict[str, Any]:
    """构造全市场聚合运行 Manifest。"""
    watermark = {
        "source": snapshot.source,
        "quote_date": snapshot.quote_date.isoformat(),
        "quote_at": snapshot.quote_at.isoformat() if snapshot.quote_at else None,
        "received_at": snapshot.received_at.isoformat(),
        "freshness": freshness,
    }
    manifest = build_manifest_base(
        artifact_type="market_aggregate",
        schema_version=config.schema_version,
        title=config.title,
        run_id=paths.run_dir.name,
        as_of_date=snapshot.quote_date,
        artifact_root=paths.root,
        config_path=config_path,
        inputs={"snapshot": watermark},
        watermarks={str(snapshot.source): watermark},
    )
    manifest.update(
        {
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
            "files": {
                "manifest": paths.manifest.name,
                "snapshot": paths.snapshot.name,
                "facts": paths.facts.name,
                "trend": paths.trend.name,
                "industry_breadth": paths.industry_breadth.name,
                "report_md": paths.report_md.name,
                "report_json": paths.report_json.name,
                "human_report_md": paths.human_report_md.name,
                "quality_report_md": paths.quality_report_md.name,
                "quality_report_json": paths.quality_report_json.name,
            },
        }
    )
    return manifest


__all__ = ["build_market_aggregate_manifest"]
