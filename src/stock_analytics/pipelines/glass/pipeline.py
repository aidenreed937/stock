"""玻璃全景对账管线编排：读取 → 合并 → 渲染 → ArtifactStore 落盘 + manifest。

规范对齐半导体/纯碱管线：runs/as_of=.../run_.../ + latest/ + manifest.json。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_analytics.pipelines.artifacts import (
    ArtifactRunPaths,
    ArtifactStore,
    ArtifactWriteSession,
    RunClass,
    build_manifest_base,
)
from stock_analytics.pipelines.glass.company import (
    build_glass_company_panel,
    load_glass_company_configs,
)
from stock_analytics.pipelines.glass.config import (
    DEFAULT_CONFIG_PATH,
    GlassConfig,
    load_glass_config,
)
from stock_analytics.pipelines.glass.gates import (
    evaluate_glass_trading_gates,
    load_glass_trading_gates,
)
from stock_analytics.pipelines.glass.panorama import (
    aggregate_furnace_capacity_by_month,
    latest_core_row,
    merge_monthly_panorama,
)
from stock_analytics.pipelines.glass.report import render_glass_markdown
from stock_analytics.pipelines.glass.sources import (
    DatasetReader,
    load_capacity_furnaces,
    load_customs_glass,
    load_futures_daily,
    load_nbs_plate_glass,
    load_nbs_soda_ash,
    load_spot_benchmarks,
    load_warehouse_receipts,
    load_weekly_survey,
)
from stock_data.catalog import DataCatalog
from stock_data.core.runtime import DataRuntimeContext

logger = logging.getLogger(__name__)

_ARTIFACT_TYPE = "glass_panorama"


@dataclass(frozen=True, slots=True)
class GlassRunResult:
    """玻璃全景管线运行结果。"""

    as_of_date: date
    paths: ArtifactRunPaths
    manifest: dict[str, Any]
    panorama: pl.DataFrame
    company_panel: pl.DataFrame
    report_markdown: str


class GlassPipeline:
    """玻璃全景基本面对账与量化信号管线。"""

    def __init__(
        self,
        runtime: DataRuntimeContext | None = None,
        config: GlassConfig | Path | str | None = DEFAULT_CONFIG_PATH,
        catalog_factory: Callable[[str], DatasetReader] | None = None,
        config_path: Path | str | None = None,
    ) -> None:
        self.runtime = runtime or DataRuntimeContext.from_root("data")
        if config is None:
            config = DEFAULT_CONFIG_PATH
        if isinstance(config, GlassConfig):
            self.config = config
            self._config_path: Path | str | None = config_path
        else:
            self._config_path = config
            self.config = load_glass_config(config)
        self._catalog_factory = catalog_factory or (
            lambda source: DataCatalog(data_source=source, storage_dir=self.runtime.curated_root)
        )

    def run(
        self,
        as_of: date | None = None,
        output_dir: Path | str | None = None,
        run_class: RunClass = "official",
        update_latest: bool = True,
    ) -> GlassRunResult:
        cfg = self.config
        catalog = self._catalog_factory("industry")

        furnaces = load_capacity_furnaces(cfg.inputs.capacity_furnaces)
        furnace_inc = aggregate_furnace_capacity_by_month(furnaces)

        glass_df = load_nbs_plate_glass(cfg.inputs.nbs_plate_glass_csv)
        soda_df = load_nbs_soda_ash(cfg.inputs.nbs_soda_ash_csv)
        customs_df = load_customs_glass(
            catalog, cfg.inputs.customs_trade_dataset, cfg.inputs.customs_trade_fallback
        )
        receipt_df = load_warehouse_receipts(catalog, cfg.inputs.futures_inventory_dataset)
        futures_df = load_futures_daily(catalog, cfg.inputs.futures_daily_dataset)
        weekly_df = load_weekly_survey(catalog, cfg.inputs.chemical_weekly_survey_dataset)
        spot = load_spot_benchmarks(catalog, cfg.inputs.chemical_spot_price_dataset)

        company_configs = load_glass_company_configs(cfg.inputs.companies)
        company_panel = build_glass_company_panel(
            storage_root=self.runtime.data_root, company_configs=company_configs
        )

        panorama = merge_monthly_panorama(
            glass_df=glass_df,
            soda_df=soda_df,
            customs_df=customs_df,
            receipt_df=receipt_df,
            futures_df=futures_df,
            weekly_survey_df=weekly_df,
            furnace_increment=furnace_inc,
            regime=cfg.regime,
        )

        if panorama.is_empty():
            raise RuntimeError("玻璃全景表为空：NBS 核心输入缺失或无有效月份")

        if as_of is not None:
            as_of_month = f"{as_of.year:04d}-{as_of.month:02d}"
            panorama = panorama.filter(pl.col("report_month") <= pl.lit(as_of_month))
            if panorama.is_empty():
                raise RuntimeError(f"玻璃全景表为空：as_of={as_of} 之前无有效月份")

        gates_cfg = load_glass_trading_gates(cfg.inputs.trading_gates)
        gate_evaluation = evaluate_glass_trading_gates(panorama, company_panel, spot, gates_cfg)

        month_str = _latest_month(panorama)
        as_of_date = as_of or _parse_month_as_date(month_str)
        markdown = render_glass_markdown(
            panorama=panorama,
            furnaces=furnaces,
            company_panel=company_panel,
            spot_benchmarks=spot,
            gate_evaluation=gate_evaluation,
            config=cfg,
        )

        artifact_root = Path(output_dir) if output_dir is not None else Path(cfg.artifact_root)
        paths = ArtifactStore.build_run_paths(
            as_of_date=as_of_date, artifact_root=artifact_root, run_class=run_class
        )
        manifest = _build_manifest(
            cfg=cfg,
            as_of_date=as_of_date,
            paths=paths,
            panorama=panorama,
            company_panel=company_panel,
            gate_evaluation=gate_evaluation,
            spot=spot,
            config_path=self._config_path,
        )

        with ArtifactWriteSession(paths, update_latest=update_latest) as session:
            session.write_parquet("glass_panorama.parquet", panorama)
            session.write_csv("glass_panorama.csv", panorama)
            session.write_text("glass_panorama.md", markdown)
            if not company_panel.is_empty():
                session.write_parquet("glass_company_panel.parquet", company_panel)
                session.write_csv("glass_company_panel.csv", company_panel)
            session.write_json("manifest.json", manifest)

        logger.info("玻璃全景对账管线完成: %s (as_of=%s)", paths.run_dir, as_of_date)
        return GlassRunResult(
            as_of_date=as_of_date,
            paths=paths,
            manifest=manifest,
            panorama=panorama,
            company_panel=company_panel,
            report_markdown=markdown,
        )


def _build_manifest(
    cfg: GlassConfig,
    as_of_date: date,
    paths: ArtifactRunPaths,
    panorama: pl.DataFrame,
    company_panel: pl.DataFrame,
    gate_evaluation: dict[str, Any],
    spot: dict[str, Any],
    config_path: Path | str | None,
) -> dict[str, Any]:
    manifest = build_manifest_base(
        artifact_type=_ARTIFACT_TYPE,
        schema_version=cfg.schema_version,
        title=cfg.title,
        run_id=paths.run_dir.name,
        as_of_date=as_of_date,
        artifact_root=str(paths.root),
        config_path=config_path or DEFAULT_CONFIG_PATH,
        watermarks={
            "nbs_plate_glass": _frame_watermark(panorama),
            "company_panel": _frame_watermark(company_panel),
        },
    )
    manifest["trading_gates"] = gate_evaluation
    manifest["spot_benchmarks"] = spot
    snapshot_row = latest_core_row(panorama)
    manifest["latest_snapshot"] = (
        [snapshot_row] if snapshot_row is not None else panorama.tail(1).to_dicts()
    )
    if not company_panel.is_empty():
        manifest["company_count"] = int(
            company_panel.select("symbol").n_unique() if "symbol" in company_panel.columns else 0
        )
    return manifest


def _frame_watermark(df: pl.DataFrame) -> dict[str, str | None]:
    col = "report_month" if "report_month" in df.columns else "trade_date"
    if df.is_empty() or col not in df.columns:
        return {"min": None, "max": None}
    vals = df[col].drop_nulls().unique().sort()
    if vals.len() == 0:
        return {"min": None, "max": None}
    return {"min": str(vals.first()), "max": str(vals.last())}


def _latest_month(panorama: pl.DataFrame) -> str:
    row = latest_core_row(panorama)
    if row is not None and row.get("report_month") is not None:
        return str(row["report_month"])
    months = panorama["report_month"].drop_nulls().unique().sort()
    if months.len() == 0:
        raise RuntimeError("玻璃全景表缺少 report_month 列或数据为空")
    return str(months.last())


def _parse_month_as_date(month: str) -> date:
    return date(int(month[:4]), int(month[5:7]), 1)


def run_glass_pipeline(
    *,
    as_of: date | None = None,
    config_path: Path | str | None = None,
    output_dir: Path | str | None = None,
    run_class: RunClass = "official",
    update_latest: bool = True,
    storage_dir: Path | str | None = None,
) -> GlassRunResult:
    runtime = DataRuntimeContext.from_root(storage_dir) if storage_dir else None
    pipeline = GlassPipeline(runtime=runtime, config=config_path)
    return pipeline.run(
        as_of=as_of,
        output_dir=output_dir,
        run_class=run_class,
        update_latest=update_latest,
    )


__all__ = [
    "GlassPipeline",
    "GlassRunResult",
    "run_glass_pipeline",
]
