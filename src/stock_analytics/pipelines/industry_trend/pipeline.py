"""申万行业产业趋势跟踪因子面板管线编排。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from stock_analytics.pipelines.artifacts import ArtifactRunPaths
from stock_analytics.pipelines.industry_trend.config import (
    DEFAULT_CONFIG_PATH,
    load_industry_trend_config,
)
from stock_analytics.pipelines.industry_trend.factor_panel import (
    build_industry_trend_panel,
    save_industry_trend_panel,
)
from stock_data.core.runtime import DataRuntimeContext


def run_industry_trend_panel(
    *,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    output_root: Path | str | None = None,
    run_class: str = "official",
    update_latest: bool = True,
    as_of: date | None = None,
    start_date: date | None = None,
    storage_dir: Path | str | None = None,
) -> ArtifactRunPaths:
    """生成并落盘产业趋势跟踪因子面板。"""
    config = load_industry_trend_config(config_path)
    runtime = DataRuntimeContext.from_root(storage_dir) if storage_dir else None

    panel = build_industry_trend_panel(
        config_path=config_path,
        runtime=runtime,
        start_date=start_date or date(2015, 1, 1),
        as_of=as_of,
    )
    return save_industry_trend_panel(
        panel,
        output_dir=output_root or config.artifact_root,
        as_of=as_of,
        update_latest=update_latest,
        run_class=run_class,  # type: ignore[arg-type]
        config_path=config_path,
    )


__all__ = ["run_industry_trend_panel"]
