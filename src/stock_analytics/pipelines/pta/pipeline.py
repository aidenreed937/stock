"""精对苯二甲酸 (PTA) 全景基本面对账与量化投研管线。

生产级标准管线：配置驱动、读取 → 合并 → 双雄 SOTP 测算 → 门禁裁决 → 研报渲染 → ArtifactStore 落盘 + manifest。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_analytics.marts.pta_company_panel import build_pta_company_panel
from stock_analytics.pipelines.artifacts import (
    ArtifactRunPaths,
    ArtifactStore,
    ArtifactWriteSession,
    RunClass,
    build_manifest_base,
)
from stock_analytics.pipelines.pta.config import (
    DEFAULT_CONFIG_PATH,
    PtaConfig,
    load_pta_config,
)
from stock_analytics.pipelines.pta.gates import (
    evaluate_trading_gates,
    load_trading_gates,
)
from stock_analytics.pipelines.pta.panorama import (
    aggregate_capacity_by_month,
    detect_regime_episodes,
    merge_monthly_panorama,
)
from stock_analytics.pipelines.pta.projections import (
    PtaCompanyProjectionEngine,
    PtaProjectionResult,
    build_financial_context,
)
from stock_analytics.pipelines.pta.report import render_markdown
from stock_analytics.pipelines.pta.sources import (
    DatasetReader,
    load_capacity_projects,
    load_company_panel,
    load_customs_export,
    load_futures_daily,
    load_pta_output,
    load_spot_price,
    load_spreads,
    load_synthetic_fiber,
    load_warehouse_receipts,
)
from stock_data.catalog import DataCatalog
from stock_data.core.runtime import DataRuntimeContext

logger = logging.getLogger(__name__)

_ARTIFACT_TYPE = "pta_panorama"


@dataclass(frozen=True, slots=True)
class PtaRunResult:
    """PTA 全景管线一次运行的结果。"""

    as_of_date: date
    paths: ArtifactRunPaths
    manifest: dict[str, Any]
    panorama: pl.DataFrame
    company_panel: pl.DataFrame
    report_markdown: str
    company_projections: pl.DataFrame | None = None


class PtaPipeline:
    """PTA 全景基本面对账与量化信号管线。"""

    def __init__(
        self,
        runtime: DataRuntimeContext | None = None,
        config: PtaConfig | Path | str | None = DEFAULT_CONFIG_PATH,
        catalog_factory: Callable[[str], DatasetReader] | None = None,
        config_path: Path | str | None = None,
    ) -> None:
        self.runtime = runtime or DataRuntimeContext.from_root("data")
        if config is None:
            config = DEFAULT_CONFIG_PATH
        if isinstance(config, PtaConfig):
            self.config = config
            self._config_path: Path | str | None = config_path
        else:
            self._config_path = config
            self.config = load_pta_config(config)
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
    ) -> PtaRunResult:
        """运行完整管线并落盘 CSV/Parquet/Markdown 与 Manifest。"""
        cfg = self.config
        catalog = self._catalog_factory("industry")

        # 1. 加载产能工程种子库
        projects = load_capacity_projects(cfg.inputs.capacity_projects)
        cap_increment = aggregate_capacity_by_month(projects)

        # 2. 加载供需实物量与期货/现货事实
        pta_output_df = load_pta_output(catalog, cfg.inputs.chemical_capacity_utilization_dataset)
        fiber_df = load_synthetic_fiber(
            catalog,
            cfg.inputs.chemical_capacity_utilization_dataset,
            cfg.inputs.chemical_market_dataset,
        )
        receipt_df = load_warehouse_receipts(catalog, cfg.inputs.futures_inventory_czce_dataset)
        futures_df = load_futures_daily(catalog, cfg.inputs.chemical_futures_daily_dataset)
        spot_df = load_spot_price(catalog, cfg.inputs.chemical_spot_price_dataset)
        spreads_df = load_spreads(catalog, cfg.inputs.chemical_spreads_dataset)
        export_df = load_customs_export(
            catalog, cfg.inputs.customs_trade_dataset, cfg.inputs.customs_trade_fallback
        )

        # 3. 关联并聚合月度全景表
        panorama_full = merge_monthly_panorama(
            pta_output_df=pta_output_df,
            fiber_df=fiber_df,
            cap_increment=cap_increment,
            receipt_df=receipt_df,
            futures_df=futures_df,
            spreads_df=spreads_df,
            export_df=export_df,
            high_profit_margin=cfg.history.high_profit_margin,
            deep_loss_margin=cfg.history.deep_loss_margin,
        )

        # 日期截断 (as_of)
        as_of_date = as_of or self._resolve_as_of_date(panorama_full, spot_df)
        as_of_month = as_of_date.isoformat()[:7]
        if not panorama_full.is_empty() and "report_month" in panorama_full.columns:
            panorama_df = panorama_full.filter(pl.col("report_month") <= as_of_month)
        else:
            panorama_df = panorama_full

        # 4. 加载上市公司面板与二级行业
        company_panel = load_company_panel(catalog, cfg.inputs.company_panel_dataset)
        if company_panel.is_empty() and build_company_fallback:
            try:
                tushare_cat = self._catalog_factory("tushare")
                if isinstance(tushare_cat, DataCatalog):
                    company_panel = build_pta_company_panel(catalog=tushare_cat)
            except Exception as exc:
                logger.debug(f"构建 PTA 上市公司回退失败: {exc}")

        # 5. 历史周期大拐点检测
        episodes = detect_regime_episodes(
            panorama_df,
            high_profit_threshold=cfg.history.high_profit_margin,
            deep_loss_threshold=cfg.history.deep_loss_margin,
            min_months=cfg.history.min_episode_months,
            max_episodes=cfg.history.max_episodes,
            follow_up_months=cfg.history.follow_up_months,
        )

        # 6. 量化交易门禁评估
        gates_cfg = load_trading_gates(cfg.inputs.trading_gates)
        gate_res = evaluate_trading_gates(
            panorama_df=panorama_df,
            company_panel=company_panel,
            gates_config=gates_cfg,
        )

        # 7. 双雄 (恒力石化 vs 桐昆股份) SOTP 分部测算引擎
        hengli_proj, tongkun_proj, sens_df, projections_df = self._run_projections(
            cfg.inputs.company_projections
        )

        # 8. 研报渲染
        report_md = render_markdown(
            panorama_df=panorama_df,
            projects=projects,
            gate_res=gate_res,
            company_panel=company_panel,
            hengli_projections=hengli_proj,
            tongkun_projections=tongkun_proj,
            sensitivity_df=sens_df,
            episodes=episodes,
            as_of=as_of_date.isoformat(),
        )

        # 9. ArtifactStore 事务写入与 Manifest 生成
        artifact_root = Path(output_dir) if output_dir is not None else Path(cfg.artifact_root)
        paths = ArtifactStore.build_run_paths(
            as_of_date=as_of_date, artifact_root=artifact_root, run_class=run_class
        )

        manifest = build_manifest_base(
            artifact_type=_ARTIFACT_TYPE,
            schema_version=cfg.schema_version,
            title=cfg.title,
            run_id=paths.run_dir.name,
            as_of_date=as_of_date,
            artifact_root=str(paths.root),
            config_path=self._config_path or DEFAULT_CONFIG_PATH,
        )
        manifest["pipeline_name"] = "pta_pipeline"
        manifest["regime_thresholds"] = asdict(cfg.regime)
        manifest["history_config"] = asdict(cfg.history)
        manifest["history_episodes"] = episodes
        manifest["trading_gates"] = gate_res
        manifest["panorama_months_count"] = len(panorama_df)
        manifest["outputs"] = {
            "panorama_csv": "panorama.csv",
            "panorama_parquet": "panorama.parquet",
            "report_md": "report.md",
            "company_projections_csv": "company_projections.csv",
        }

        with ArtifactWriteSession(paths, update_latest=update_latest) as session:
            session.write_parquet("pta_panorama.parquet", panorama_df)
            session.write_csv("pta_panorama.csv", panorama_df)
            session.write_parquet("panorama.parquet", panorama_df)
            session.write_csv("panorama.csv", panorama_df)
            session.write_text("pta_panorama.md", report_md)
            session.write_text("report.md", report_md)
            if not company_panel.is_empty():
                session.write_parquet("pta_company_panel.parquet", company_panel)
                session.write_csv("pta_company_panel.csv", company_panel)
            if projections_df is not None and not projections_df.is_empty():
                session.write_parquet("company_projections.parquet", projections_df)
                session.write_csv("company_projections.csv", projections_df)
            if sens_df is not None and not sens_df.is_empty():
                session.write_parquet("pta_profit_sensitivity.parquet", sens_df)
                session.write_csv("pta_profit_sensitivity.csv", sens_df)
            session.write_json("manifest.json", manifest)

        logger.info(f"PTA 全景对账管线完成: {paths.run_dir} (as_of={as_of_date})")

        return PtaRunResult(
            as_of_date=as_of_date,
            paths=paths,
            manifest=manifest,
            panorama=panorama_df,
            company_panel=company_panel,
            report_markdown=report_md,
            company_projections=projections_df,
        )

    def _run_projections(
        self,
        proj_config_path: str,
    ) -> tuple[
        list[PtaProjectionResult] | None,
        list[PtaProjectionResult] | None,
        pl.DataFrame | None,
        pl.DataFrame | None,
    ]:
        """运行双雄 SOTP 分部测算与敏感性分析。"""
        try:
            engine = PtaCompanyProjectionEngine(proj_config_path)
            if not engine.config:
                return None, None, None, None

            tushare_cat = None
            try:
                tushare_cat = self._catalog_factory("tushare")
                if not isinstance(tushare_cat, DataCatalog):
                    tushare_cat = DataCatalog("tushare")
            except Exception:
                tushare_cat = None

            # 恒力石化 600346.SH
            hl_ctx = build_financial_context("600346.SH", tushare_cat)
            hl_res = engine.project_all_scenarios("600346.SH", hl_ctx)

            # 桐昆股份 601233.SH
            tk_ctx = build_financial_context("601233.SH", tushare_cat)
            tk_res = engine.project_all_scenarios("601233.SH", tk_ctx)

            # 敏感性分析 (以恒力石化为例，PTA 现货价格 vs PX CFR 价格)
            sens_df = engine.generate_sensitivity_matrix(
                symbol="600346.SH",
                x_name="pta_price",
                x_values=[4800.0, 5200.0, 5600.0, 6000.0, 6400.0],
                y_name="px_price",
                y_values=[6800.0, 7200.0, 7600.0, 8000.0, 8400.0],
                base_scenario="mid_cycle",
                context=hl_ctx,
            )

            # 汇总双雄各情景为宽表
            summary_rows: list[dict[str, Any]] = []
            for r in hl_res + tk_res:
                summary_rows.append(
                    {
                        "symbol": r.symbol,
                        "company_name": r.company_name,
                        "scenario": r.scenario_key,
                        "scenario_name": r.scenario_name,
                        "total_revenue_cny": r.total_revenue_cny,
                        "total_gross_profit_cny": r.total_gross_profit_cny,
                        "finance_expense_cny": r.finance_expense_cny,
                        "equity_investment_income_cny": r.equity_investment_income_cny,
                        "net_profit_cny": r.net_profit_cny,
                        "eps_cny": r.eps_cny,
                        "fair_market_value_cny": r.fair_market_value_cny,
                        "fair_price_cny": r.fair_price_cny,
                        "target_pe": r.target_pe,
                        "target_pb": r.target_pb,
                        "implied_pb": r.implied_pb,
                        "valuation_method": r.valuation_method,
                        "implied_roe": r.implied_roe,
                    }
                )
            projections_df = pl.DataFrame(summary_rows) if summary_rows else None

            return hl_res, tk_res, sens_df, projections_df
        except Exception as exc:
            logger.warning(f"运行 PTA 双雄 SOTP 测算失败: {exc}")
            return None, None, None, None

    def _resolve_as_of_date(self, panorama: pl.DataFrame, spot_df: pl.DataFrame) -> date:
        """从全景表或现货事实确定管线基准日期。"""
        if not panorama.is_empty() and "report_month" in panorama.columns:
            m_val = panorama.get_column("report_month").drop_nulls().max()
            if m_val is not None:
                m = str(m_val)
                y, mon = int(m[:4]), int(m[5:7])
                import calendar

                _, last_day = calendar.monthrange(y, mon)
                return date(y, mon, last_day)
        return date.today()


def run_pta_pipeline(
    as_of: date | None = None,
    output_dir: Path | str | None = None,
    config: Path | str | None = None,
    run_class: RunClass = "official",
    update_latest: bool = True,
    storage_dir: Path | str | None = None,
    build_company_fallback: bool = True,
) -> PtaRunResult:
    """运行 PTA 全景管线的顶层便捷函数。"""
    runtime = (
        DataRuntimeContext.from_root(storage_dir)
        if storage_dir is not None
        else DataRuntimeContext.from_root("data")
    )
    pipe = PtaPipeline(runtime=runtime, config=config)
    return pipe.run(
        as_of=as_of,
        output_dir=output_dir,
        run_class=run_class,
        update_latest=update_latest,
        build_company_fallback=build_company_fallback,
    )


def load_latest_pta_panorama(
    artifact_root: Path | str = "data/analytics/pta",
) -> pl.DataFrame:
    """加载最新一期 PTA 全景事实表。"""
    latest_path = Path(artifact_root) / "latest" / "panorama.parquet"
    if latest_path.exists():
        return pl.read_parquet(latest_path)
    legacy_path = Path(artifact_root) / "latest" / "pta_panorama.parquet"
    if legacy_path.exists():
        return pl.read_parquet(legacy_path)
    return pl.DataFrame()
