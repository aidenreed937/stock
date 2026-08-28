"""系统性风险管线编排。"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Literal

import polars as pl

from stock_analytics.features import FeatureStore
from stock_analytics.pipelines.macro_risk.config import load_macro_risk_config
from stock_analytics.pipelines.macro_risk.data_fetchers import (
    FETCHER_REGISTRY,
    FetchContext,
)
from stock_analytics.primitives.rules import rolling_percentile
from stock_data.catalog import DataCatalog
from stock_data.core.runtime import DataRuntimeContext
from stock_reporting.templates.macro_risk_report import render_macro_risk_report

logger = logging.getLogger(__name__)


class MacroRiskPipeline:
    def __init__(
        self,
        runtime: DataRuntimeContext | None = None,
        config_path: Path | str = "config/analytics/macro_risk.yaml",
    ):
        self.runtime = runtime or DataRuntimeContext.from_root("data")
        self.cat = DataCatalog(runtime=self.runtime, data_source="lixinger")
        self.cat_yf = DataCatalog(runtime=self.runtime, data_source="yfinance")
        self.fs = FeatureStore()

        # 真正实现配置驱动
        self.config = load_macro_risk_config(config_path)

        self._md_cache: pl.DataFrame | None = None

    def _market_daily(self) -> pl.DataFrame:
        if self._md_cache is None:
            self._md_cache = self.fs.get_domain_mart("market_daily").sort("trade_date")
        return self._md_cache

    def _get_raw_series(self, name: str) -> pl.DataFrame:
        ctx = FetchContext(
            cat=self.cat,
            cat_yf=self.cat_yf,
            fs=self.fs,
            md=self._market_daily(),
        )
        fetcher = FETCHER_REGISTRY.get(name)
        if not fetcher:
            raise ValueError(f"未注册的因子数据源: {name}")
        return fetcher(ctx)

    def run(
        self,
        output_dir: Path | str | None = "data/analytics/macro_risk",
        update_latest: bool = True,
        run_class: Literal["official", "backfill", "experiment"] = "official",
    ) -> pl.DataFrame:
        axis = (
            self._market_daily()
            .filter(pl.col("trade_date") >= date(2015, 1, 1))
            .select("trade_date")
            .sort("trade_date")
        )
        as_of_val = axis["trade_date"].max()
        if as_of_val is None or not isinstance(as_of_val, date):
            raise ValueError("无法获取有效的基准日期")
        as_of: date = as_of_val
        score_frame = axis.select("trade_date")
        raw_cache: dict[str, pl.DataFrame] = {}

        logger.info(f"开始生成系统性风险指数 (基准日: {as_of!s})")

        # 遍历配置表中的因子
        for factor_name, f_cfg in self.config.factors.items():
            if f_cfg.series not in raw_cache:
                raw_cache[f_cfg.series] = self._get_raw_series(f_cfg.series)

            s = (
                raw_cache[f_cfg.series]
                .filter(pl.col("trade_date") <= as_of)
                .select(["trade_date", f_cfg.column])
                .drop_nulls(subset=[f_cfg.column])
                .sort("trade_date")
            )

            # 使用系统标准 primitives 算子计算历史分位
            s = s.with_columns(
                rolling_percentile(f_cfg.column, f_cfg.window, min_samples=f_cfg.min_periods).alias(
                    f"{factor_name}_score"
                )
            )

            # 反转逻辑处理
            if f_cfg.direction == "rev":
                s = s.with_columns(
                    (100.0 - pl.col(f"{factor_name}_score")).alias(f"{factor_name}_score")
                )

            scored = s.select(["trade_date", f"{factor_name}_score"])

            # 合并逻辑
            if f_cfg.series == "vix":
                score_frame = score_frame.join_asof(
                    scored.drop_nulls(), on="trade_date", strategy="backward"
                )
            else:
                score_frame = score_frame.join(scored, on="trade_date", how="left")

        score_cols = [f"{n}_score" for n in self.config.factors]
        score_frame = score_frame.with_columns(
            [pl.col(c).fill_nan(None).alias(c) for c in score_cols]
        )

        # 按照配置的维度聚合成多维评分
        for dim, names in self.config.dims.items():
            score_frame = score_frame.with_columns(
                pl.mean_horizontal([pl.col(f"{n}_score").fill_nan(None) for n in names]).alias(
                    f"dim_{dim}"
                )
            )

        # 聚合生成双轨制核心指数 (Overheat & Panic)
        for idx_name, components in self.config.indices.items():
            exprs = []
            for comp in components:
                col_expr = pl.col(f"dim_{comp.dim}")
                if comp.direction == "rev":
                    col_expr = 100.0 - col_expr
                exprs.append(col_expr)

            score_frame = score_frame.with_columns(pl.mean_horizontal(exprs).alias(idx_name))

        if output_dir:
            from stock_analytics.pipelines.artifacts import (
                ArtifactStore,
                ArtifactWriteSession,
                build_manifest_base,
            )

            paths = ArtifactStore.build_run_paths(
                as_of_date=as_of, artifact_root=output_dir, run_class=run_class
            )

            # 渲染研报
            report_md = render_macro_risk_report(score_frame, as_of)

            with ArtifactWriteSession(paths, update_latest=update_latest) as session:
                session.write_parquet("risk_factors.parquet", score_frame)
                session.write_text("report.md", report_md)

                manifest = build_manifest_base(
                    artifact_type="macro_risk",
                    schema_version=1,
                    title="双轨制系统性风险雷达",
                    run_id=paths.run_dir.name,
                    as_of_date=as_of,
                    artifact_root=output_dir,
                    config_path="config/analytics/macro_risk.yaml",
                )
                session.write_json("manifest.json", manifest)

            logger.info(f"双轨制系统性风险指数已通过 ArtifactStore 落盘: {paths.run_dir}")

        return score_frame
