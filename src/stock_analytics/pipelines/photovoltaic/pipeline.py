"""光伏设备（630500）周期状态与防守信号特征面板管线。

把散落 ``scripts/industry_solar_*.py`` 的光伏已验证形态（产能周期状态 + 财报 TTM 防守门 +
价格回撤补丁），工程化为配置驱动、ArtifactStore 落盘 + manifest 的标准管线：

- cycle_state ：产能周期四态（上行/过剩/下行/底部右侧），产业层唯一季度前瞻危险源；
- fin_defense ：成分股聚合净利 TTM <0（恶化认定，滞后防守腿）；
- price_dd    ：组件周价 52 周高点回撤 %（「确认恶化后」尾部防守补丁，非前瞻）。

产物落盘于 ``data/analytics/photovoltaic/``（ArtifactStore run 目录 + latest），并写 manifest。
注意：这不是半导体式供需剪刀差管线——光伏供需腿已证伪，本管线生产化的是验证通过的
**周期状态 + 防守信号**，不重复生产化失效的剪刀差腿。

术语约定：本层产出的是**特征（feature / 状态）**，是回测/决策的输入；有效性由
``stock_strategy`` 验证层确认。
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
from stock_analytics.pipelines.photovoltaic.config import (
    DEFAULT_CONFIG_PATH,
    PhotovoltaicLegsConfig,
    load_photovoltaic_legs_config,
)
from stock_analytics.pipelines.photovoltaic.legs import (
    build_photovoltaic_legs_panel,
    load_calendar,
)
from stock_data.core.runtime import DataRuntimeContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PhotovoltaicLegsRunResult:
    """光伏建腿/状态面板一次运行结果。"""

    as_of_date: date
    paths: ArtifactRunPaths
    manifest: dict[str, Any]
    panel: pl.DataFrame


class PhotovoltaicLegsPipeline:
    """光伏 630500 周期状态 + 防守信号特征面板管线。"""

    def __init__(
        self,
        runtime: DataRuntimeContext | None = None,
        config: PhotovoltaicLegsConfig | Path | str = DEFAULT_CONFIG_PATH,
    ) -> None:
        self.runtime = runtime or DataRuntimeContext.from_root("data")
        if isinstance(config, PhotovoltaicLegsConfig):
            self.config = config
            self._config_path: Path | str | None = None
        else:
            self._config_path = config
            self.config = load_photovoltaic_legs_config(config)

    def run(
        self,
        as_of: date | None = None,
        output_dir: Path | str | None = None,
        run_class: RunClass = "official",
        update_latest: bool = True,
    ) -> PhotovoltaicLegsRunResult:
        """构建特征面板并落盘（ArtifactStore + manifest）。

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

        panel = build_photovoltaic_legs_panel(config, calendar, self.runtime)

        paths = ArtifactStore.build_run_paths(
            as_of_date=as_of, artifact_root=artifact_root, run_class=run_class
        )
        manifest = _build_manifest(config, as_of, paths, panel, self._config_path)

        with ArtifactWriteSession(paths, update_latest=update_latest) as session:
            session.write_parquet("photovoltaic_legs.parquet", panel)
            session.write_json("manifest.json", manifest)

        logger.info("光伏特征面板已落盘: %s (as_of=%s)", paths.run_dir, as_of)
        return PhotovoltaicLegsRunResult(
            as_of_date=as_of, paths=paths, manifest=manifest, panel=panel
        )


def _bool_share(series: pl.Series) -> float:
    """布尔/整数列 True 占比（0-1）。空面板返回 0.0。"""
    n = series.len()
    if n == 0:
        return 0.0
    return float(series.sum()) / float(n)


def _alerts_summary(panel: pl.DataFrame) -> dict[str, Any]:
    """防守信号触发占比摘要（%）＋样本天数。"""
    n = max(panel.height, 1)
    return {
        "al_cycle_pct": _bool_share(panel["al_cycle"].cast(pl.Int32)) * 100.0,
        "al_fin_pct": _bool_share(panel["al_fin"].cast(pl.Int32)) * 100.0,
        "al_price_pct": _bool_share(panel["al_price"].cast(pl.Int32)) * 100.0,
        "defense_reduced_pct": _bool_share((panel["defense_w"] < 1.0).cast(pl.Int32)) * 100.0,
        "defense_empty_pct": _bool_share((panel["defense_w"] == 0.0).cast(pl.Int32)) * 100.0,
        "n_days": n,
    }


def _build_manifest(
    config: PhotovoltaicLegsConfig,
    as_of_date: date,
    paths: ArtifactRunPaths,
    panel: pl.DataFrame,
    config_path: Path | str | None,
) -> dict[str, Any]:
    """构建管线 manifest（含完整性 + 水位 + 最新截面）。"""
    manifest = build_manifest_base(
        artifact_type="photovoltaic_legs",
        schema_version=config.schema_version,
        title=config.title,
        run_id=paths.run_dir.name,
        as_of_date=as_of_date,
        artifact_root=str(paths.root),
        config_path=config_path or DEFAULT_CONFIG_PATH,
    )
    manifest["methodology"] = {
        "cycle_state": "产能周期四态(上行/过剩/下行/底部右侧)：扩产潮 cap_yoy>=30% 及其 24 月余波是核心开关",
        "fin_defense": "成分股聚合净利 TTM 同比<0 判定恶化（滞后防守腿）",
        "price_dd": "组件周价 52 周高点回撤 %（『确认恶化后』尾部防守补丁，非前瞻）",
        "defense_w": "cycle∈{过剩,下行} 或 fin<0 → reduced(0.25)；price_dd<=-20% → empty(0.0)",
        "lifecycle_w": "上行 1.0 / 过剩 0.0 / 下行 0.8 / 底部右侧 试探 0.5",
        "calendar_effect": "release_date/披露日生效，日频前向填充，T+1 由权重层 shift(1)",
    }
    _max = panel["trade_date"].max()
    manifest["states"] = {
        "max_trade_date": (_max.isoformat() if isinstance(_max, date) else None),
        "latest_state": panel.sort("trade_date")
        .tail(1)
        .select(["trade_date", "state"])
        .to_dicts()[0],
    }
    manifest["industries"] = list(config.industry_codes)

    # 各状态天数分布 + 防守权重触发占比
    state_dist = (
        panel.group_by("state").agg(pl.len().alias("days")).sort("days", descending=True).to_dicts()
    )
    manifest["state_distribution"] = state_dist
    manifest["alerts"] = _alerts_summary(panel)

    # 最新截面快照
    snap = (
        panel.sort("trade_date")
        .tail(1)
        .select(
            [
                "trade_date",
                "close",
                "state",
                "price_dd",
                "lifecycle_w",
                "al_cycle",
                "al_fin",
                "al_price",
                "defense_w",
            ]
        )
        .to_dicts()
    )
    manifest["latest_snapshot"] = snap
    return manifest


def run_photovoltaic_legs(
    *,
    as_of: date | None = None,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    output_dir: Path | str | None = None,
    run_class: RunClass = "official",
    update_latest: bool = True,
    storage_dir: Path | str | None = None,
) -> PhotovoltaicLegsRunResult:
    """运行光伏建腿/状态面板管线便捷函数。"""
    runtime = (
        DataRuntimeContext.from_root(storage_dir)
        if storage_dir
        else DataRuntimeContext.from_root("data")
    )
    pipeline = PhotovoltaicLegsPipeline(runtime=runtime, config=config_path)
    return pipeline.run(
        as_of=as_of,
        output_dir=output_dir,
        run_class=run_class,
        update_latest=update_latest,
    )


def load_latest_photovoltaic_legs(
    artifact_root: Path | str | None = None,
) -> pl.DataFrame:
    """读取光伏特征面板管线 latest 产物面板。

    供策略/研究层消费，返回周期状态 + 防守信号特征面板。产物缺失时抛 FileNotFoundError。
    """
    from stock_analytics.pipelines.artifacts.reader import resolve_artifact_run

    root = Path(artifact_root) if artifact_root else Path("data/analytics/photovoltaic")
    try:
        run_dir = resolve_artifact_run(
            root, as_of_date="latest", expected_artifact_type="photovoltaic_legs"
        ).run_dir
    except Exception as exc:  # noqa: BLE001
        raise FileNotFoundError(
            f"未找到光伏特征面板产物 {root}（先运行 run_photovoltaic_legs）"
        ) from exc
    path = run_dir / "photovoltaic_legs.parquet"
    if not path.exists():
        raise FileNotFoundError(f"光伏特征面板产物缺面板: {path}")
    return pl.read_parquet(path)


__all__ = [
    "PhotovoltaicLegsPipeline",
    "PhotovoltaicLegsRunResult",
    "load_latest_photovoltaic_legs",
    "run_photovoltaic_legs",
]
