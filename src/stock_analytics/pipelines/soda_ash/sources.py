"""纯碱全景对账管线数据读取层（供给/产能/库存基础输入）。

Curated 事实一律通过 ``DataCatalog``（或鸭子类型测试替身）读取，不直接拼接
``data/curated`` 物理路径；NBS 纯碱/平板玻璃同比产量目前仅存在于 RAW 标准化
CSV（含 ``output_yoy`` 列），通过配置路径读取（完整 Curated 化为后续工作项）。

市场侧读取（价差/龙虎榜/期货/现货基差/公司面板）见 :mod:`market_sources`。

读取语义：
- NBS 产量为核心输入，文件缺失时 fail-closed；
- 其余为可选输入，缺失或读取失败时返回空表，由合并层容错。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import polars as pl

_SODA_ASH_PRODUCT_NAME = "纯碱"
_SODA_ASH_HS_PREFIX = "283620"
_CZCE_SYMBOL = "SA"


class DatasetReader(Protocol):
    """DataCatalog 的最小读取契约（测试可用鸭子类型替身）。"""

    def load_dataset(self, dataset: str) -> pl.DataFrame: ...


def calculate_implied_shipment_rate(
    weekly_output: float | None,
    current_inv: float | None,
    prev_inv: float | None,
) -> float | None:
    """基于物理守恒推导周度产销率 / 出货率（百分比）。

    公式: (weekly_output - (current_inv - prev_inv)) / weekly_output * 100.0
    """
    if weekly_output is None or weekly_output <= 0:
        return None
    if current_inv is None or prev_inv is None:
        return None
    delta_inv = current_inv - prev_inv
    rate = (weekly_output - delta_inv) / weekly_output * 100.0
    return round(rate, 2)


def load_capacity_projects(path: Path | str) -> list[dict[str, Any]]:
    """加载结构化产能投产事件库；文件缺失时返回空列表。"""
    import yaml

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


def load_nbs_soda_ash(path: Path | str) -> pl.DataFrame:
    """加载 NBS 纯碱月度产量（核心输入，缺失即报错）。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"NBS 纯碱产量文件缺失: {p}")
    df = pl.read_csv(p)
    return df.select(
        [
            pl.col("report_month"),
            pl.col("output_current").cast(pl.Float64, strict=False).alias("soda_output_w_tons"),
            pl.col("output_yoy").cast(pl.Float64, strict=False).alias("soda_output_yoy"),
        ]
    ).filter(pl.col("report_month").is_not_null())


def load_nbs_plate_glass(path: Path | str) -> pl.DataFrame:
    """加载 NBS 下游平板玻璃月度产量（可选输入）。"""
    p = Path(path)
    if not p.exists():
        return pl.DataFrame()
    df = pl.read_csv(p)
    return df.select(
        [
            pl.col("report_month"),
            pl.col("output_current").cast(pl.Float64, strict=False).alias("glass_output_w_cases"),
            pl.col("output_yoy").cast(pl.Float64, strict=False).alias("glass_output_yoy"),
        ]
    ).filter(pl.col("report_month").is_not_null())


def load_customs_export(
    catalog: DatasetReader,
    dataset: str,
    fallback: str,
) -> pl.DataFrame:
    """加载海关纯碱月度出口量与金额（按 8 位税号 283620xx / product_key 聚合）。

    对齐 ``customs_trade_gacc`` 真实 Curated 契约（``CUSTOMS_TRADE_SCHEMA``）：

    - 数量列为 ``export_volume``（GACC 原始单位为千克），按 ``quantity_unit_norm``
      归一为吨；旧别名 ``export_quantity`` 仍兼容；
    - 该表无逐月同比列，缺失 ``yoy_growth`` 时按实物量滞后 12 期自算 YoY（百分比），
      避免把 ratio 口径（0.15 = 15%）直接当百分比比较；
    - 存在 ``trade_direction`` 时仅保留 export 行，防止进口混入抬高出口量。
    """
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
                cond = cond | pl.col("hs_code").cast(pl.String).str.starts_with(_SODA_ASH_HS_PREFIX)
            if "product_key" in df.columns:
                cond = cond | (pl.col("product_key") == "soda_ash")
            filtered = df.filter(cond)
        except Exception:
            continue
        if filtered.is_empty():
            continue
        if "trade_direction" in filtered.columns:
            filtered = filtered.filter(pl.col("trade_direction") == "export")
            if filtered.is_empty():
                continue
        date_col = _pick_date_column(filtered, ("report_month", "period", "trade_date", "date"))
        if date_col is None:
            continue
        qty_col = next(
            (
                col
                for col in ("export_volume", "export_quantity", "quantity", "qty")
                if col in filtered.columns
            ),
            None,
        )
        val_col = next(
            (
                col
                for col in ("export_value_usd", "value_usd", "amount_usd")
                if col in filtered.columns
            ),
            None,
        )
        if qty_col is None or val_col is None:
            continue

        qty_factor = _quantity_to_tons_factor(filtered)
        agg_exprs: list[pl.Expr] = [
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
        if "export_qty_yoy" not in grouped.columns:
            grouped = grouped.with_columns(
                (
                    (pl.col("export_qty_tons") / pl.col("export_qty_tons").shift(12) - 1.0) * 100.0
                ).alias("export_qty_yoy")
            )
        return grouped
    return pl.DataFrame()


def _quantity_to_tons_factor(df: pl.DataFrame) -> float:
    """按数量单位列推断折算为吨的除数（kg/千克 → 1000，其余 → 1）。"""
    unit_col = next(
        (col for col in ("quantity_unit_norm", "quantity_unit") if col in df.columns), None
    )
    if unit_col is None:
        return 1.0
    try:
        units = (
            df.get_column(unit_col)
            .drop_nulls()
            .cast(pl.String)
            .str.to_lowercase()
            .unique()
            .head(5)
            .to_list()
        )
    except Exception:
        return 1.0
    return 1000.0 if any("kg" in unit or "千克" in unit for unit in units) else 1.0


def load_warehouse_receipts(catalog: DatasetReader, dataset: str) -> pl.DataFrame:
    """加载郑商所纯碱期货注册仓单（月均与月末值）。"""
    df = _load_symbol_dataset(catalog, dataset, _CZCE_SYMBOL)
    if df.is_empty():
        return pl.DataFrame()
    date_col = _pick_date_column(df, ("trade_date", "date", "report_date"))
    if date_col is None or "inventory" not in df.columns:
        return pl.DataFrame()
    return (
        df.with_columns(
            pl.col(date_col).cast(pl.String).str.slice(0, 7).alias("report_month"),
            pl.col("inventory").cast(pl.Float64, strict=False),
        )
        .sort(date_col)
        .group_by("report_month", maintain_order=True)
        .agg(
            [
                pl.col("inventory").last().alias("warehouse_receipt_month_end"),
                pl.col("inventory").mean().alias("warehouse_receipt_avg"),
            ]
        )
        .sort("report_month")
    )


def load_factory_inventory(catalog: DatasetReader, dataset: str) -> pl.DataFrame:
    """加载样本企业周度厂库与出货率（含物理守恒推导补算）。"""
    try:
        df = catalog.load_dataset(dataset)
    except Exception:
        return pl.DataFrame()
    if df.is_empty() or "product_name" not in df.columns:
        return pl.DataFrame()
    filtered = df.filter(pl.col("product_name") == _SODA_ASH_PRODUCT_NAME)
    if filtered.is_empty():
        return pl.DataFrame()

    date_col = _pick_date_column(filtered, ("report_date", "trade_date", "date"))
    if date_col is None:
        return pl.DataFrame()

    sorted_df = filtered.sort(date_col)
    rows = sorted_df.to_dicts()
    prev_inv: float | None = None
    for r in rows:
        cur_inv_raw = r.get("factory_inventory_w_tons")
        cur_inv = (
            float(cur_inv_raw)
            if cur_inv_raw is not None and str(cur_inv_raw).strip() != ""
            else None
        )
        out_raw = r.get("weekly_output_w_tons")
        out = float(out_raw) if out_raw is not None and str(out_raw).strip() != "" else None
        rate_raw = r.get("shipment_rate_pct")
        rate = float(rate_raw) if rate_raw is not None and str(rate_raw).strip() != "" else None

        if (
            rate is None
            and cur_inv is not None
            and prev_inv is not None
            and out is not None
            and out > 0
        ):
            implied = calculate_implied_shipment_rate(out, cur_inv, prev_inv)
            if implied is not None:
                r["shipment_rate_pct"] = implied
        if cur_inv is not None:
            prev_inv = cur_inv

    enhanced = pl.DataFrame(rows)
    return (
        enhanced.with_columns(
            pl.col(date_col).cast(pl.String).str.slice(0, 7).alias("report_month"),
            pl.col("factory_inventory_w_tons").cast(pl.Float64, strict=False),
            pl.col("operating_rate_pct").cast(pl.Float64, strict=False),
            pl.col("shipment_rate_pct").cast(pl.Float64, strict=False),
        )
        .sort(date_col)
        .group_by("report_month", maintain_order=True)
        .agg(
            [
                pl.col("factory_inventory_w_tons")
                .drop_nulls()
                .last()
                .alias("factory_inv_month_end_w_tons"),
                pl.col("factory_inventory_w_tons")
                .drop_nulls()
                .mean()
                .alias("factory_inv_avg_w_tons"),
                pl.col("operating_rate_pct").drop_nulls().mean().alias("survey_operating_rate_pct"),
                pl.col("shipment_rate_pct").drop_nulls().mean().alias("survey_shipment_rate_pct"),
                pl.col("shipment_rate_pct").drop_nulls().last().alias("latest_shipment_rate_pct"),
            ]
        )
        .sort("report_month")
    )


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
        df = df.filter(pl.col("symbol") == symbol)
    return df


def _pick_date_column(df: pl.DataFrame, candidates: tuple[str, ...]) -> str | None:
    return next((col for col in candidates if col in df.columns), None)


__all__ = [
    "DatasetReader",
    "calculate_implied_shipment_rate",
    "load_capacity_projects",
    "load_customs_export",
    "load_factory_inventory",
    "load_nbs_plate_glass",
    "load_nbs_soda_ash",
    "load_warehouse_receipts",
]
