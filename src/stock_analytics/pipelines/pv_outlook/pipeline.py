"""光伏景气前瞻仪表盘管线 (pv_outlook)。

不等财报（滞后确认），用产业数据前瞻景气方向：周度价格链价差（毛利空间）+ 月度
装机/库存/供需水位 + 数据缺口矩阵（明示可补充）+ 外部核验事实（强制携带信源日期）。

产物落盘于 ``data/analytics/pv_outlook/``（ArtifactStore run 目录 + latest），并写 manifest：
- pv_outlook_snapshot.parquet : 前瞻读数面板（价格/库存/需求/综合状态）
- gap_matrix.parquet         : 数据缺口矩阵（数据集 x 最新水位 x 状态）
- pv_outlook_report.md       : 人类可读 Markdown 报告
"""

from __future__ import annotations

import logging
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
from stock_analytics.pipelines.pv_outlook.config import (
    DEFAULT_CONFIG_PATH,
    PvOutlookConfig,
    load_pv_outlook_config,
)
from stock_analytics.pipelines.pv_outlook.facts import (
    build_gap_matrix,
    load_price_chain,
)
from stock_analytics.pipelines.pv_outlook.report import render_pv_outlook_markdown
from stock_analytics.pipelines.pv_outlook.scoring import build_outlook_snapshot
from stock_data.catalog import DataCatalog
from stock_data.core.runtime import DataRuntimeContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PvOutlookRunResult:
    """光伏景气前瞻仪表盘一次运行结果。"""

    as_of_date: date
    paths: ArtifactRunPaths
    manifest: dict[str, Any]
    snapshot: pl.DataFrame
    gap_matrix: pl.DataFrame
    report_markdown: str


class PvOutlookPipeline:
    """光伏景气前瞻仪表盘管线。"""

    def __init__(
        self,
        runtime: DataRuntimeContext | None = None,
        config: PvOutlookConfig | Path | str = DEFAULT_CONFIG_PATH,
    ) -> None:
        self.runtime = runtime or DataRuntimeContext.from_root("data")
        if isinstance(config, PvOutlookConfig):
            self.config = config
            self._config_path: Path | str | None = None
        else:
            self._config_path = config
            self.config = load_pv_outlook_config(config)

    def run(
        self,
        as_of: date | None = None,
        output_dir: Path | str | None = None,
        run_class: RunClass = "official",
        update_latest: bool = True,
    ) -> PvOutlookRunResult:
        """构建前瞻面板与缺口矩阵并落盘（ArtifactStore + manifest）。"""
        config = self.config
        artifact_root = Path(output_dir) if output_dir is not None else Path(config.artifact_root)

        if as_of is None:
            catalog = DataCatalog(data_source="tushare", runtime=self.runtime)
            resolved = catalog.get_latest_trade_date("daily_basic")
            if resolved is None:
                raise ValueError("无法确定基准日 as_of（daily_basic 无数据）")
            as_of = resolved

        price_chain = load_price_chain(self.runtime, config)
        gap_matrix = build_gap_matrix(self.runtime, config, as_of, price_chain=price_chain)
        snapshot = build_outlook_snapshot(self.runtime, config, price_chain, as_of)
        report_md = render_pv_outlook_markdown(config, as_of, snapshot, price_chain, gap_matrix)

        paths = ArtifactStore.build_run_paths(
            as_of_date=as_of, artifact_root=artifact_root, run_class=run_class
        )
        manifest = _build_manifest(
            config, as_of, paths, snapshot, gap_matrix, price_chain, self._config_path
        )

        with ArtifactWriteSession(paths, update_latest=update_latest) as session:
            session.write_parquet("pv_outlook_snapshot.parquet", snapshot)
            session.write_parquet("gap_matrix.parquet", gap_matrix)
            session.write_text("pv_outlook_report.md", report_md)
            session.write_json("manifest.json", manifest)

        logger.info("光伏前瞻仪表盘已落盘: %s (as_of=%s)", paths.run_dir, as_of)
        return PvOutlookRunResult(
            as_of_date=as_of,
            paths=paths,
            manifest=manifest,
            snapshot=snapshot,
            gap_matrix=gap_matrix,
            report_markdown=report_md,
        )


def _watermarks_section(price_chain: pl.DataFrame) -> dict[str, Any]:
    """Manifest 水位：价格链最新周与行数。"""
    if price_chain.is_empty():
        return {"latest_week": None, "rows": 0}
    return {"latest_week": str(price_chain["report_date"].max()), "rows": len(price_chain)}


def _gap_summary(gap_matrix: pl.DataFrame) -> dict[str, Any]:
    if gap_matrix.is_empty():
        return {"ok": 0, "lagging": 0, "missing": 0}
    summary: dict[str, Any] = {"ok": 0, "lagging": 0, "missing": 0}
    for row in gap_matrix.group_by("status").len().to_dicts():
        status = row["status"]
        if isinstance(status, str) and status in summary:
            summary[status] = int(row["len"])
    return summary


def _build_manifest(
    config: PvOutlookConfig,
    as_of_date: date,
    paths: ArtifactRunPaths,
    snapshot: pl.DataFrame,
    gap_matrix: pl.DataFrame,
    price_chain: pl.DataFrame,
    config_path: Path | str | None,
) -> dict[str, Any]:
    """构建管线 manifest（含口径 + 水位 + 缺口摘要）。"""
    manifest = build_manifest_base(
        artifact_type="pv_outlook",
        schema_version=config.schema_version,
        title=config.title,
        run_id=paths.run_dir.name,
        as_of_date=as_of_date,
        artifact_root=str(paths.root),
        config_path=config_path or DEFAULT_CONFIG_PATH,
    )
    manifest["methodology"] = {
        "price_spread": "组件毛利空间=组件价-电池价；电池=电池价-硅片价/6.6W；硅片=硅片价/6.6W-硅料价×2.1g/W（简化口径）",
        "scoring": "价格分(周度)权重最高 + 库存分(月度) + 需求分(装机/剪刀差)；综合状态为机制化摘要",
        "gap_matrix": "按各数据集发布节奏(release_lag_days)判定 ok/lagging/missing，缺口如实明示",
        "external_facts": "自动管线不联网；外部事实人工核验后填入配置，强制携带信源与日期",
        "layering": "本面板为前瞻信号摘要（分析产物），财报层为滞后确认，不混入",
    }
    manifest["watermarks"] = {
        "price_chain": _watermarks_section(price_chain),
    }
    manifest["gap_summary"] = _gap_summary(gap_matrix)
    stage_rows = snapshot.filter(pl.col("维度") == "前瞻状态")
    manifest["outlook_stage"] = stage_rows["状态"].to_list()[-1] if stage_rows.height else "NA"
    return manifest


def run_pv_outlook(
    as_of: date | None = None,
    output_dir: Path | str | None = None,
    run_class: RunClass = "official",
    update_latest: bool = True,
    config: PvOutlookConfig | Path | str = DEFAULT_CONFIG_PATH,
    runtime: DataRuntimeContext | None = None,
) -> PvOutlookRunResult:
    """运行光伏景气前瞻仪表盘管线便捷函数。"""
    return PvOutlookPipeline(runtime=runtime, config=config).run(
        as_of=as_of, output_dir=output_dir, run_class=run_class, update_latest=update_latest
    )
