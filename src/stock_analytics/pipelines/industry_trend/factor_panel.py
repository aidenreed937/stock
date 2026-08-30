"""申万行业产业趋势跟踪因子面板生成器。

与「行业轮动 5 大因子」不同，本面板面向**周期尺度（季度/半年）全球产业趋势的确认与跟踪**，
而非 A 股内部截面博弈。核心骨架（与 docs/plan/industry_rotation_upgrade_plan.md §2 对齐）：

    composite = 全球方向(方向层) × 量价齐升(供需层) × 毛利率扩张(议价权层)
                + 现实景气(业绩预告/快报)
                − 拥挤度(防守)

默认权重精确对齐已验证 milestone：现实景气 2/3 + 拥挤度防守 1/3，样本外 Sharpe ≈ 0.39；
三层框架因子（direction/supply_demand/bargaining）默认权重 0，待全球共振数据补齐后激活。

输入：``industry_panel_daily.parquet``（49 字段 Mart，含 forecast/express/revenue/profit/tcr）。
方向层输入：``global_resonance_map.parquet``（数据缺口，未来接入；缺失时中性 50）。
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any, Literal

import polars as pl

from stock_analytics.pipelines.artifacts import (
    ArtifactRunPaths,
    ArtifactStore,
    ArtifactWriteSession,
    build_manifest_base,
)
from stock_analytics.pipelines.industry_trend.config import (
    DEFAULT_CONFIG_PATH,
    load_industry_trend_config,
)
from stock_core.exceptions import DataValidationError
from stock_data.core.runtime import DataRuntimeContext

logger = logging.getLogger(__name__)

_DEFAULT_START_DATE = date(2015, 1, 1)

_GLOBAL_RESONANCE_MART = "global_resonance_map"

# 面板输出 schema（按此顺序落盘）
_PANEL_COLUMNS = [
    "trade_date",
    "industry_code",
    "industry_name",
    "direction_score",
    "supply_demand_score",
    "bargaining_score",
    "prosperity_score",
    "crowding_score",
    "composite_trend_score",
    "trend_momentum",
]


def _cs_percentile(col: str) -> pl.Expr:
    """横截面百分位: (rank - 1) / (count - 1) * 100，空值取中性 50。"""
    return (
        (
            (pl.col(col).rank(method="average").over("trade_date") - 1.0)
            / (pl.col(col).count().over("trade_date") - 1.0)
            * 100.0
        )
        .fill_nan(50.0)
        .fill_null(50.0)
    )


def load_global_resonance_scores(runtime: DataRuntimeContext) -> pl.DataFrame | None:
    """加载全球共振方向层得分（数据缺口，未来接入）。

    期望输入 ``data/curated/mart/global_resonance_map.parquet``，列：
    ``trade_date`` / ``industry_code`` / ``direction_score``（0-100，全球资本开支方向分）。
    文件缺失或列不满足时返回 None，方向层退化为中性分。
    """
    path = runtime.data_root / "curated" / "mart" / f"{_GLOBAL_RESONANCE_MART}.parquet"
    if not path.exists():
        return None
    try:
        frame = pl.read_parquet(path)
    except Exception as exc:
        logger.warning(f"全球共振映射表读取失败，方向层退化为中性: {exc}")
        return None
    required = {"trade_date", "industry_code", "direction_score"}
    if not required.issubset(frame.columns):
        logger.warning(f"全球共振映射表缺少列 {sorted(required - set(frame.columns))}，退化为中性")
        return None
    return frame.select(["trade_date", "industry_code", "direction_score"])


def build_industry_trend_panel(
    *,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    runtime: DataRuntimeContext | None = None,
    start_date: date = _DEFAULT_START_DATE,
    as_of: date | None = None,
) -> pl.DataFrame:
    """构建全历史申万 31 行业产业趋势跟踪因子面板。"""
    config = load_industry_trend_config(config_path)
    rt = runtime or DataRuntimeContext.from_root("data")
    mart_path = rt.data_root / "curated" / "mart" / "industry_panel_daily.parquet"
    if not mart_path.exists():
        raise DataValidationError(f"缺少行业基本面面板: {mart_path}")

    df = pl.read_parquet(mart_path).rename({"as_of_date": "trade_date"})
    df = df.filter(pl.col("trade_date") >= start_date)
    if as_of is not None:
        df = df.filter(pl.col("trade_date") <= as_of)
    df = df.sort(["trade_date", "industry_code"])

    # 0. 中间列：营收/净利增速（空值视为 0）、量价齐升门、毛利率扩张代理
    rev = pl.col("revenue_growth_ttm").fill_null(0.0)
    prof = pl.col("profit_growth_ttm").fill_null(0.0)
    base = df.with_columns(
        [
            rev.alias("_rev"),
            prof.alias("_prof"),
            (rev + prof).alias("_rev_plus_prof"),
            (prof - rev).alias("_margin_expand"),
            ((rev > 0.0) & (prof > 0.0)).alias("_quality"),
        ]
    )

    # 1. 现实景气（业绩预告向好占比 + 快报利润增速中位数），样本外走强的主驱动
    fc = _cs_percentile("forecast_positive_share")
    ex = _cs_percentile("express_profit_growth_median")

    # 2. 供需层：量价齐升（营收 + 净利双正）才是真需求驱动
    supply_demand = (
        pl.when(pl.col("_quality"))
        .then(_cs_percentile("_rev_plus_prof"))
        .when(pl.col("_prof") > 0.0)  # 供给收缩（营收负、净利正）：假繁荣，惩罚
        .then(pl.lit(config.supply_contract_penalty))
        .otherwise(pl.lit(config.double_negative_penalty))  # 双负
    )

    # 3. 议价权层：量价齐升门内的毛利率扩张（净利增速 > 营收增速）
    bargaining = (
        pl.when(pl.col("_quality"))
        .then(_cs_percentile("_margin_expand"))
        .otherwise(pl.lit(config.bargaining_neutral))
    )

    computed = base.with_columns(
        [
            fc.alias("_fc"),
            ex.alias("_ex"),
            supply_demand.clip(0.0, 100.0).alias("supply_demand_score"),
            bargaining.clip(0.0, 100.0).alias("bargaining_score"),
            pl.col("tcr_percentile")
            .fill_null(_cs_percentile("amount_yi"))
            .clip(0.0, 100.0)
            .alias("crowding_score"),
        ]
    )

    # 4. 方向层：全球共振（数据缺口 → 中性）
    resonance = load_global_resonance_scores(rt)
    if resonance is not None:
        computed = computed.join(resonance, on=["trade_date", "industry_code"], how="left")
        computed = computed.with_columns(
            pl.col("direction_score").fill_null(config.direction_neutral).alias("direction_score")
        )
    else:
        computed = computed.with_columns(pl.lit(config.direction_neutral).alias("direction_score"))

    # 5. 合成复合趋势得分（权重归一化，crowding 为减分项）
    result = computed.with_columns(
        ((pl.col("_fc") + pl.col("_ex")) / 2.0).alias("prosperity_score"),
    )
    result = result.with_columns(
        _composite_expr(config.weights, config.weight_sum).alias("composite_trend_score"),
    )

    # 6. 环比趋势确认：复合得分相对上一季度的变化（趋势跟踪而非追高）
    result = result.sort(["industry_code", "trade_date"]).with_columns(
        (
            pl.col("composite_trend_score")
            - pl.col("composite_trend_score").shift(config.trend_lookback).over("industry_code")
        ).alias("trend_momentum")
    )

    return result.select(_PANEL_COLUMNS).sort(["trade_date", "industry_code"])


def _composite_expr(weights: dict[str, float], total: float) -> pl.Expr:
    """三层共振 + 现实景气 − 拥挤度的加权合成表达式。"""
    if total <= 0:
        return pl.lit(50.0)
    return (
        weights["direction"] * pl.col("direction_score")
        + weights["supply_demand"] * pl.col("supply_demand_score")
        + weights["bargaining"] * pl.col("bargaining_score")
        + weights["prosperity"] * pl.col("prosperity_score")
        + weights["crowding"] * (100.0 - pl.col("crowding_score"))
    ) / total


def save_industry_trend_panel(
    panel: pl.DataFrame,
    output_dir: Path | str = "data/analytics/industry_trend",
    as_of: date | None = None,
    update_latest: bool = True,
    run_class: Literal["official", "backfill", "experiment"] = "official",
    config_path: Path | str = DEFAULT_CONFIG_PATH,
) -> ArtifactRunPaths:
    """将产业趋势跟踪因子面板持久化到 ArtifactStore。"""
    if as_of is None:
        max_d = panel["trade_date"].max()
        if max_d is None or not isinstance(max_d, date):
            raise ValueError("无法获取有效的交易日期")
        as_of = max_d

    paths = ArtifactStore.build_run_paths(
        as_of_date=as_of, artifact_root=output_dir, run_class=run_class
    )
    manifest = build_manifest_base(
        artifact_type="industry_trend_panel",
        schema_version=1,
        title="申万行业产业趋势跟踪因子面板",
        run_id=paths.run_dir.name,
        as_of_date=as_of,
        artifact_root=output_dir,
        config_path=config_path,
    )
    manifest["methodology"] = {
        "framework": "方向(全球) × 供需(量价齐升) × 议价权(毛利率扩张) + 现实景气 − 拥挤度",
        "trend_lookback": load_industry_trend_config(config_path).trend_lookback,
    }

    with ArtifactWriteSession(paths, update_latest=update_latest) as session:
        session.write_parquet("industry_trend_panel.parquet", panel)
        session.write_json("manifest.json", manifest)

    logger.info(f"产业趋势跟踪因子面板已写入: {paths.run_dir}")
    return paths


def load_latest_industry_trend_panel(
    artifact_root: Path | str = "data/analytics/industry_trend",
) -> tuple[Path, pl.DataFrame, dict[str, Any]]:
    """读取最新的产业趋势跟踪因子面板产物。"""
    root = Path(artifact_root)
    latest_file = root / "latest" / "industry_trend_panel.parquet"
    if latest_file.exists():
        panel = pl.read_parquet(latest_file)
        manifest_file = root / "latest" / "manifest.json"
        manifest: dict[str, Any] = {}
        if manifest_file.exists():
            try:
                import json

                manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return latest_file.parent, panel, manifest

    logger.info("未找到本地落盘产业趋势面板，正在即时计算...")
    panel = build_industry_trend_panel()
    paths = save_industry_trend_panel(panel, output_dir=artifact_root, update_latest=True)
    return paths.run_dir, panel, {}


__all__ = [
    "build_industry_trend_panel",
    "load_global_resonance_scores",
    "load_latest_industry_trend_panel",
    "save_industry_trend_panel",
]
