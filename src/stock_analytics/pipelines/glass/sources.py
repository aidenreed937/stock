"""玻璃全景管线输入数据读取。

支持通过 DataCatalog（或测试替身）读取 Curated 事实，兼容本地 CSV/YAML。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol

import polars as pl
import yaml

logger = logging.getLogger(__name__)

_FG_SYMBOL = "FG"
_PVG_SYMBOL = "PVG"


class DatasetReader(Protocol):
    def load_dataset(self, name: str) -> pl.DataFrame: ...


def load_capacity_furnaces(path: Path | str) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        furnaces = data.get("furnaces", [])
        return furnaces if isinstance(furnaces, list) else []
    except Exception as e:
        logger.debug("读取玻璃窑炉种子库失败: %s", e)
        return []


def load_nbs_plate_glass(csv_path: Path | str) -> pl.DataFrame:
    path = Path(csv_path)
    if not path.exists():
        return pl.DataFrame()
    try:
        df = pl.read_csv(path)
        return df.select(
            pl.col("report_month").cast(pl.String),
            pl.col("output_current").cast(pl.Float64, strict=False).alias("glass_output_w_cases"),
            pl.col("output_yoy").cast(pl.Float64, strict=False).alias("glass_output_yoy"),
        ).sort("report_month")
    except Exception as exc:
        logger.debug("读取 NBS 平板玻璃失败: %s", exc)
        return pl.DataFrame()


def load_nbs_soda_ash(csv_path: Path | str) -> pl.DataFrame:
    path = Path(csv_path)
    if not path.exists():
        return pl.DataFrame()
    try:
        df = pl.read_csv(path)
        return df.select(
            pl.col("report_month").cast(pl.String),
            pl.col("output_current").cast(pl.Float64, strict=False).alias("soda_output_w_tons"),
            pl.col("output_yoy").cast(pl.Float64, strict=False).alias("soda_output_yoy"),
        ).sort("report_month")
    except Exception as exc:
        logger.debug("读取 NBS 纯碱失败: %s", exc)
        return pl.DataFrame()


def load_customs_glass(catalog: DatasetReader, dataset: str, fallback_dataset: str) -> pl.DataFrame:
    for name in (dataset, fallback_dataset):
        try:
            df = catalog.load_dataset(name)
        except Exception:
            continue
        if df.is_empty():
            continue
        filtered = df.filter(
            pl.col("hs_code").str.starts_with("7005") | pl.col("product_name").str.contains("玻璃")
        )
        if filtered.is_empty():
            continue
        vol_col = "export_volume" if "export_volume" in filtered.columns else "qty"
        val_col = "export_value_usd" if "export_value_usd" in filtered.columns else "amount_usd"
        return (
            filtered.with_columns(
                pl.col("report_month").cast(pl.String),
                pl.col(vol_col).cast(pl.Float64, strict=False).alias("export_qty_kg"),
                pl.col(val_col).cast(pl.Float64, strict=False).alias("export_value_usd"),
            )
            .group_by("report_month")
            .agg(
                pl.col("export_qty_kg").sum().alias("export_qty_kg"),
                pl.col("export_value_usd").sum().alias("export_value_usd"),
            )
            .sort("report_month")
        )
    return pl.DataFrame()


def load_warehouse_receipts(catalog: DatasetReader, dataset: str) -> pl.DataFrame:
    try:
        df = catalog.load_dataset(dataset)
    except Exception:
        return pl.DataFrame()
    if df.is_empty():
        return pl.DataFrame()
    sub = df.filter(pl.col("symbol") == _FG_SYMBOL)
    if sub.is_empty():
        return pl.DataFrame()
    rec_col = "inventory" if "inventory" in sub.columns else "receipt_volume"
    return (
        sub.with_columns(
            pl.col("trade_date").cast(pl.String).str.slice(0, 7).alias("report_month"),
            pl.col(rec_col).cast(pl.Float64, strict=False).alias("receipt_volume"),
        )
        .sort("trade_date")
        .group_by("report_month", maintain_order=True)
        .agg(
            pl.col("receipt_volume").last().alias("warehouse_receipt_month_end"),
            pl.col("receipt_volume").mean().alias("warehouse_receipt_avg"),
        )
        .sort("report_month")
    )


def load_futures_daily(catalog: DatasetReader, dataset: str) -> pl.DataFrame:
    try:
        df = catalog.load_dataset(dataset)
    except Exception:
        return pl.DataFrame()
    if df.is_empty():
        return pl.DataFrame()
    sub = df.filter(pl.col("symbol") == _FG_SYMBOL)
    if sub.is_empty():
        return pl.DataFrame()
    return (
        sub.with_columns(
            pl.col("trade_date").cast(pl.String).str.slice(0, 7).alias("report_month"),
            pl.col("settle").cast(pl.Float64, strict=False),
            pl.col("close").cast(pl.Float64, strict=False),
        )
        .sort("trade_date")
        .group_by("report_month", maintain_order=True)
        .agg(
            pl.col("settle").drop_nulls().last().alias("futures_settle_month_end"),
            pl.col("settle").drop_nulls().mean().alias("futures_settle_avg"),
            pl.col("close").drop_nulls().last().alias("futures_close_month_end"),
        )
        .sort("report_month")
    )


def load_weekly_survey(catalog: DatasetReader, dataset: str) -> pl.DataFrame:
    try:
        df = catalog.load_dataset(dataset)
    except Exception:
        return pl.DataFrame()
    if df.is_empty():
        return pl.DataFrame()
    sub = df.filter(pl.col("symbol") == _FG_SYMBOL)
    if sub.is_empty():
        return pl.DataFrame()
    return (
        sub.with_columns(
            pl.col("trade_date").cast(pl.String).str.slice(0, 7).alias("report_month"),
            pl.col("operating_rate_pct").cast(pl.Float64, strict=False),
            pl.col("weekly_output_w_tons").cast(pl.Float64, strict=False),
            pl.col("factory_inventory_w_tons").cast(pl.Float64, strict=False),
            pl.col("shipment_rate_pct").cast(pl.Float64, strict=False),
        )
        .sort("trade_date")
        .group_by("report_month", maintain_order=True)
        .agg(
            pl.col("operating_rate_pct").mean().alias("survey_operating_rate_pct"),
            pl.col("weekly_output_w_tons").last().alias("survey_weekly_output_w_tons"),
            pl.col("factory_inventory_w_tons").last().alias("factory_inv_month_end_w_tons"),
            pl.col("shipment_rate_pct").mean().alias("survey_shipment_rate_pct"),
            pl.col("shipment_rate_pct").last().alias("latest_shipment_rate_pct"),
        )
        .sort("report_month")
    )


def load_spot_benchmarks(catalog: DatasetReader, dataset: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    try:
        df = catalog.load_dataset(dataset)
    except Exception:
        return result
    if df.is_empty():
        return result

    for sym, key in (
        ("FG", "fg_spot_price"),
        ("PVG_2mm", "pvg_2mm_spot_price"),
        ("PVG_3.2mm", "pvg_3_2mm_spot_price"),
        ("SA", "soda_heavy_spot_price"),
        ("ZC", "coal_spot_price"),
    ):
        try:
            sub = df.filter(pl.col("symbol") == sym).sort("trade_date")
            if not sub.is_empty():
                result[key] = float(sub["spot_price_cny"].to_list()[-1])
                result[f"{key}_date"] = str(sub["trade_date"].to_list()[-1])
        except Exception:
            continue
    return result


__all__ = [
    "DatasetReader",
    "load_capacity_furnaces",
    "load_customs_glass",
    "load_futures_daily",
    "load_nbs_plate_glass",
    "load_nbs_soda_ash",
    "load_spot_benchmarks",
    "load_warehouse_receipts",
    "load_weekly_survey",
]
