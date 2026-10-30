"""纯碱全景对账管线编排：读取 → 合并 → 渲染 → ArtifactStore 落盘 + manifest。

对齐仓库既有工程化先例（半导体/光伏/海关景气管线）：配置驱动、运行目录
``runs/as_of=.../run_.../`` + ``latest/`` + ``manifest.json``（完整性/水位），
供策略与研究层经 ``load_latest_soda_ash_panorama`` 消费，禁止直接拼接物理路径。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
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
from stock_analytics.pipelines.soda_ash.config import (
    DEFAULT_CONFIG_PATH,
    SodaAshConfig,
    load_soda_ash_config,
)
from stock_analytics.pipelines.soda_ash.gates import (
    evaluate_trading_gates,
    load_trading_gates,
)
from stock_analytics.pipelines.soda_ash.market_sources import (
    load_company_panel,
    load_futures_daily,
    load_hold_rank,
    load_spot_benchmark,
    load_spreads,
)
from stock_analytics.pipelines.soda_ash.panorama import (
    aggregate_capacity_by_month,
    detect_regime_episodes,
    latest_core_row,
    merge_monthly_panorama,
)
from stock_analytics.pipelines.soda_ash.report import render_markdown
from stock_analytics.pipelines.soda_ash.sources import (
    DatasetReader,
    load_capacity_projects,
    load_customs_export,
    load_factory_inventory,
    load_nbs_plate_glass,
    load_nbs_soda_ash,
    load_warehouse_receipts,
)
from stock_data.catalog import DataCatalog
from stock_data.core.runtime import DataRuntimeContext

logger = logging.getLogger(__name__)

_ARTIFACT_TYPE = "soda_ash_panorama"


@dataclass(frozen=True, slots=True)
class SodaAshRunResult:
    """纯碱全景管线一次运行的结果。"""

    as_of_date: date
    paths: ArtifactRunPaths
    manifest: dict[str, Any]
    panorama: pl.DataFrame
    company_panel: pl.DataFrame
    report_markdown: str


class SodaAshPipeline:
    """纯碱全景基本面对账与量化信号管线。"""

    def __init__(
        self,
        runtime: DataRuntimeContext | None = None,
        config: SodaAshConfig | Path | str | None = DEFAULT_CONFIG_PATH,
        catalog_factory: Callable[[str], DatasetReader] | None = None,
        config_path: Path | str | None = None,
    ) -> None:
        self.runtime = runtime or DataRuntimeContext.from_root("data")
        if config is None:
            config = DEFAULT_CONFIG_PATH
        if isinstance(config, SodaAshConfig):
            self.config = config
            self._config_path: Path | str | None = config_path
        else:
            self._config_path = config
            self.config = load_soda_ash_config(config)
        self._catalog_factory = catalog_factory or (
            lambda source: DataCatalog(data_source=source, storage_dir=self.runtime.curated_root)
        )

    def run(
        self,
        as_of: date | None = None,
        output_dir: Path | str | None = None,
        run_class: RunClass = "official",
        update_latest: bool = True,
        build_company_fallback: bool = True,
    ) -> SodaAshRunResult:
        """运行完整管线并落盘 CSV/Parquet/Markdown 与 Manifest。"""
        cfg = self.config
        catalog = self._catalog_factory("industry")

        projects = load_capacity_projects(cfg.inputs.capacity_projects)
        cap_increment = aggregate_capacity_by_month(projects)

        soda_df = load_nbs_soda_ash(cfg.inputs.nbs_soda_ash_csv)
        glass_df = load_nbs_plate_glass(cfg.inputs.nbs_plate_glass_csv)
        customs_df = load_customs_export(
            catalog, cfg.inputs.customs_trade_dataset, cfg.inputs.customs_trade_fallback
        )
        receipt_df = load_warehouse_receipts(catalog, cfg.inputs.futures_inventory_dataset)
        factory_df = load_factory_inventory(catalog, cfg.inputs.chemical_weekly_survey_dataset)
        spreads_df = load_spreads(catalog, cfg.inputs.chemical_spreads_dataset)
        futures_df = load_futures_daily(catalog, cfg.inputs.futures_daily_dataset)
        hold_rank_df = load_hold_rank(catalog, cfg.inputs.futures_hold_rank_dataset)
        spot = load_spot_benchmark(
            catalog, cfg.inputs.chemical_spot_price_dataset, cfg.inputs.futures_daily_dataset
        )
        gates_cfg = load_trading_gates(cfg.inputs.trading_gates)

        tushare_factory = (
            (lambda: self._catalog_factory("tushare")) if build_company_fallback else None
        )
        company_panel = load_company_panel(
            catalog, cfg.inputs.company_panel_dataset, tushare_factory=tushare_factory
        )

        panorama = merge_monthly_panorama(
            soda_df=soda_df,
            glass_df=glass_df,
            customs_df=customs_df,
            cap_increment=cap_increment,
            receipt_df=receipt_df,
            factory_df=factory_df,
            spreads_df=spreads_df,
            futures_df=futures_df,
            hold_rank_df=hold_rank_df,
            regime=cfg.regime,
        )
        if panorama.is_empty():
            raise RuntimeError("纯碱全景表为空：NBS 核心输入缺失或无有效月份")

        # --as-of 贯通：按 as_of 截断全景表，使研报基准与季节性门禁一起回到目标月，
        # 而非始终取最新完整月（此前 --as-of 仅影响产物落盘路径，属静默无效）。
        if as_of is not None:
            as_of_month = f"{as_of.year:04d}-{as_of.month:02d}"
            panorama = panorama.filter(pl.col("report_month") <= pl.lit(as_of_month))
            if panorama.is_empty():
                raise RuntimeError(f"纯碱全景表为空：as_of={as_of} 之前无有效月份")

        episodes = detect_regime_episodes(panorama, cfg.history)
        gate_evaluation = evaluate_trading_gates(panorama, company_panel, spot, gates_cfg)
        month_str = _latest_month(panorama)
        as_of_date = as_of or _parse_month_as_date(month_str)
        markdown = render_markdown(
            panorama,
            projects,
            company_panel,
            spot,
            episodes,
            gate_evaluation,
            cfg,
        )

        artifact_root = Path(output_dir) if output_dir is not None else Path(cfg.artifact_root)
        paths = ArtifactStore.build_run_paths(
            as_of_date=as_of_date, artifact_root=artifact_root, run_class=run_class
        )
        manifest = _build_manifest(
            cfg,
            as_of_date,
            paths,
            panorama,
            company_panel,
            episodes,
            gate_evaluation,
            spot,
            self._config_path,
        )

        with ArtifactWriteSession(paths, update_latest=update_latest) as session:
            session.write_parquet("soda_ash_panorama.parquet", panorama)
            session.write_csv("soda_ash_panorama.csv", panorama)
            session.write_text("soda_ash_panorama.md", markdown)
            if not company_panel.is_empty():
                session.write_parquet("soda_ash_company_panel.parquet", company_panel)
                session.write_csv("soda_ash_company_panel.csv", company_panel)
            session.write_json("manifest.json", manifest)

        logger.info("纯碱全景对账管线完成: %s (as_of=%s)", paths.run_dir, as_of_date)
        return SodaAshRunResult(
            as_of_date=as_of_date,
            paths=paths,
            manifest=manifest,
            panorama=panorama,
            company_panel=company_panel,
            report_markdown=markdown,
        )


def _build_manifest(
    config: SodaAshConfig,
    as_of_date: date,
    paths: ArtifactRunPaths,
    panorama: pl.DataFrame,
    company_panel: pl.DataFrame,
    episodes: list[dict[str, Any]],
    gate_evaluation: dict[str, Any],
    spot: dict[str, Any],
    config_path: Path | str | None,
) -> dict[str, Any]:
    """构建纯碱全景管线 manifest（水位 + 阈值 + 最新截面 + 拐点）。"""
    manifest = build_manifest_base(
        artifact_type=_ARTIFACT_TYPE,
        schema_version=config.schema_version,
        title=config.title,
        run_id=paths.run_dir.name,
        as_of_date=as_of_date,
        artifact_root=str(paths.root),
        config_path=config_path or DEFAULT_CONFIG_PATH,
        watermarks=_build_watermarks(panorama, company_panel),
    )
    manifest["methodology"] = {
        "scissors": "glass_output_yoy - soda_output_yoy",
        "margin": "soda_ash/cost_models.yaml 联碱双吨/氨碱法成本利润状态机",
        "flow_regime": "厂库变动 + 出货率 + 仓单增量 + 基差 + 开工率 状态机",
        "history": "利润状态机连续期识别（数据实证）+ 机制推断",
    }
    manifest["regime_thresholds"] = asdict(config.regime)
    manifest["history_config"] = asdict(config.history)
    manifest["history_episodes"] = episodes
    manifest["trading_gates"] = gate_evaluation
    snapshot_row = latest_core_row(panorama)
    manifest["latest_snapshot"] = (
        [snapshot_row] if snapshot_row is not None else panorama.tail(1).to_dicts()
    )
    if not company_panel.is_empty():
        manifest["company_count"] = int(
            company_panel.select("symbol").n_unique() if "symbol" in company_panel.columns else 0
        )
    manifest["spot_benchmark"] = spot
    return manifest


def _build_watermarks(
    panorama: pl.DataFrame,
    company_panel: pl.DataFrame,
) -> dict[str, dict[str, str | None]]:
    """提取各输入侧数据水位（report_month/trade_date min/max）。"""
    frames: dict[str, pl.DataFrame] = {
        "nbs_soda_ash": panorama,
        "company_panel": company_panel,
    }
    watermarks: dict[str, dict[str, str | None]] = {}
    for name, frame in frames.items():
        watermarks[name] = _frame_watermark(frame)
    return watermarks


def _frame_watermark(df: pl.DataFrame) -> dict[str, str | None]:
    col = "report_month" if "report_month" in df.columns else "trade_date"
    if df.is_empty() or col not in df.columns:
        return {"min": None, "max": None}
    vals = df[col].drop_nulls().unique().sort()
    if vals.len() == 0:
        return {"min": None, "max": None}
    return {"min": str(vals.first()), "max": str(vals.last())}


def _latest_month(panorama: pl.DataFrame) -> str:
    """取最近一个核心产量非空的月份作为报告基准月（跳过待发布尾行）。"""
    row = latest_core_row(panorama)
    if row is not None and row.get("report_month") is not None:
        return str(row["report_month"])
    months = panorama["report_month"].drop_nulls().unique().sort()
    if months.len() == 0:
        raise RuntimeError("纯碱全景表缺少 report_month 列或数据为空")
    return str(months.last())


def _parse_month_as_date(month: str) -> date:
    try:
        return date(int(month[:4]), int(month[5:7]), 1)
    except (ValueError, IndexError) as exc:
        raise ValueError(f"无法解析报告月份: {month!r}") from exc


def run_soda_ash_pipeline(
    *,
    as_of: date | None = None,
    config_path: Path | str | None = None,
    output_dir: Path | str | None = None,
    run_class: RunClass = "official",
    update_latest: bool = True,
    storage_dir: Path | str | None = None,
    build_company_fallback: bool = True,
) -> SodaAshRunResult:
    """运行纯碱全景对账管线便捷函数（config_path=None 使用默认配置）。"""
    runtime = DataRuntimeContext.from_root(storage_dir) if storage_dir else None
    pipeline = SodaAshPipeline(runtime=runtime, config=config_path)
    return pipeline.run(
        as_of=as_of,
        output_dir=output_dir,
        run_class=run_class,
        update_latest=update_latest,
        build_company_fallback=build_company_fallback,
    )


def load_latest_soda_ash_panorama(
    artifact_root: Path | str | None = None,
) -> pl.DataFrame:
    """读取纯碱全景管线 latest 产物面板（经 Artifact Reader 定位）。"""
    from stock_analytics.pipelines.artifacts.reader import resolve_artifact_run

    root = Path(artifact_root) if artifact_root else Path("data/analytics/soda_ash")
    try:
        run_dir = resolve_artifact_run(
            root, as_of_date="latest", expected_artifact_type=_ARTIFACT_TYPE
        ).run_dir
    except Exception as exc:  # noqa: BLE001
        raise FileNotFoundError(
            f"未找到纯碱全景产物 {root}（先运行 run_soda_ash_pipeline）"
        ) from exc
    path = run_dir / "soda_ash_panorama.parquet"
    if not path.exists():
        raise FileNotFoundError(f"纯碱全景产物缺面板: {path}")
    return pl.read_parquet(path)


__all__ = [
    "SodaAshPipeline",
    "SodaAshRunResult",
    "load_latest_soda_ash_panorama",
    "run_soda_ash_pipeline",
]
