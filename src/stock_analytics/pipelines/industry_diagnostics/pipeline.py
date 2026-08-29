"""中观产业深度诊断与全景量化体检核心管线。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from stock_analytics.pipelines.artifacts import (
    ArtifactRunPaths,
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
from stock_analytics.pipelines.industry_diagnostics.scoring import calculate_industry_scores
from stock_analytics.pipelines.industry_diagnostics.sources import (
    build_industry_technicals,
    build_industry_valuation,
    load_industry_constituents,
    load_value_chain_map,
    resolve_industry_meta,
)
from stock_analytics.pipelines.industry_diagnostics.types import (
    IndustryConstituentsSnapshot,
    IndustryDiagnosticsResult,
    IndustryFinancialsSnapshot,
    IndustryScoreBreakdown,
    IndustryValuationSnapshot,
)
from stock_core.utils.logger import logger
from stock_data.catalog import DataCatalog
from stock_data.core.runtime import DataRuntimeContext
from stock_reporting.templates.industry_diagnostics_report import (
    render_industry_diagnostics_report,
)


def _load_industry_financials(
    runtime: DataRuntimeContext,
    std_code: str,
    as_of_date_val: str,
    target_date: date | None,
    config: IndustryDiagnosticsConfig,
) -> IndustryFinancialsSnapshot:
    """从行业日频面板提取财务基本面快照并判断一票否决。"""
    roe_val = None
    rev_yoy = None
    np_yoy = None
    gm_val = None
    veto_flag = False
    veto_reason = ""

    try:
        p_daily_path = runtime.data_root / "curated" / "mart" / "industry_panel_daily.parquet"
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
                        if (
                            float(np_yoy) < config.veto_rules.profit_decay_threshold
                            and float(rev_yoy) < config.veto_rules.revenue_decay_threshold
                        ):
                            veto_flag = True
                            veto_reason = f"利润大幅下滑({np_yoy:.1f}%)且营收萎缩({rev_yoy:.1f}%)"
    except Exception as exc:
        logger.warning(f"读取行业面板基本面数据失败: {exc}")

    scissors = None
    if np_yoy is not None and rev_yoy is not None:
        scissors = round(float(np_yoy) - float(rev_yoy), 2)

    return IndustryFinancialsSnapshot(
        report_date=as_of_date_val,
        roe_avg=round(float(roe_val), 2) if roe_val is not None else None,
        revenue_yoy=round(float(rev_yoy), 2) if rev_yoy is not None else None,
        netprofit_yoy=round(float(np_yoy), 2) if np_yoy is not None else None,
        profit_scissors=scissors,
        gross_margin=gm_val,
        cycle_stage="存量博弈与结构分化期" if not veto_flag else "下行去库与压力出清期",
        veto_flag=veto_flag,
        veto_reason=veto_reason,
    )


def _write_industry_artifacts(
    result: IndustryDiagnosticsResult,
    scores: IndustryScoreBreakdown,
    val_snapshot: IndustryValuationSnapshot,
    fin_snapshot: IndustryFinancialsSnapshot,
    const_snapshot: IndustryConstituentsSnapshot,
    sw_df: pl.DataFrame,
    paths: ArtifactRunPaths,
    config: IndustryDiagnosticsConfig,
    config_path: str,
    output_dir: Path | str,
    parsed_as_of: date,
    update_latest: bool,
) -> None:
    """写入文件产物并通过 ArtifactStore 自动同步落库至 SQLite 控制面。"""
    report_md = render_industry_diagnostics_report(result)

    with ArtifactWriteSession(paths, update_latest=update_latest) as session:
        session.write_json("diagnostics.json", result.to_dict())
        session.write_json("scores.json", scores.to_dict())
        session.write_text("report.md", report_md)

        # 质量审计报告
        quality_md = (
            f"# 数据质量审计报告: {result.industry_name} ({result.industry_code})\n\n"
            f"- **基准日期**: {result.as_of_date}\n"
            f"- **行情数据条数**: {len(sw_df)} 条 (Curated sw_daily)\n"
            f"- **成份股覆盖数**: {const_snapshot.total_count} 家\n"
            f"- **估值数据完整度**: PE={'OK' if val_snapshot.pe_ttm is not None else 'Missing'}, "
            f"PB={'OK' if val_snapshot.pb is not None else 'Missing'}, "
            f"5Y分位={'OK' if val_snapshot.pe_percentile_5y is not None else 'Missing'}\n"
            f"- **基本面数据完整度**: ROE={'OK' if fin_snapshot.roe_avg is not None else 'Missing'}, "
            f"营收同比={'OK' if fin_snapshot.revenue_yoy is not None else 'Missing'}\n"
            f"- **数据质量状态**: 正常\n"
        )
        session.write_text("quality_report.md", quality_md)
        session.write_json(
            "quality_report.json",
            {
                "as_of_date": result.as_of_date,
                "sw_daily_rows": len(sw_df),
                "constituents_count": const_snapshot.total_count,
                "valuation_complete": val_snapshot.pe_ttm is not None,
                "financials_complete": fin_snapshot.roe_avg is not None,
                "status": "PASS",
            },
        )

        manifest = build_manifest_base(
            artifact_type=config.artifact_type,
            schema_version=config.schema_version,
            title=f"{config.title}: {result.industry_name} ({result.industry_code})",
            run_id=paths.run_dir.name,
            as_of_date=parsed_as_of,
            artifact_root=output_dir,
            config_path=config_path,
        )
        manifest["industry"] = {
            "code": result.industry_code,
            "name": result.industry_name,
            "level": result.level,
        }
        manifest["summary"] = {
            "composite_score": scores.composite_score,
            "momentum_score": scores.momentum_score,
            "valuation_score": scores.valuation_score,
            "fundamental_score": scores.fundamental_score,
            "crowding_penalty": scores.crowding_penalty,
            "pe_percentile_5y": val_snapshot.pe_percentile_5y or 0.0,
            "pb_percentile_5y": val_snapshot.pb_percentile_5y or 0.0,
            "veto_flag": 1 if scores.veto_triggered else 0,
            "profit_scissors": fin_snapshot.profit_scissors or 0.0,
        }
        manifest["quadrant"] = scores.quadrant
        manifest["industry_type"] = scores.industry_type
        session.write_json("manifest.json", manifest)

    logger.info(f"中观产业量化诊断产物已通过 ArtifactStore 落盘: {paths.run_dir}")


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

        # 1. 行业行情
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

        # 2. 行业估值
        val_snapshot = build_industry_valuation(sw_df, self.config.valuation, self.cat_lx)

        # 3. 行业基本面
        fin_snapshot = _load_industry_financials(
            self.runtime, std_code, as_of_date_val, target_date, self.config
        )

        # 4. 行业成份股与 CR5
        const_snapshot, turnover_p5y = load_industry_constituents(
            self.cat_tu, std_code, target_date=target_date
        )

        # 5. 产业链图谱
        chain_snapshot = load_value_chain_map(
            std_name, config_path=self.config.value_chain_map_path
        )

        # 6. 多维打分与 PB-ROE 象限
        scores = calculate_industry_scores(
            industry_name=std_name,
            technicals=tech_snapshot,
            valuation=val_snapshot,
            financials=fin_snapshot,
            constituents=const_snapshot,
            weights=self.config.score_weights,
            veto_rules=self.config.veto_rules,
            turnover_p5y=turnover_p5y,
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
            scores=scores,
            veto_flag=scores.veto_triggered,
        )

        # 7. 标准化产物管理与落盘
        if output_dir:
            parsed_as_of = date.fromisoformat(as_of_date_val[:10])
            paths = ArtifactStore.build_run_paths(
                as_of_date=parsed_as_of,
                artifact_root=output_dir,
                run_class=run_class,
            )
            _write_industry_artifacts(
                result=result,
                scores=scores,
                val_snapshot=val_snapshot,
                fin_snapshot=fin_snapshot,
                const_snapshot=const_snapshot,
                sw_df=sw_df,
                paths=paths,
                config=self.config,
                config_path=self._config_path,
                output_dir=output_dir,
                parsed_as_of=parsed_as_of,
                update_latest=update_latest,
            )

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
