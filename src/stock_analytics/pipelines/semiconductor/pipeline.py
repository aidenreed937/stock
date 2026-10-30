"""半导体深研线：供需剪刀差与结构性确认腿的管线编排。

把散落 ``scripts/*.py`` 的半导体实物流量腿，工程化为配置驱动、ArtifactStore
落盘 + manifest 的标准管线：

- 剪刀差 = demand(T read + SIA sales 均值合成) - supply(SEAJ 设备出货)；
- 结构性腿 = ai_capex(云 CapEx 季度)，独立分组不入剪刀差。

产物落盘于 ``data/analytics/semiconductor/``（ArtifactStore run 目录 + latest），
并写 manifest（完整性 + watermark）。

术语约定：本层产出的腿部均为**特征（feature / 候选因子）**，是回测的输入；
**不是已验证的有效因子**——因子有效性（IC/回测/敏感性）由
``stock_strategy.industry.semiconductor`` 验证层确认。
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
from stock_analytics.pipelines.semiconductor.config import (
    DEFAULT_CONFIG_PATH,
    SemiconductorLegsConfig,
    load_semiconductor_legs_config,
)
from stock_analytics.pipelines.semiconductor.legs import (
    build_semiconductor_legs_panel,
    load_calendar,
)
from stock_data.catalog import DataCatalog
from stock_data.core.runtime import DataRuntimeContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SemiconductorLegsRunResult:
    """半导体建腿一次运行结果。"""

    as_of_date: date
    paths: ArtifactRunPaths
    manifest: dict[str, Any]
    panel: pl.DataFrame


class SemiconductorLegsPipeline:
    """半导体供需剪刀差 + 结构性确认腿 管线。"""

    def __init__(
        self,
        runtime: DataRuntimeContext | None = None,
        config: SemiconductorLegsConfig | Path | str = DEFAULT_CONFIG_PATH,
    ) -> None:
        self.runtime = runtime or DataRuntimeContext.from_root("data")
        if isinstance(config, SemiconductorLegsConfig):
            self.config = config
            self._config_path: Path | str | None = None
        else:
            self._config_path = config
            self.config = load_semiconductor_legs_config(config)

    def run(
        self,
        as_of: date | None = None,
        output_dir: Path | str | None = None,
        run_class: RunClass = "official",
        update_latest: bool = True,
    ) -> SemiconductorLegsRunResult:
        """构建腿部面板并落盘（ArtifactStore + manifest）。

        ``output_dir`` 缺省用配置的 artifact_root。
        """
        config = self.config
        artifact_root = Path(output_dir) if output_dir is not None else Path(config.artifact_root)
        calendar = load_calendar(self.runtime, config.calendar_mart)

        if as_of is None:
            _max_date = calendar["trade_date"].max()
            if not isinstance(_max_date, date):
                raise ValueError("无法确定基准日 as_of")
            as_of = _max_date

        cat = DataCatalog(data_source="industry")
        panel = build_semiconductor_legs_panel(config, calendar, cat)

        paths = ArtifactStore.build_run_paths(
            as_of_date=as_of, artifact_root=artifact_root, run_class=run_class
        )
        manifest = _build_manifest(config, as_of, paths, panel, self._config_path)

        with ArtifactWriteSession(paths, update_latest=update_latest) as session:
            session.write_parquet("semiconductor_legs.parquet", panel)
            session.write_json("manifest.json", manifest)

        logger.info("半导体建腿产物已落盘: %s (as_of=%s)", paths.run_dir, as_of)
        return SemiconductorLegsRunResult(
            as_of_date=as_of, paths=paths, manifest=manifest, panel=panel
        )


def _build_manifest(
    config: SemiconductorLegsConfig,
    as_of_date: date,
    paths: ArtifactRunPaths,
    panel: pl.DataFrame,
    config_path: Path | str | None,
) -> dict[str, Any]:
    """构建建腿管线 manifest（含完整性 + 水位 + 最新截面）。"""
    manifest = build_manifest_base(
        artifact_type="semiconductor_legs",
        schema_version=config.schema_version,
        title=config.title,
        run_id=paths.run_dir.name,
        as_of_date=as_of_date,
        artifact_root=str(paths.root),
        config_path=config_path or DEFAULT_CONFIG_PATH,
    )
    manifest["methodology"] = {
        "demand": "TSMC 台积电月营收(领先) + SIA 全球销售额(同步)，均值合成滚动分位",
        "supply": "SEAJ 日本制设备出货 3MMA 滚动分位（领先 1-2 年产能释放）",
        "scissors": "demand_score - supply_score",
        "structural": "ai_capex(云 CapEx 季度)，leg_type 独立分组不入剪刀差",
        "calendar_effect": "release_date 生效，日频前向填充，无前视",
    }
    _max_leg_date = panel["trade_date"].max()
    manifest["legs"] = {
        "max_trade_date": (_max_leg_date.isoformat() if isinstance(_max_leg_date, date) else None)
    }
    manifest["industries"] = list(config.industry_codes)

    # 数据完整性：结构腿列（demand/supply/scissors）与结构性腿列的空值覆盖
    struct_cols = [c for c in panel.columns if c.endswith("_score")]
    records = panel.select(["industry_code", *struct_cols]).group_by("industry_code").mean()
    datacomplete = {}
    for row in records.to_dicts():
        code = row["industry_code"]
        datacomplete[code] = {col: (row.get(col) is not None) for col in struct_cols}
    manifest["data_completeness"] = datacomplete

    # 最新截面快照（as_of 前后各行业）
    snap = (
        panel.filter(pl.col("trade_date") <= as_of_date)
        .sort("trade_date")
        .group_by("industry_code")
        .last()
        .select(["industry_code", *struct_cols])
    )
    manifest["latest_snapshot"] = snap.to_dicts()
    return manifest


def run_semiconductor_legs(
    *,
    as_of: date | None = None,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    output_dir: Path | str | None = None,
    run_class: RunClass = "official",
    update_latest: bool = True,
    storage_dir: Path | str | None = None,
) -> SemiconductorLegsRunResult:
    """运行半导体建腿管线便捷函数。"""
    runtime = (
        DataRuntimeContext.from_root(storage_dir)
        if storage_dir
        else DataRuntimeContext.from_root("data")
    )
    pipeline = SemiconductorLegsPipeline(runtime=runtime, config=config_path)
    return pipeline.run(
        as_of=as_of,
        output_dir=output_dir,
        run_class=run_class,
        update_latest=update_latest,
    )


def load_latest_semiconductor_legs(
    artifact_root: Path | str | None = None,
) -> pl.DataFrame:
    """读取半导体建腿管线 latest 产物面板。

    供策略/研究层消费（经包级门面），返回腿部面板（剪刀差 + 结构性腿，仅 270100）。
    产物缺失时抛出 FileNotFoundError。
    """
    from stock_analytics.pipelines.artifacts.reader import resolve_artifact_run

    root = Path(artifact_root) if artifact_root else Path("data/analytics/semiconductor")
    try:
        run_dir = resolve_artifact_run(
            root, as_of_date="latest", expected_artifact_type="semiconductor_legs"
        ).run_dir
    except Exception as exc:  # noqa: BLE001
        raise FileNotFoundError(
            f"未找到半导体建腿产物 {root}（先运行 run_semiconductor_legs）"
        ) from exc
    path = run_dir / "semiconductor_legs.parquet"
    if not path.exists():
        raise FileNotFoundError(f"半导体建腿产物缺面板: {path}")
    return pl.read_parquet(path)


__all__ = [
    "SemiconductorLegsPipeline",
    "SemiconductorLegsRunResult",
    "load_latest_semiconductor_legs",
    "run_semiconductor_legs",
]
