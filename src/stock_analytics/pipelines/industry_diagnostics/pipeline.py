"""中观产业深度诊断与全景量化体检核心管线。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from stock_analytics.pipelines.artifacts import (
    ArtifactStore,
    ArtifactWriteSession,
    RunClass,
    build_manifest_base,
)
from stock_analytics.pipelines.industry_diagnostics.config import (
    DEFAULT_CONFIG_PATH,
    IndustryDiagnosticsConfig,
    load_industry_diagnostics_config,
)
from stock_analytics.pipelines.industry_diagnostics.sources import (
    build_industry_technicals,
    build_industry_valuation,
    load_industry_constituents,
    load_value_chain_map,
    resolve_industry_meta,
)
from stock_analytics.pipelines.industry_diagnostics.types import (
    IndustryDiagnosticsResult,
    IndustryFinancialsSnapshot,
)
from stock_core.utils.logger import logger
from stock_data.catalog import DataCatalog
from stock_data.core.runtime import DataRuntimeContext
from stock_reporting.templates.industry_diagnostics_report import (
    render_industry_diagnostics_report,
)


class IndustryDiagnosticsPipeline:
    """中观产业量化诊断管线。"""

    def __init__(
        self,
        runtime: DataRuntimeContext | None = None,
        config: IndustryDiagnosticsConfig | Path | str | None = None,
        config_path: Path | str = DEFAULT_CONFIG_PATH,
    ) -> None:
        self.runtime = runtime or DataRuntimeContext.from_root("data")
        self.cat_tu = DataCatalog(data_source="tushare", runtime=self.runtime)
        self.cat_lx = DataCatalog(data_source="lixinger", runtime=self.runtime)

        if isinstance(config, IndustryDiagnosticsConfig):
            self.config = config
            self._config_path = str(config_path)
        elif config is not None:
            self.config = load_industry_diagnostics_config(config)
            self._config_path = str(config)
        else:
            self.config = load_industry_diagnostics_config(config_path)
            self._config_path = str(config_path)

    def run(
        self,
        industry: str,
        target_date: date | None = None,
        output_dir: Path | str | None = None,
        update_latest: bool = True,
        run_class: RunClass = "official",
    ) -> IndustryDiagnosticsResult:
        """执行申万中观产业全景量化诊断。"""
        std_code, std_name, level, _raw_code = resolve_industry_meta(self.cat_tu, industry)

        # 1. 加载行业行情
        sw_df = self.cat_tu.load_dataset("sw_daily", symbols=[std_code])
        if not sw_df.is_empty() and "trade_date" in sw_df.columns:
            sw_df = sw_df.sort("trade_date")
            if target_date is not None:
                sw_df = sw_df.filter(pl.col("trade_date") <= target_date)

        if sw_df.is_empty():
            raise ValueError(
                f"未在本地 Curated 数据集中找到行业 {industry} ({std_code}) 的行情数据"
            )

        as_of_date_val, tech_snapshot = build_industry_technicals(sw_df, self.config.technicals)

        # 2. 行业估值分位与利差
        val_snapshot = build_industry_valuation(sw_df, self.config.valuation, self.cat_lx)

        # 3. 行业基本面（从行业面板或财报黄金表提取）
        roe_val = None
        rev_yoy = None
        np_yoy = None
        gm_val = None
        veto_flag = False
        veto_reason = ""

        try:
            p_daily_path = (
                self.runtime.data_root / "curated" / "mart" / "industry_panel_daily.parquet"
            )
            if p_daily_path.exists():
                p_df = pl.read_parquet(p_daily_path).filter(pl.col("industry_code") == std_code)
                if not p_df.is_empty():
                    p_df = p_df.sort("as_of_date")
                    if target_date is not None:
                        p_df = p_df.filter(pl.col("as_of_date") <= target_date)
                    if not p_df.is_empty():
                        latest_p = p_df.tail(1).to_dicts()[0]
                        roe_val = latest_p.get("roe_ttm")
                        rev_yoy = latest_p.get("revenue_growth_ttm")
                        np_yoy = latest_p.get("profit_growth_ttm")
                        if np_yoy is not None and rev_yoy is not None:
                            if float(np_yoy) < -30.0 and float(rev_yoy) < -15.0:
                                veto_flag = True
                                veto_reason = (
                                    f"利润大幅下滑({np_yoy:.1f}%)且营收萎缩({rev_yoy:.1f}%)"
                                )
        except Exception as exc:
            logger.warning(f"读取行业面板基本面数据失败: {exc}")

        fin_snapshot = IndustryFinancialsSnapshot(
            report_date=as_of_date_val,
            roe_avg=round(float(roe_val), 2) if roe_val is not None else None,
            revenue_yoy=round(float(rev_yoy), 2) if rev_yoy is not None else None,
            netprofit_yoy=round(float(np_yoy), 2) if np_yoy is not None else None,
            gross_margin=gm_val,
            cycle_stage="存量博弈与结构分化期" if not veto_flag else "下行去库与压力出清期",
            veto_flag=veto_flag,
            veto_reason=veto_reason,
        )

        # 4. 行业成份股龙头梯队与 CR5 集中度
        const_snapshot = load_industry_constituents(self.cat_tu, std_code, target_date=target_date)

        # 5. 产业链上下游图谱
        chain_snapshot = load_value_chain_map(
            std_name, config_path=self.config.value_chain_map_path
        )

        result = IndustryDiagnosticsResult(
            industry_code=std_code,
            industry_name=std_name,
            level=level,
            as_of_date=as_of_date_val,
            technicals=tech_snapshot,
            valuation=val_snapshot,
            financials=fin_snapshot,
            constituents=const_snapshot,
            value_chain=chain_snapshot,
            veto_flag=veto_flag,
        )

        # 6. 标准化产物管理与落盘
        if output_dir:
            parsed_as_of = date.fromisoformat(as_of_date_val[:10])
            paths = ArtifactStore.build_run_paths(
                as_of_date=parsed_as_of,
                artifact_root=output_dir,
                run_class=run_class,
            )
            report_md = render_industry_diagnostics_report(result)

            with ArtifactWriteSession(paths, update_latest=update_latest) as session:
                session.write_json("diagnostics.json", result.to_dict())
                session.write_text("report.md", report_md)

                manifest = build_manifest_base(
                    artifact_type=self.config.artifact_type,
                    schema_version=self.config.schema_version,
                    title=f"{self.config.title}: {std_name} ({std_code})",
                    run_id=paths.run_dir.name,
                    as_of_date=parsed_as_of,
                    artifact_root=output_dir,
                    config_path=self._config_path,
                )
                manifest["industry"] = {
                    "code": std_code,
                    "name": std_name,
                    "level": level,
                }
                session.write_json("manifest.json", manifest)

            logger.info(f"中观产业量化诊断产物已通过 ArtifactStore 落盘: {paths.run_dir}")

        return result


def run_industry_diagnostics(
    industry: str,
    target_date: date | None = None,
    storage_dir: Path | str | None = None,
    config: IndustryDiagnosticsConfig | Path | str | None = None,
    output_dir: Path | str | None = None,
    update_latest: bool = True,
    run_class: RunClass = "official",
) -> IndustryDiagnosticsResult:
    """执行申万中观产业全景量化诊断便捷函数。"""
    runtime = (
        DataRuntimeContext.from_root(storage_dir)
        if storage_dir
        else DataRuntimeContext.from_root("data")
    )
    pipeline = IndustryDiagnosticsPipeline(runtime=runtime, config=config)
    return pipeline.run(
        industry=industry,
        target_date=target_date,
        output_dir=output_dir,
        update_latest=update_latest,
        run_class=run_class,
    )
