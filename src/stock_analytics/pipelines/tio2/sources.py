"""钛白粉全景对账管线数据读取层（供给/产能/海关出口基础输入）。

Curated 事实一律通过 ``DataCatalog``（或鸭子类型测试替身）读取，不直接拼接
``data/curated`` 物理路径。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

import polars as pl
import yaml

logger = logging.getLogger(__name__)

_TIO2_PRODUCT_NAME = "钛白粉"
_TIO2_SYMBOL = "TiO2"
_TIO2_HS_PREFIX = "320611"


class DatasetReader(Protocol):
    """DataCatalog 的最小读取契约（测试可用鸭子类型替身）。"""

    def load_dataset(self, dataset: str) -> pl.DataFrame: ...


def _pick_date_column(df: pl.DataFrame, candidates: Sequence[str]) -> str | None:
    for col in candidates:
        if col in df.columns:
            return col
    return None


def _load_symbol_dataset(
    catalog: DatasetReader,
    dataset: str,
    symbol: str,
) -> pl.DataFrame:
    try:
        df = catalog.load_dataset(dataset)
    except Exception:
        return pl.DataFrame()
    if df.is_empty():
        return pl.DataFrame()
    if "symbol" in df.columns:
        return df.filter(pl.col("symbol") == symbol)
    return df


def load_capacity_projects(path: Path | str) -> list[dict[str, Any]]:
    """加载结构化产能投产事件库；文件缺失时返回空列表。"""
    p = Path(path)
    if not p.exists():
        return []
    try:
        payload = yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    projects = payload.get("projects", [])
    return [item for item in projects if isinstance(item, dict)]


def load_cost_models(path: Path | str) -> dict[str, Any]:
    """加载理论生产工艺成本模型与利润区间阈值。"""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        payload = yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def load_customs_export(
    catalog: DatasetReader,
    dataset: str,
    fallback: str,
) -> pl.DataFrame:
    """加载海关钛白粉月度出口量与金额（按 8 位税号 320611xx / tio2 聚合）。"""
    for name in (dataset, fallback):
        try:
            df = catalog.load_dataset(name)
        except Exception:
            continue
        if df.is_empty():
            continue
        try:
            cond = pl.lit(False)
            if "hs_code" in df.columns:
                cond = cond | pl.col("hs_code").cast(pl.String).str.starts_with(_TIO2_HS_PREFIX)
            if "product_key" in df.columns:
                cond = cond | (pl.col("product_key") == "tio2")
            if "product_code" in df.columns:
                cond = cond | (pl.col("product_code") == "tio2")
            if "product" in df.columns:
                cond = cond | (pl.col("product") == "tio2")
            filtered = df.filter(cond)
        except Exception:
            continue
        if filtered.is_empty():
            continue
        # 出口口径：只统计 export 行，剔除 import（防止进出口混入抬高“出口量/均价”）
        if "trade_direction" in filtered.columns:
            filtered = filtered.filter(pl.col("trade_direction") == "export")
            if filtered.is_empty():
                continue
        date_col = _pick_date_column(filtered, ("report_month", "period", "trade_date", "date"))
        if date_col is None:
            continue

        # 检查数量与金额列
        qty_col = next(
            (
                c
                for c in ("export_volume", "export_quantity", "quantity", "qty")
                if c in filtered.columns
            ),
            None,
        )
        val_col = next(
            (c for c in ("export_value_usd", "value_usd", "amount_usd") if c in filtered.columns),
            None,
        )
        if qty_col is None or val_col is None:
            continue

        # 数量单位归一化：若为千克 (kg / 千克)，折算为吨 (tons)
        # 优先读取已规范化的 quantity_unit_norm（kg/ton），否则兼容原始中文单位列
        unit_col = next(
            (c for c in ("quantity_unit_norm", "quantity_unit") if c in filtered.columns),
            None,
        )
        is_kg = False
        if unit_col is not None:
            units = (
                filtered.get_column(unit_col)
                .drop_nulls()
                .str.to_lowercase()
                .unique()
                .head(5)
                .to_list()
            )
            is_kg = any("kg" in u or "千克" in u for u in units)
        qty_factor = 1000.0 if is_kg else 1.0

        agg_exprs = [
            (pl.col(qty_col).cast(pl.Float64, strict=False) / qty_factor)
            .sum()
            .alias("export_qty_tons"),
            pl.col(val_col).cast(pl.Float64, strict=False).sum().alias("export_value_usd"),
        ]
        if "yoy_growth" in filtered.columns:
            agg_exprs.append(
                pl.col("yoy_growth").cast(pl.Float64, strict=False).mean().alias("export_qty_yoy")
            )

        grouped = (
            filtered.with_columns(
                pl.col(date_col).cast(pl.String).str.slice(0, 7).alias("report_month")
            )
            .group_by("report_month")
            .agg(agg_exprs)
            .sort("report_month")
        )

        # 补齐计算指标
        if "export_qty_yoy" not in grouped.columns:
            # 数据驱动计算 YoY (滞后 12 期)
            grouped = grouped.with_columns(
                (
                    (pl.col("export_qty_tons") / pl.col("export_qty_tons").shift(12) - 1.0) * 100.0
                ).alias("export_qty_yoy")
            )

        grouped = grouped.with_columns(
            (
                pl.when(pl.col("export_qty_tons") > 0)
                .then(pl.col("export_value_usd") / pl.col("export_qty_tons"))
                .otherwise(None)
            ).alias("export_unit_price_usd")
        )
        return grouped

    return pl.DataFrame()


def load_spot_price(catalog: DatasetReader, dataset: str) -> pl.DataFrame:
    """加载生意社 100ppi 钛白粉现货出厂基准价（月度均价）。"""
    df = _load_symbol_dataset(catalog, dataset, _TIO2_SYMBOL)
    if df.is_empty():
        return pl.DataFrame()
    date_col = _pick_date_column(df, ("trade_date", "date", "release_date"))
    if date_col is None:
        return pl.DataFrame()

    price_col = next(
        (c for c in ("spot_price_cny", "spot_price", "price") if c in df.columns), None
    )
    if price_col is None:
        return pl.DataFrame()

    return (
        df.sort(date_col)
        .with_columns(
            pl.col(date_col).cast(pl.String).str.slice(0, 7).alias("report_month"),
            pl.col(price_col).cast(pl.Float64, strict=False).alias("spot_price_cny"),
        )
        .group_by("report_month")
        .agg(
            [
                pl.col("spot_price_cny").mean().alias("tio2_spot_price_cny"),
                pl.col("spot_price_cny").last().alias("tio2_spot_price_month_end"),
            ]
        )
        .sort("report_month")
    )
