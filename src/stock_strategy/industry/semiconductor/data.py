"""半导体深研线回测/IC 验证的数据加载层。

消费上游产物与 Mart：
- 剪刀差/结构腿：`stock_analytics.pipelines.semiconductor` 门面 latest 产物（经包级门面导入）；
- 行业收盘与剪刀差：`data/curated/mart/industry_l2_panel_daily.parquet`；
- 供给端确认腿（utilization/inventory）：`data/curated/mart/semiconductor_supply_legs.parquet`。

仅按需读取，不重新计算腿，不修改数据。
术语约定：本层（stock_strategy）是**验证层**——消费 stock_analytics 产出的特征
（feature / 候选因子），通过 IC / 回测 / 敏感性扫描**验证其是否为有效因子（factor）**。
本层不产生新特征。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from stock_core.utils.logger import logger
from stock_data.core.runtime import DataRuntimeContext

_INDUSTRY = "270100"
_START = date(2018, 1, 1)

_L2_PANEL_MART = "industry_l2_panel_daily.parquet"
_SUPPLY_LEGS_MART = "semiconductor_supply_legs.parquet"


def _read_mart(runtime: DataRuntimeContext, name: str) -> pl.DataFrame:
    path = runtime.data_root / "curated" / "mart" / name
    if not path.exists():
        raise FileNotFoundError(f"缺少 Mart: {path}")
    return pl.read_parquet(path)


def load_semiconductor_panel(
    *,
    storage_dir: Path | str | None = None,
    industry: str = _INDUSTRY,
    start_date: date = _START,
) -> pl.DataFrame:
    """加载半导体研究面板（默认 270100）。

    输出列：trade_date, close, scissors_score(direction), demand_score, supply_score,
            ai_capex_score, storage_score, utilization_score, inventory_score。
    供给腿缺失时对应列为空（不阻断）。
    """
    runtime = (
        DataRuntimeContext.from_root(storage_dir)
        if storage_dir
        else DataRuntimeContext.from_root("data")
    )

    panel = _read_mart(runtime, _L2_PANEL_MART)
    semi = (
        panel.filter((pl.col("industry_code") == industry) & (pl.col("trade_date") >= start_date))
        .select(["trade_date", "close"])
        .sort("trade_date")
    )

    from stock_analytics.pipelines.semiconductor import load_latest_semiconductor_legs

    legs_root = runtime.data_root / "analytics" / "semiconductor" if storage_dir else None
    legs = load_latest_semiconductor_legs(artifact_root=legs_root)
    legs_semi = legs.filter(pl.col("industry_code") == industry).select(
        [
            "trade_date",
            "demand_score",
            "supply_score",
            "scissors_score",
            "ai_capex_score",
            "storage_score",
        ]
    )

    merged = semi.join(legs_semi, on="trade_date", how="left", coalesce=True).sort("trade_date")

    # 供给端确认腿（utilization/inventory）——可空，缺失不阻断
    try:
        supply = _read_mart(runtime, _SUPPLY_LEGS_MART)
        supply_semi = supply.filter(pl.col("industry_code") == industry).select(
            ["trade_date", "utilization_score", "inventory_score"]
        )
        merged = merged.join(supply_semi, on="trade_date", how="left", coalesce=True)
    except FileNotFoundError as exc:
        logger.warning("半导体供给端确认腿缺失，utilization/inventory 为空: %s", exc)
        merged = merged.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("utilization_score"),
            pl.lit(None, dtype=pl.Float64).alias("inventory_score"),
        )

    return merged


__all__ = ["load_semiconductor_panel"]
