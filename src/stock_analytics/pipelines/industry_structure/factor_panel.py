"""申万 31 行业中观 5 大量化因子特征面板生成器。

计算 5 大标准化、无量纲 (0~100) 中观因子：
1. ind_momentum: 景气动量因子 (20/60D 动量 + MA20 偏离度)
2. ind_scissors: 供需剪刀差因子 (净利润增速 - 营收增速，衡量毛利率扩张与定价权)
3. ind_crowding: 拥挤过热因子 (成交额占比 5Y 滚动分位数)
4. ind_valuation: 估值赔率因子 (100 - PE/PB 滚动 5Y 分位数)
5. ind_smart_flow: 聪明资金流因子 (北向资金变动 + 机构大单净流入占比)
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any, Literal

import polars as pl
import yaml

from stock_analytics.pipelines.artifacts import (
    ArtifactRunPaths,
    ArtifactStore,
    ArtifactWriteSession,
    build_manifest_base,
)
from stock_core.exceptions import DataValidationError
from stock_data.catalog import DataCatalog
from stock_data.core.runtime import DataRuntimeContext

logger = logging.getLogger(__name__)

_DEFAULT_START_DATE = date(2015, 1, 1)


def _cs_percentile(col: str) -> pl.Expr:
    """横截面百分位计算: (rank - 1) / (count - 1) * 100."""
    return (
        (
            (pl.col(col).rank(method="average").over("trade_date") - 1.0)
            / (pl.col(col).count().over("trade_date") - 1.0)
            * 100.0
        )
        .fill_nan(50.0)
        .fill_null(50.0)
    )


def build_industry_factor_panel(
    *,
    catalog: DataCatalog | None = None,
    as_of: date | None = None,
    start_date: date = _DEFAULT_START_DATE,
    config_path: Path | str = "config/analytics/industry_factors.yaml",
) -> pl.DataFrame:
    """构建全历史申万 31 行业 5 大中观量化因子面板。

    Returns:
        包含 trade_date, industry_code, industry_name, close 及 5 大因子的 DataFrame。
    """
    runtime = catalog.runtime if catalog else DataRuntimeContext.from_root("data")
    mart_dir = runtime.data_root / "curated" / "mart"

    panel_daily_path = mart_dir / "industry_panel_daily.parquet"
    industry_daily_path = mart_dir / "industry_daily.parquet"
    northbound_path = mart_dir / "northbound_industry_daily.parquet"
    insider_path = mart_dir / "insider_industry_daily.parquet"

    if not panel_daily_path.exists() or not industry_daily_path.exists():
        raise DataValidationError(
            "缺少 industry_panel_daily.parquet 或 industry_daily.parquet 数据表"
        )

    p_daily = pl.read_parquet(panel_daily_path)
    i_daily = pl.read_parquet(industry_daily_path)

    # 1. 关联行业基础日行情
    df = p_daily.join(
        i_daily.select(
            ["trade_date", "industry_code", "close", "amount_yi", "tcr", "tcr_percentile"]
        ),
        left_on=["as_of_date", "industry_code"],
        right_on=["trade_date", "industry_code"],
        how="left",
        suffix="_idaily",
    ).rename({"as_of_date": "trade_date"})

    df = df.filter(pl.col("trade_date") >= start_date)
    if as_of is not None:
        df = df.filter(pl.col("trade_date") <= as_of)

    df = df.sort(["trade_date", "industry_code"])

    # 2. 北向资金因子提取 (若存在)
    if northbound_path.exists():
        try:
            nb_df = pl.read_parquet(northbound_path).select(
                ["trade_date", "industry_code", "hold_value_pct_chg"]
            )
            df = df.join(nb_df, on=["trade_date", "industry_code"], how="left")
        except Exception:
            df = df.with_columns(pl.lit(None, dtype=pl.Float64).alias("hold_value_pct_chg"))
    else:
        df = df.with_columns(pl.lit(None, dtype=pl.Float64).alias("hold_value_pct_chg"))

    # 3. 产业资本增减持与回购因子提取 (若存在)
    if insider_path.exists():
        try:
            ins_df = pl.read_parquet(insider_path).select(
                ["trade_date", "industry_code", "insider_net_amount_yi_60d"]
            )
            df = df.join(ins_df, on=["trade_date", "industry_code"], how="left")
        except Exception:
            df = df.with_columns(pl.lit(None, dtype=pl.Float64).alias("insider_net_amount_yi_60d"))
    else:
        df = df.with_columns(pl.lit(None, dtype=pl.Float64).alias("insider_net_amount_yi_60d"))

    # 4. 构造各因子原始计算列
    scissors_raw = pl.col("profit_growth_ttm").fill_null(0.0) - pl.col(
        "revenue_growth_ttm"
    ).fill_null(0.0)
    val_raw = 100.0 - pl.mean_horizontal(["pe_percentile_5y", "pb_percentile_5y"]).fill_null(50.0)

    computed = df.with_columns(
        [
            _cs_percentile("return_20d").alias("ret20_pct"),
            _cs_percentile("return_60d").alias("ret60_pct"),
            _cs_percentile("ma_bias_20d").alias("mabias_pct"),
            scissors_raw.alias("scissors_raw"),
            val_raw.alias("val_raw"),
            _cs_percentile("large_money_net_inflow_share_20d").alias("flow_pct"),
            pl.col("tcr_percentile").fill_null(_cs_percentile("amount_yi")).alias("ind_crowding"),
            _cs_percentile("hold_value_pct_chg").alias("nb_flow_pct"),
            _cs_percentile("insider_net_amount_yi_60d").alias("insider_flow_pct"),
        ]
    )

    # 5. 聚合为 5 大标准化中观因子 (0~100)
    # ind_smart_flow 三维融合: 60% 机构大单 + 25% 北向资金 + 15% 产业资本 (自适应平滑降级)
    smart_flow_expr = (
        pl.when(
            pl.col("hold_value_pct_chg").is_not_null()
            & pl.col("insider_net_amount_yi_60d").is_not_null()
        )
        .then(
            0.60 * pl.col("flow_pct")
            + 0.25 * pl.col("nb_flow_pct")
            + 0.15 * pl.col("insider_flow_pct")
        )
        .when(pl.col("insider_net_amount_yi_60d").is_not_null())
        .then(0.75 * pl.col("flow_pct") + 0.25 * pl.col("insider_flow_pct"))
        .when(pl.col("hold_value_pct_chg").is_not_null())
        .then(0.65 * pl.col("flow_pct") + 0.35 * pl.col("nb_flow_pct"))
        .otherwise(pl.col("flow_pct"))
    )

    factors_df = computed.with_columns(
        [
            (
                0.35 * pl.col("ret20_pct")
                + 0.35 * pl.col("ret60_pct")
                + 0.30 * pl.col("mabias_pct")
            ).alias("ind_momentum"),
            _cs_percentile("scissors_raw").alias("ind_scissors"),
            pl.col("ind_crowding").alias("ind_crowding"),
            _cs_percentile("val_raw").alias("ind_valuation"),
            smart_flow_expr.alias("ind_smart_flow"),
        ]
    )

    # 5. 读取权重并合成 composite_industry_score
    weights = _load_weights(config_path)
    w_mom = weights.get("ind_momentum", 0.30)
    w_sci = weights.get("ind_scissors", 0.25)
    w_cro = weights.get("ind_crowding", 0.15)
    w_val = weights.get("ind_valuation", 0.15)
    w_flo = weights.get("ind_smart_flow", 0.15)

    result_df = factors_df.with_columns(
        (
            w_mom * pl.col("ind_momentum")
            + w_sci * pl.col("ind_scissors")
            + w_cro * (100.0 - pl.col("ind_crowding"))
            + w_val * pl.col("ind_valuation")
            + w_flo * pl.col("ind_smart_flow")
        ).alias("composite_industry_score")
    )

    return result_df.select(
        [
            "trade_date",
            "industry_code",
            "industry_name",
            "close",
            "ind_momentum",
            "ind_scissors",
            "ind_crowding",
            "ind_valuation",
            "ind_smart_flow",
            "composite_industry_score",
        ]
    ).sort(["trade_date", "industry_code"])


def _load_weights(config_path: Path | str) -> dict[str, float]:
    """读取因子权重配置。"""
    try:
        cfg_p = Path(config_path)
        if cfg_p.exists():
            data = yaml.safe_load(cfg_p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "weights" in data:
                return {k: float(v) for k, v in data["weights"].items()}
    except Exception as exc:
        logger.warning(f"读取因子权重配置失败: {exc}")
    return {
        "ind_momentum": 0.30,
        "ind_scissors": 0.25,
        "ind_crowding": 0.15,
        "ind_valuation": 0.15,
        "ind_smart_flow": 0.15,
    }


def save_industry_factor_panel(
    panel: pl.DataFrame,
    output_dir: Path | str = "data/analytics/industry_structure",
    as_of: date | None = None,
    update_latest: bool = True,
    run_class: Literal["official", "backfill", "experiment"] = "official",
) -> ArtifactRunPaths:
    """将因子面板持久化到 ArtifactStore。"""
    if as_of is None:
        max_d = panel["trade_date"].max()
        if max_d is None or not isinstance(max_d, date):
            raise ValueError("无法获取有效的交易日期")
        as_of = max_d

    paths = ArtifactStore.build_run_paths(
        as_of_date=as_of, artifact_root=output_dir, run_class=run_class
    )

    manifest = build_manifest_base(
        artifact_type="industry_factor_panel",
        schema_version=1,
        title="申万行业 5 大中观因子面板",
        run_id=paths.run_dir.name,
        as_of_date=as_of,
        artifact_root=output_dir,
        config_path="config/analytics/industry_factors.yaml",
    )

    with ArtifactWriteSession(paths, update_latest=update_latest) as session:
        session.write_parquet("industry_factor_panel.parquet", panel)
        session.write_json("manifest.json", manifest)

    logger.info(f"申万行业 5 大中观因子面板已写入: {paths.run_dir}")
    return paths


def load_latest_industry_factors(
    artifact_root: Path | str = "data/analytics/industry_structure",
) -> tuple[Path, pl.DataFrame, dict[str, Any]]:
    """读取最新的行业因子面板产物。"""
    root = Path(artifact_root)
    latest_file = root / "latest" / "industry_factor_panel.parquet"
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

    # 若未找到 latest 产物，即时生成
    logger.info("未找到本地落盘因子面板，正在即时计算...")
    panel = build_industry_factor_panel()
    paths = save_industry_factor_panel(panel, output_dir=artifact_root, update_latest=True)
    return paths.run_dir, panel, {}


__all__ = [
    "build_industry_factor_panel",
    "load_latest_industry_factors",
    "save_industry_factor_panel",
]
