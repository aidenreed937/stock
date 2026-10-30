"""聚氯乙烯 (PVC / V) 全景基本面对账管线编排：读取 → 合并 → 诊断 → 渲染 → ArtifactStore 落盘 + manifest。

对齐仓库既有工程化先例（半导体/纯碱/海关出口管线）：
配置驱动、运行目录 ``runs/as_of=.../run_.../`` + ``latest/`` + ``manifest.json``。
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime
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
from stock_analytics.pipelines.pvc.company import (
    build_pvc_company_panel,
    load_pvc_companies_config,
)
from stock_analytics.pipelines.pvc.config import (
    DEFAULT_CONFIG_PATH,
    PVCConfig,
    load_pvc_config,
)
from stock_analytics.pipelines.pvc.gates import (
    PVCTradingGatesSummary,
    evaluate_pvc_trading_gates,
)
from stock_analytics.pipelines.pvc.panorama import (
    build_pvc_monthly_panorama,
    detect_pvc_regime_episodes,
)
from stock_analytics.pipelines.pvc.report import render_pvc_markdown_report
from stock_analytics.pipelines.pvc.sources import (
    load_pvc_basis_mart,
    load_pvc_capacity_projects,
    load_pvc_cost_models,
    load_pvc_customs_export,
    load_pvc_warehouse_receipts,
    load_pvc_weekly_survey,
)
from stock_data.catalog import DataCatalog
from stock_data.core.runtime import DataRuntimeContext

logger = logging.getLogger(__name__)

_ARTIFACT_TYPE = "pvc_panorama"


@dataclass(frozen=True, slots=True)
class PVCRunResult:
    """PVC 全景管线一次运行的结果。"""

    as_of_date: date
    paths: ArtifactRunPaths
    manifest: dict[str, Any]
    panorama: pl.DataFrame
    company_panel: pl.DataFrame
    gates_summary: PVCTradingGatesSummary
    report_markdown: str


class PVCPipeline:
    """聚氯乙烯全景基本面对账与量化信号管线。"""

    def __init__(
        self,
        runtime: DataRuntimeContext | None = None,
        config: PVCConfig | Path | str | None = DEFAULT_CONFIG_PATH,
        config_path: Path | str | None = None,
    ) -> None:
        self.runtime = runtime or DataRuntimeContext.from_root("data")
        if config is None:
            config = DEFAULT_CONFIG_PATH
        if isinstance(config, PVCConfig):
            self.config = config
            self._config_path: Path | str | None = config_path
        else:
            self._config_path = config
            self.config = load_pvc_config(config)

    def run(
        self,
        as_of: date | None = None,
        output_dir: Path | str | None = None,
        run_class: RunClass = "official",
        update_latest: bool = True,
    ) -> PVCRunResult:
        """运行完整管线并落盘 CSV/Parquet/Markdown 与 Manifest。"""
        cfg = self.config
        curated_root = self.runtime.curated_root

        projects = load_pvc_capacity_projects(cfg.inputs.capacity_projects)
        cost_models = load_pvc_cost_models(cfg.inputs.cost_models)
        receipt_df = load_pvc_warehouse_receipts(curated_root)
        weekly_survey_df = load_pvc_weekly_survey(curated_root)
        customs_df = load_pvc_customs_export(curated_root)
        basis_df = load_pvc_basis_mart(curated_root)

        # 构造月度全景表
        panorama = build_pvc_monthly_panorama(
            customs_df=customs_df,
            receipt_df=receipt_df,
            basis_df=basis_df,
            weekly_survey_df=weekly_survey_df,
            regime_cfg=cfg.regime,
        )
        if panorama.is_empty():
            raise RuntimeError("PVC 全景表为空：缺少核心海关或期货基差/仓单输入")

        episodes = detect_pvc_regime_episodes(panorama, cfg.history)

        # 上市公司估值时钟面板
        tushare_catalog = DataCatalog(data_source="tushare", storage_dir=curated_root)
        companies_cfg = load_pvc_companies_config(cfg.inputs.companies)
        company_panel = build_pvc_company_panel(
            catalog=tushare_catalog,
            companies=companies_cfg,
            as_of_date=as_of,
        )

        # 确定基准日期
        latest_row = panorama.tail(1).to_dicts()[0]
        if as_of is not None:
            as_of_date = as_of
        else:
            month_str = latest_row.get("report_month", "2026-09")
            as_of_date = _parse_month_as_date(month_str)

        # 提取指标执行三门禁诊断
        spot_price = float(latest_row.get("spot_price_monthly_mean") or 4710.0)
        basis_rate = (
            float(latest_row["basis_rate_month_end"])
            if latest_row.get("basis_rate_month_end") is not None
            else None
        )
        warehouse_w_tons = (
            float(latest_row["warehouse_w_tons_month_end"])
            if latest_row.get("warehouse_w_tons_month_end") is not None
            else None
        )
        export_vol_yoy = (
            float(latest_row["export_volume_yoy_pct"])
            if latest_row.get("export_volume_yoy_pct") is not None
            else None
        )
        op_rate = (
            float(latest_row["operating_rate_monthly_mean"])
            if latest_row.get("operating_rate_monthly_mean") is not None
            else None
        )

        min_pb_abs = None
        min_pb_10y = None
        min_pe = None
        if not company_panel.is_empty():
            pb_list = [float(x) for x in company_panel.get_column("pb").to_list() if x is not None]
            pb_pct_list = [
                float(x)
                for x in company_panel.get_column("pb_percentile_10y").to_list()
                if x is not None
            ]
            pe_list = [
                float(x)
                for x in company_panel.get_column("pe_ttm").to_list()
                if x is not None and float(x) > 0
            ]
            if pb_list:
                min_pb_abs = min(pb_list)
            if pb_pct_list:
                min_pb_10y = min(pb_pct_list)
            if pe_list:
                min_pe = min(pe_list)

        gates_summary = evaluate_pvc_trading_gates(
            spot_price_cny=spot_price,
            cash_cost_cny=5100.0,
            operating_rate_pct=op_rate,
            destocking_weeks=0,
            basis_rate_pct=basis_rate,
            warehouse_w_tons=warehouse_w_tons,
            export_vol_yoy_pct=export_vol_yoy,
            min_pb_10y_pct=min_pb_10y,
            min_pb_abs=min_pb_abs,
            pe_ttm_low=min_pe,
            config_path=cfg.inputs.trading_gates,
            as_of_date_str=as_of_date.isoformat(),
        )

        # 渲染 Markdown 报告
        markdown = render_pvc_markdown_report(
            monthly_panorama=panorama,
            company_panel=company_panel,
            gates_summary=gates_summary,
            episodes=episodes,
            cost_models=cost_models,
            capacity_projects=projects,
            as_of_date_str=as_of_date.isoformat(),
        )

        # 写入 ArtifactStore
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
            episodes=episodes,
            gates_summary=gates_summary,
            config_path=self._config_path,
        )

        with ArtifactWriteSession(paths, update_latest=update_latest) as session:
            session.write_parquet("pvc_monthly_panorama.parquet", panorama)
            session.write_csv("pvc_monthly_panorama.csv", panorama)
            session.write_text("pvc_report.md", markdown)
            if not company_panel.is_empty():
                session.write_parquet("pvc_company_panel.parquet", company_panel)
                session.write_csv("pvc_company_panel.csv", company_panel)
            session.write_json("manifest.json", manifest)

        logger.info("PVC 全景对账管线运行完成: %s (as_of=%s)", paths.run_dir, as_of_date)
        return PVCRunResult(
            as_of_date=as_of_date,
            paths=paths,
            manifest=manifest,
            panorama=panorama,
            company_panel=company_panel,
            gates_summary=gates_summary,
            report_markdown=markdown,
        )


def _parse_month_as_date(month_str: str) -> date:
    try:
        parts = month_str.split("-")
        return date(int(parts[0]), int(parts[1]), 28)
    except Exception:
        return datetime.now().date()


def _build_manifest(
    cfg: PVCConfig,
    as_of_date: date,
    paths: ArtifactRunPaths,
    panorama: pl.DataFrame,
    company_panel: pl.DataFrame,
    episodes: list[dict[str, Any]],
    gates_summary: PVCTradingGatesSummary,
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
        watermarks=_build_watermarks(panorama, company_panel),
    )
    manifest["methodology"] = {
        "cost_curve": "pvc/cost_models.yaml 电石法现金成本 (5100) / 完全成本 (5600)",
        "flow_regime": "大商所交割仓单 + 3年分位数 + 基差结构 + 海关出口",
        "trading_gates": "pvc/trading_gates.yaml 左侧赔率 / 右侧胜率 / 逃顶否决",
    }
    manifest["regime_thresholds"] = asdict(cfg.regime)
    manifest["history_config"] = asdict(cfg.history)
    manifest["history_episodes"] = episodes
    manifest["trading_gates_summary"] = {
        "current_stance": gates_summary.current_stance,
        "advice": gates_summary.overall_action_advice,
        "left_side_triggered": gates_summary.left_side.is_triggered,
        "right_side_triggered": gates_summary.right_side.is_triggered,
        "top_escape_triggered": gates_summary.top_escape.is_triggered,
    }
    manifest["latest_snapshot"] = panorama.tail(1).to_dicts()
    if not company_panel.is_empty():
        manifest["company_count"] = int(
            company_panel.select("symbol").n_unique() if "symbol" in company_panel.columns else 0
        )
    return manifest


def _build_watermarks(panorama: pl.DataFrame, company_panel: pl.DataFrame) -> dict[str, Any]:
    watermarks: dict[str, Any] = {}
    if not panorama.is_empty() and "report_month" in panorama.columns:
        watermarks["panorama_max_month"] = panorama["report_month"].max()
    if not company_panel.is_empty() and "trade_date" in company_panel.columns:
        watermarks["company_max_trade_date"] = str(company_panel["trade_date"].max())
    return watermarks


__all__ = ["PVCPipeline", "PVCRunResult"]
