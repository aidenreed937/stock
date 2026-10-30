"""钛白粉全景对账管线编排：读取 → 合并 → 门禁裁决 → 渲染 → ArtifactStore 落盘 + manifest。

对齐仓库既有工程化先例（纯碱/半导体/光伏/海关景气管线）：配置驱动、运行目录
``runs/as_of=.../run_.../`` + ``latest/`` + ``manifest.json``。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

import polars as pl
import yaml

from stock_analytics.marts.tio2_company_panel import (
    build_tio2_company_panel,
)
from stock_analytics.pipelines.artifacts import (
    ArtifactRunPaths,
    ArtifactStore,
    ArtifactWriteSession,
    RunClass,
    build_manifest_base,
)
from stock_analytics.pipelines.tio2.config import (
    DEFAULT_CONFIG_PATH,
    Tio2Config,
    load_tio2_config,
)
from stock_analytics.pipelines.tio2.gates import (
    evaluate_trading_gates,
    load_trading_gates,
)
from stock_analytics.pipelines.tio2.market_sources import (
    load_company_panel,
    load_industry_market,
    load_ma20_signal,
    load_monthly_survey,
    load_spreads,
    load_weekly_survey,
)
from stock_analytics.pipelines.tio2.panorama import (
    aggregate_capacity_by_month,
    detect_regime_episodes,
    merge_monthly_panorama,
)
from stock_analytics.pipelines.tio2.projections import CompanyProjectionEngine
from stock_analytics.pipelines.tio2.quarterly import QuarterlyProjectionEngine
from stock_analytics.pipelines.tio2.report import render_markdown
from stock_analytics.pipelines.tio2.sources import (
    DatasetReader,
    load_capacity_projects,
    load_customs_export,
    load_spot_price,
)
from stock_data.catalog import DataCatalog
from stock_data.core.runtime import DataRuntimeContext

logger = logging.getLogger(__name__)

_ARTIFACT_TYPE = "tio2_panorama"


@dataclass(frozen=True, slots=True)
class Tio2RunResult:
    """钛白粉全景管线一次运行的结果。"""

    as_of_date: date
    paths: ArtifactRunPaths
    manifest: dict[str, Any]
    panorama: pl.DataFrame
    company_panel: pl.DataFrame
    report_markdown: str
    company_projections: pl.DataFrame | None = None
    quarterly_projections: pl.DataFrame | None = None


class Tio2Pipeline:
    """钛白粉全景基本面对账与量化信号管线。"""

    def __init__(
        self,
        runtime: DataRuntimeContext | None = None,
        config: Tio2Config | Path | str | None = DEFAULT_CONFIG_PATH,
        catalog_factory: Callable[[str], DatasetReader] | None = None,
        config_path: Path | str | None = None,
    ) -> None:
        self.runtime = runtime or DataRuntimeContext.from_root("data")
        if config is None:
            config = DEFAULT_CONFIG_PATH
        if isinstance(config, Tio2Config):
            self.config = config
            self._config_path: Path | str | None = config_path
        else:
            self._config_path = config
            self.config = load_tio2_config(config)
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
    ) -> Tio2RunResult:
        """运行完整管线并落盘 CSV/Parquet/Markdown 与 Manifest。"""
        cfg = self.config
        catalog = self._catalog_factory("industry")

        projects = load_capacity_projects(cfg.inputs.capacity_projects)
        cap_increment = aggregate_capacity_by_month(projects)

        customs_df = load_customs_export(
            catalog, cfg.inputs.customs_trade_dataset, cfg.inputs.customs_trade_fallback
        )
        spot_df = load_spot_price(catalog, cfg.inputs.chemical_spot_price_dataset)
        spreads_df = load_spreads(catalog, cfg.inputs.chemical_spreads_dataset)
        weekly_survey_df = load_weekly_survey(catalog, cfg.inputs.chemical_weekly_survey_dataset)
        monthly_survey_df = load_monthly_survey(catalog, cfg.inputs.chemical_monthly_survey_dataset)
        ma20_df = load_ma20_signal(catalog, cfg.inputs.industry_l2_daily_dataset)
        industry_df = load_industry_market(catalog, cfg.inputs.industry_l2_daily_dataset)

        gates_cfg = load_trading_gates(cfg.inputs.trading_gates)

        fallback_fn: Callable[[], pl.DataFrame] | None = None
        if build_company_fallback:
            tushare_cat = self._catalog_factory("tushare")

            def _build_panel() -> pl.DataFrame:
                return build_tio2_company_panel(cast("DataCatalog", tushare_cat))

            fallback_fn = _build_panel

        company_panel = load_company_panel(
            catalog, cfg.inputs.company_panel_dataset, fallback_builder=fallback_fn
        )

        margin_fallback = _build_margin_fallback(cfg)

        panorama = merge_monthly_panorama(
            customs_df=customs_df,
            spot_df=spot_df,
            spreads_df=spreads_df,
            industry_df=industry_df,
            weekly_survey_df=weekly_survey_df,
            monthly_survey_df=monthly_survey_df,
            ma20_df=ma20_df,
            cap_increment=cap_increment,
            regime=cfg.regime,
            margin_fallback=margin_fallback,
        )

        # 空全景不注入占位数据：保持空表 → 渲染“无数据”报告，manifest 标记 data_status=empty（Ground Truth First）

        episodes = detect_regime_episodes(panorama, cfg.history)
        month_str = _latest_month(panorama)
        as_of_date = as_of or _parse_month_as_date(month_str)

        # 运行企业分部预测引擎与情景推演 (优先注入 TuShare 黄金财报事实表)
        proj_cfg_path = (
            cfg.inputs.company_projections if hasattr(cfg.inputs, "company_projections") else None
        )
        engine_cat: Any = None
        try:
            engine_cat = self._catalog_factory("tushare")
        except Exception as cat_exc:
            logger.debug(f"无法初始化 tushare catalog，以静态配置模式运行预测引擎: {cat_exc}")

        projection_engine = CompanyProjectionEngine(
            config_path=proj_cfg_path,
            catalog=engine_cat,
            as_of_date=as_of_date,
        )
        projection_results = projection_engine.project_all()
        projections_df = projection_engine.to_dataframe(projection_results)
        lb_grid_df = projection_engine.generate_profit_sensitivity_grid("002601.SZ")
        zh_grid_df = projection_engine.generate_profit_sensitivity_grid("002145.SZ")

        # 季度化引擎（Phase 2）：月频价格/成本/利用率路径 → Q1-Q4 归母净利
        quarterly_engine = QuarterlyProjectionEngine(projection_engine)
        quarterly_results: list[Any] = []
        for cid in ("002601.SZ", "002145.SZ"):
            for scen_key in ("current_spot", "trough", "mid_cycle", "peak"):
                quarterly_results.extend(quarterly_engine.project_quarters(cid, scen_key))
        quarterly_df = quarterly_engine.to_dataframe(quarterly_results)
        # Phase 0: 对账门禁（季度引擎 H1 模型 vs 最新实际中报）
        reconciliation = quarterly_engine.build_reconciliation(scenario_key="current_spot")

        audit_reports = projection_engine.audit_reconciliation(projection_results)
        pit_audit = projection_engine.build_pit_audit()

        # 门禁评估（置于分部预测之后）：左侧“边际产能亏损”改用公司边际口径，
        # 即钛能化学 current_spot 硫酸法单吨毛利（随 100ppi 酸价序列校准，当前深度为负）
        marginal_margin_cny: float | None = None
        marginal_margin_desc: str | None = None
        for r in projection_results:
            if r.symbol == "002145.SZ" and r.scenario_key == "current_spot":
                sulfate = next((s for s in r.segments if s.segment_key == "sulfate_tio2"), None)
                if sulfate is not None:
                    marginal_margin_cny = sulfate.unit_gross_margin_cny
                    marginal_margin_desc = (
                        f"边际产能(钛能化学)硫酸法单吨毛利: {sulfate.unit_gross_margin_cny:.0f} 元/吨 "
                        f"(售价 {sulfate.unit_price_cny:.0f} / 完全成本 {sulfate.unit_cost_cny:.0f})"
                    )
                break
        gate_evaluation = evaluate_trading_gates(
            panorama,
            company_panel,
            gates_cfg,
            cfg.regime,
            marginal_margin_cny=marginal_margin_cny,
            marginal_margin_desc=marginal_margin_desc,
        )

        # 生成核心龙头 EPS 置信带宽与敏感性矩阵
        confidence_bands = []
        try:
            for sym in ["002601.SZ", "002145.SZ"]:
                band = projection_engine.compute_confidence_band(sym, "mid_cycle")
                confidence_bands.append(band)
        except Exception as band_exc:
            logger.debug(f"置信带宽推演跳过: {band_exc}")

        markdown = render_markdown(
            panorama=panorama,
            projects=projects,
            company_panel=company_panel,
            episodes=episodes,
            gate_evaluation=gate_evaluation,
            config=cfg,
            projection_results=projection_results,
            lb_sensitivity_grid=lb_grid_df,
            zh_sensitivity_grid=zh_grid_df,
            audit_reports=audit_reports,
            confidence_bands=confidence_bands,
            pit_audit=pit_audit,
            quarterly_df=quarterly_df,
            reconciliation=reconciliation,
        )

        artifact_root = Path(output_dir) if output_dir is not None else Path(cfg.artifact_root)
        paths = ArtifactStore.build_run_paths(
            as_of_date=as_of_date, artifact_root=artifact_root, run_class=run_class
        )
        manifest = _build_manifest(
            config=cfg,
            as_of_date=as_of_date,
            paths=paths,
            panorama=panorama,
            company_panel=company_panel,
            episodes=episodes,
            gate_evaluation=gate_evaluation,
            config_path=self._config_path,
            projections_df=projections_df,
            pit_audit=pit_audit,
            quarterly_df=quarterly_df,
        )
        manifest["reconciliation"] = reconciliation

        with ArtifactWriteSession(paths, update_latest=update_latest) as session:
            session.write_parquet("tio2_panorama.parquet", panorama)
            session.write_csv("tio2_panorama.csv", panorama)
            session.write_text("tio2_panorama.md", markdown)
            if not company_panel.is_empty():
                session.write_parquet("tio2_company_panel.parquet", company_panel)
                session.write_csv("tio2_company_panel.csv", company_panel)
            session.write_parquet("company_projections.parquet", projections_df)
            session.write_csv("company_projections.csv", projections_df)
            if not quarterly_df.is_empty():
                session.write_parquet("quarterly_projections.parquet", quarterly_df)
                session.write_csv("quarterly_projections.csv", quarterly_df)
            session.write_parquet("lb_profit_sensitivity.parquet", lb_grid_df)
            session.write_csv("lb_profit_sensitivity.csv", lb_grid_df)
            session.write_parquet("zh_profit_sensitivity.parquet", zh_grid_df)
            session.write_csv("zh_profit_sensitivity.csv", zh_grid_df)
            session.write_json("manifest.json", manifest)

        logger.info("钛白粉全景对账管线完成: %s (as_of=%s)", paths.run_dir, as_of_date)
        return Tio2RunResult(
            as_of_date=as_of_date,
            paths=paths,
            manifest=manifest,
            panorama=panorama,
            company_panel=company_panel,
            report_markdown=markdown,
            company_projections=projections_df,
            quarterly_projections=quarterly_df,
        )


def _build_margin_fallback(config: Tio2Config) -> dict[str, float] | None:
    """构建配置驱动的毛利兜底参数（价差数据集缺失时使用）。

    综合成本线取 company_projections.yaml 钛能化学（边际）中周期基准，
    利润带取 tio2/cost_models.yaml 的 regime_thresholds；任一读取失败返回 None（不做估算）。
    """
    try:
        proj_path = Path(config.inputs.company_projections)
        cost_path = Path(config.inputs.cost_models)
        proj = yaml.safe_load(proj_path.read_text(encoding="utf-8")) or {}
        cost = yaml.safe_load(cost_path.read_text(encoding="utf-8")) or {}
        seg = proj["companies"]["002145.SZ"]["segments"]["sulfate_tio2"]
        scen = proj["scenarios"]["mid_cycle"]
        cost_line = (
            float(seg["ore_consumption"]) * float(scen["ilmenite_market_price"])
            + float(seg["sulfate_acid_coeff"]) * float(scen["acid_price"])
            + float(seg["fixed_cost"])
            - float(seg.get("byproduct_credit", 0.0))
        )
        thresholds = cost.get("regime_thresholds", {})
        return {
            "cost_line_cny": cost_line,
            "high_profit": float(thresholds.get("high_profit", 2000.0)),
            "profitable": float(thresholds.get("profitable", 500.0)),
            "near_breakeven": float(thresholds.get("near_breakeven", -500.0)),
        }
    except Exception:
        return None


def _build_manifest(
    config: Tio2Config,
    as_of_date: date,
    paths: ArtifactRunPaths,
    panorama: pl.DataFrame,
    company_panel: pl.DataFrame,
    episodes: list[dict[str, Any]],
    gate_evaluation: dict[str, Any],
    config_path: Path | str | None,
    projections_df: pl.DataFrame | None = None,
    pit_audit: list[dict[str, Any]] | None = None,
    quarterly_df: pl.DataFrame | None = None,
) -> dict[str, Any]:
    """构建钛白粉全景管线 manifest。"""
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
        "export_flow": "GACC 320611 海关出口量价与增速",
        "margin": "tio2/cost_models.yaml 硫酸法与氯化法成本利润状态机 (品种级唯一维护源)",
        "flow_regime": "出口增速 + 现货价格变动 寡头蓄水池状态机",
        "trading_gates": "tio2/trading_gates.yaml 品种级寡头门禁 (唯一维护源；门面仅保留 B 类通用模板)",
        "margin_fallback": "价差缺失时按 company_projections 中周期成本线 + tio2/cost_models 利润带推导 (配置驱动)",
        "company_projections": "company_projections.yaml SOTP 自下而上分部预测与 OPEX Bridge",
    }
    manifest["regime_thresholds"] = asdict(config.regime)
    manifest["history_config"] = asdict(config.history)
    manifest["history_episodes"] = episodes
    manifest["trading_gates"] = gate_evaluation
    manifest["pit_audit"] = pit_audit or []
    manifest["data_status"] = "empty" if panorama.is_empty() else "ok"
    manifest["latest_snapshot"] = panorama.tail(1).to_dicts()
    if projections_df is not None and not projections_df.is_empty():
        manifest["company_projections"] = projections_df.to_dicts()
    if quarterly_df is not None and not quarterly_df.is_empty():
        manifest["quarterly_projections"] = quarterly_df.to_dicts()
    if not company_panel.is_empty():
        manifest["company_count"] = int(
            company_panel.select("symbol").n_unique() if "symbol" in company_panel.columns else 0
        )
    return manifest


def _build_watermarks(
    panorama: pl.DataFrame,
    company_panel: pl.DataFrame,
) -> dict[str, dict[str, str | None]]:
    frames: dict[str, pl.DataFrame] = {
        "panorama": panorama,
        "company_panel": company_panel,
    }
    watermarks: dict[str, dict[str, str | None]] = {}
    for name, frame in frames.items():
        watermarks[name] = _frame_watermark(frame)
    return watermarks


def _frame_watermark(frame: pl.DataFrame) -> dict[str, str | None]:
    if frame.is_empty():
        return {"min": None, "max": None}
    date_cols = ("report_month", "trade_date", "date", "period")
    for col in date_cols:
        if col in frame.columns:
            series = frame.get_column(col).drop_nulls()
            if not series.is_empty():
                return {
                    "min": str(series.min()),
                    "max": str(series.max()),
                }
    return {"min": None, "max": None}


def _latest_month(df: pl.DataFrame) -> str:
    if "report_month" in df.columns:
        months = df.get_column("report_month").drop_nulls().to_list()
        if months:
            return str(months[-1])
    return date.today().strftime("%Y-%m")


def _parse_month_as_date(month_str: str) -> date:
    try:
        parts = month_str.split("-")
        return date(int(parts[0]), int(parts[1]), 1)
    except Exception:
        return date.today().replace(day=1)


def run_tio2_pipeline(
    as_of: date | None = None,
    output_dir: Path | str | None = None,
    config: Path | str | None = None,
    run_class: RunClass = "official",
    update_latest: bool = True,
    storage_dir: Path | str | None = None,
    build_company_fallback: bool = True,
) -> Tio2RunResult:
    """运行钛白粉全景管线的顶层便捷函数。"""
    runtime = (
        DataRuntimeContext.from_root(storage_dir)
        if storage_dir is not None
        else DataRuntimeContext.from_root("data")
    )
    pipe = Tio2Pipeline(runtime=runtime, config=config)
    return pipe.run(
        as_of=as_of,
        output_dir=output_dir,
        run_class=run_class,
        update_latest=update_latest,
        build_company_fallback=build_company_fallback,
    )


def load_latest_tio2_panorama(
    artifact_root: Path | str = "data/analytics/tio2",
) -> pl.DataFrame:
    """加载最新一期钛白粉全景事实表。"""
    latest_path = Path(artifact_root) / "latest" / "tio2_panorama.parquet"
    if latest_path.exists():
        return pl.read_parquet(latest_path)
    return pl.DataFrame()
