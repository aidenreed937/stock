"""晶圆代工产能利用率黄金事实转换器。"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from datetime import date
from typing import Any

import polars as pl

from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.semiconductor.baseline import (
    apply_tsmc_utilization_baseline,
)
from stock_data.fetcher.industry.semiconductor.schemas import (
    FOUNDRY_CURATED_SCHEMA,
    FOUNDRY_RAW_SCHEMA,
)
from stock_data.fetcher.industry.semiconductor.transforms.release_date import (
    require_raw_release_dates,
)


def determine_foundry_utilization_regime(util_pct: float | None) -> str | None:
    """按加权产能利用率判定供需平衡状态。"""
    if util_pct is None:
        return None
    if util_pct >= 95.0:
        return "tight_overheated"
    if util_pct >= 85.0:
        return "healthy"
    if util_pct >= 75.0:
        return "oversupply"
    return "slump"


def build_foundry_raw_frame(
    items: Sequence[dict[str, Any]] | pl.DataFrame,
    collected_at: str | None = None,
) -> pl.DataFrame:
    """将晶圆代工采集结果整理为源端字段/字符串值优先的 RAW 帧。"""
    if isinstance(items, pl.DataFrame):
        if items.is_empty() and not items.columns:
            return pl.DataFrame(schema=FOUNDRY_RAW_SCHEMA)
        df_raw = _normalise_raw_frame(items)
        return _build_foundry_raw_frame(df_raw)
    if not items:
        return pl.DataFrame(schema=FOUNDRY_RAW_SCHEMA)

    now_iso = collected_at or now_utc_iso()
    rows = [
        {
            "report_quarter": _normalise_report_quarter(str(item["report_quarter"])),
            "trade_date": item["trade_date"],
            "tsmc_utilization_raw": _item_raw_string(
                item, "tsmc_utilization_raw", "tsmc_utilization_pct"
            ),
            "tsmc_wafer_shipments_12in_kpcs_raw": _item_raw_quantity_string(
                item,
                "tsmc_wafer_shipments_12in_kpcs_raw",
                "tsmc_wafer_shipments_12in_kpcs",
                " kpcs",
            ),
            "tsmc_capacity_12in_kpcs_raw": _item_raw_quantity_string(
                item,
                "tsmc_capacity_12in_kpcs_raw",
                "tsmc_capacity_12in_kpcs",
                " kpcs",
            ),
            "tsmc_utilization_status": _item_raw_string(item, "tsmc_utilization_status", ""),
            "smic_utilization_raw": _item_raw_string(
                item, "smic_utilization_raw", "smic_utilization_pct"
            ),
            "smic_monthly_capacity_raw": _item_raw_quantity_string(
                item,
                "smic_monthly_capacity_raw",
                "smic_monthly_capacity_8inch_kw",
                "千片",
            ),
            "smic_wafer_shipment_raw": _item_raw_quantity_string(
                item,
                "smic_wafer_shipment_raw",
                "smic_wafer_shipment_kw",
                "千片",
            ),
            "smic_utilization_status": _item_raw_string(item, "smic_utilization_status", ""),
            "source": item.get("source") or "SMIC_TSMC_IR",
            "source_url": item.get("source_url") or "",
            "release_date": item.get("release_date")
            or item.get("tsmc_release_date")
            or item.get("smic_release_date"),
            "data_status": item.get("data_status") or "actual",
            "collected_at": item.get("collected_at") or now_iso,
            "raw_content_sha256": item.get("raw_content_sha256") or "",
            "raw_snapshot_path": item.get("raw_snapshot_path") or "",
            "tsmc_source_url": item.get("tsmc_source_url") or "",
            "tsmc_release_date": item.get("tsmc_release_date"),
            "tsmc_raw_content_sha256": item.get("tsmc_raw_content_sha256") or "",
            "tsmc_raw_snapshot_path": item.get("tsmc_raw_snapshot_path") or "",
            "smic_source_url": item.get("smic_source_url") or "",
            "smic_release_date": item.get("smic_release_date"),
            "smic_raw_content_sha256": item.get("smic_raw_content_sha256") or "",
            "smic_raw_snapshot_path": item.get("smic_raw_snapshot_path") or "",
        }
        for item in items
    ]
    return _build_foundry_raw_frame(pl.DataFrame(rows, schema=FOUNDRY_RAW_SCHEMA))


def _build_foundry_raw_frame(df_raw: pl.DataFrame) -> pl.DataFrame:
    return require_raw_release_dates(
        (
            apply_tsmc_utilization_baseline(df_raw)
            .select(list(FOUNDRY_RAW_SCHEMA))
            .with_columns(
                [pl.col(name).cast(dtype).alias(name) for name, dtype in FOUNDRY_RAW_SCHEMA.items()]
            )
            .sort("trade_date")
        ),
        "foundry_capacity_utilization",
    )


def _item_raw_string(item: dict[str, Any], raw_key: str, fallback_key: str) -> str | None:
    value = item.get(raw_key)
    if value is None:
        value = item.get(fallback_key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _item_raw_quantity_string(
    item: dict[str, Any],
    raw_key: str,
    fallback_key: str,
    unit_suffix: str,
) -> str | None:
    value = item.get(raw_key)
    if value is not None:
        text = str(value).strip()
        return text or None
    value = item.get(fallback_key)
    if value is None:
        return None
    return f"{value}{unit_suffix}"


def _normalise_raw_frame(df: pl.DataFrame) -> pl.DataFrame:
    additions: list[pl.Expr] = []
    if "tsmc_utilization_raw" not in df.columns:
        additions.append(
            _string_expr_from_available(df, "tsmc_utilization_pct").alias("tsmc_utilization_raw")
        )
    if "smic_utilization_raw" not in df.columns:
        additions.append(
            _string_expr_from_available(df, "smic_utilization_pct").alias("smic_utilization_raw")
        )
    if "tsmc_wafer_shipments_12in_kpcs_raw" not in df.columns:
        additions.append(
            _string_expr_from_available(df, "tsmc_wafer_shipments_12in_kpcs", suffix=" kpcs").alias(
                "tsmc_wafer_shipments_12in_kpcs_raw"
            )
        )
    if "tsmc_capacity_12in_kpcs_raw" not in df.columns:
        additions.append(
            _string_expr_from_available(df, "tsmc_capacity_12in_kpcs", suffix=" kpcs").alias(
                "tsmc_capacity_12in_kpcs_raw"
            )
        )
    if "smic_monthly_capacity_raw" not in df.columns:
        additions.append(
            _string_expr_from_available(df, "smic_monthly_capacity_8inch_kw", suffix="千片").alias(
                "smic_monthly_capacity_raw"
            )
        )
    if "smic_wafer_shipment_raw" not in df.columns:
        additions.append(
            _string_expr_from_available(df, "smic_wafer_shipment_kw", suffix="千片").alias(
                "smic_wafer_shipment_raw"
            )
        )
    df = df.with_columns(additions) if additions else df
    return _with_missing_columns(df, FOUNDRY_RAW_SCHEMA)


def _with_missing_columns(df: pl.DataFrame, schema: dict[str, Any]) -> pl.DataFrame:
    additions: list[pl.Expr] = []
    for column, dtype in schema.items():
        if column not in df.columns:
            value = pl.lit("") if dtype == pl.String else pl.lit(None, dtype=dtype)
            additions.append(value.alias(column))
    return df.with_columns(additions) if additions else df


def build_foundry_utilization_frame(
    df_raw: pl.DataFrame,
    proxy_weights: dict[str, float] | None = None,
) -> pl.DataFrame:
    """从 RAW 表构建公司事实，并显式标记可计算的代表性代理指标。

    默认使用两家公司等权平均，仅在两家公司均有利用率时输出代理值；该值不是全球
    晶圆代工行业真实加权利用率。若传入 ``proxy_weights``，权重仍只代表配置的公司
    代理权重，不代表全球产能份额。
    """
    if df_raw.is_empty():
        return pl.DataFrame(schema=FOUNDRY_CURATED_SCHEMA)

    weights = _normalise_proxy_weights(proxy_weights)
    now_iso = now_utc_iso()
    rows: list[dict[str, Any]] = []
    for raw_row in df_raw.iter_rows(named=True):
        report_quarter = _normalise_report_quarter(raw_row.get("report_quarter"))
        if report_quarter is None:
            continue

        trade_date = _coerce_date(raw_row.get("trade_date")) or _quarter_end(report_quarter)
        tsmc_util = _coerce_percent(
            raw_row.get("tsmc_utilization_pct"), raw_row.get("tsmc_utilization_raw")
        )
        tsmc_shipments = _coerce_wafer_k(
            raw_row.get("tsmc_wafer_shipments_12in_kpcs"),
            raw_row.get("tsmc_wafer_shipments_12in_kpcs_raw"),
        )
        tsmc_capacity = _coerce_wafer_k(
            raw_row.get("tsmc_capacity_12in_kpcs"), raw_row.get("tsmc_capacity_12in_kpcs_raw")
        )
        tsmc_status = _normalise_utilization_status(
            raw_row.get("tsmc_utilization_status"), tsmc_util
        )
        if tsmc_util is None and tsmc_capacity is not None and tsmc_capacity > 0:
            if tsmc_shipments is not None:
                tsmc_util = round(tsmc_shipments / tsmc_capacity * 100.0, 2)
                tsmc_status = "derived"

        smic_util = _coerce_percent(
            raw_row.get("smic_utilization_pct"), raw_row.get("smic_utilization_raw")
        )
        smic_capacity = _coerce_wafer_k(
            raw_row.get("smic_monthly_capacity_8inch_kw"),
            raw_row.get("smic_monthly_capacity_raw"),
        )
        smic_shipments = _coerce_wafer_k(
            raw_row.get("smic_wafer_shipment_kw"), raw_row.get("smic_wafer_shipment_raw")
        )
        smic_status = _normalise_utilization_status(
            raw_row.get("smic_utilization_status"), smic_util
        )

        proxy_value, proxy_method, proxy_status = _build_proxy_value(
            tsmc_util,
            smic_util,
            weights,
            tsmc_shipment=tsmc_shipments,
            smic_shipment=smic_shipments,
        )
        common_source_url = _source_value(raw_row.get("source_url"))
        tsmc_source_url = _source_value(raw_row.get("tsmc_source_url"))
        smic_source_url = _source_value(raw_row.get("smic_source_url"))
        if not common_source_url:
            common_source_url = ";".join(
                value for value in (tsmc_source_url, smic_source_url) if value
            )

        rows.append(
            {
                "report_quarter": report_quarter,
                "trade_date": trade_date,
                "tsmc_utilization_pct": tsmc_util,
                "tsmc_wafer_shipments_12in_kpcs": tsmc_shipments,
                "tsmc_capacity_12in_kpcs": tsmc_capacity,
                "tsmc_utilization_status": tsmc_status,
                "smic_utilization_pct": smic_util,
                "smic_monthly_capacity_8inch_kw": smic_capacity,
                "smic_wafer_shipment_kw": smic_shipments,
                "smic_utilization_status": smic_status,
                "source": _source_value(raw_row.get("source")) or "TSMC_IR/SMIC_IR",
                "source_url": common_source_url or "",
                "release_date": _coerce_date(raw_row.get("release_date")),
                "data_status": _source_value(raw_row.get("data_status")) or "actual",
                "collected_at": _source_value(raw_row.get("collected_at")) or now_iso,
                "tsmc_source_url": tsmc_source_url or "",
                "tsmc_release_date": _coerce_date(raw_row.get("tsmc_release_date")),
                "smic_source_url": smic_source_url or "",
                "smic_release_date": _coerce_date(raw_row.get("smic_release_date")),
                "foundry_proxy_utilization_pct": proxy_value,
                "foundry_weighted_utilization_pct": proxy_value,
                "proxy_method": proxy_method,
                "proxy_status": proxy_status,
                "utilization_regime": determine_foundry_utilization_regime(proxy_value),
            }
        )

    if not rows:
        return pl.DataFrame(schema=FOUNDRY_CURATED_SCHEMA)
    return (
        pl.DataFrame(rows, schema=FOUNDRY_CURATED_SCHEMA)
        .unique(subset=["report_quarter"], keep="last")
        .sort("trade_date")
    )


def _string_expr_from_available(
    df: pl.DataFrame,
    column: str,
    suffix: str = "",
) -> pl.Expr:
    if column not in df.columns:
        return pl.lit(None, dtype=pl.String)
    expression = pl.col(column).cast(pl.String)
    return expression if not suffix else expression + pl.lit(suffix)


def _numeric_expr_from_available(df: pl.DataFrame, column: str) -> pl.Expr:
    if column not in df.columns:
        return pl.lit(None, dtype=pl.Float64)
    return (
        pl.col(column)
        .cast(pl.String)
        .str.replace_all(r"[^\d.-]", "")
        .cast(pl.Float64, strict=False)
    )


def _normalise_report_quarter(value: object) -> str | None:
    if value is None:
        return None
    match = re.fullmatch(r"\s*(20\d{2})\s*[- ]?Q\s*([1-4])\s*", str(value), re.IGNORECASE)
    return f"{match.group(1)}Q{match.group(2)}" if match else None


def _quarter_end(quarter: str) -> date:
    year = int(quarter[:4])
    month = int(quarter[-1]) * 3
    return date(year, month, 31 if month in (3, 12) else 30)


def _coerce_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _source_value(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_percent(value: object, raw_value: object) -> float | None:
    candidate = _source_value(raw_value) or value
    number = _first_number(candidate)
    if number is None:
        return None
    return number if math.isfinite(number) else None


def _coerce_wafer_k(value: object, raw_value: object) -> float | None:
    candidate = _source_value(raw_value)
    if candidate:
        number = _first_number(candidate)
        if number is None or not math.isfinite(number):
            return None
        lower = candidate.lower()
        if "million" in lower or "百万" in lower:
            return number * 1000.0
        if (
            "thousand" in lower
            or "千" in lower
            or re.search(r"\bk(?:pcs?|w)?\b", lower)
            or "kpcs" in lower
        ):
            return number
        return number / 1000.0
    number = _first_number(value)
    return number if number is not None and math.isfinite(number) else None


def _first_number(value: object) -> float | None:
    if value is None:
        return None
    match = re.search(r"[-+]?(?:\d[\d,]*(?:\.\d*)?|\.\d+)", str(value))
    if match is None:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _normalise_utilization_status(value: object, utilization: float | None) -> str:
    status = (_source_value(value) or "").lower()
    if status in {"reported", "derived", "unavailable", "legacy_baseline"}:
        if status == "unavailable" and utilization is not None:
            return "reported"
        return status
    return "reported" if utilization is not None else "unavailable"


def _normalise_proxy_weights(weights: dict[str, float] | None) -> dict[str, float]:
    if not weights:
        return {"tsmc": 0.5, "smic": 0.5}
    tsmc = float(weights.get("tsmc", 0.0))
    smic = float(weights.get("smic", 0.0))
    total = tsmc + smic
    if not math.isfinite(total) or total <= 0 or tsmc < 0 or smic < 0:
        raise ValueError("Foundry 代理权重必须为非负有限数，且总和大于 0")
    return {"tsmc": tsmc / total, "smic": smic / total}


_TSMC_12INCH_AREA_RATIO = 2.25  # 12 寸晶圆面积 / 8 寸晶圆面积 = (150/100)^2


def _build_proxy_value(
    tsmc_util: float | None,
    smic_util: float | None,
    weights: dict[str, float],
    *,
    tsmc_shipment: float | None = None,
    smic_shipment: float | None = None,
) -> tuple[float | None, str, str]:
    """计算两家公司的代表性产能利用率代理值。

    优先按晶圆出货面积体量加权（TSMC 12 寸、SMIC 8 寸，面积比 2.25:1），去体量
    通胀；出货量缺失时回退等权/配置权重。TSMC 侧利用率官方不再公布数字，缺失时由
    :mod:`stock_data.fetcher.industry.semiconductor.baseline` 的历史基线补齐并标注
    ``legacy_baseline`` 状态（基线唯一信任源是
    ``config/industry/semiconductor/tsmc_utilization_baseline.yaml``）。
    """
    if tsmc_util is None and smic_util is None:
        return None, "none", "unavailable"
    if tsmc_util is None or smic_util is None:
        return None, "none", "partial"
    if (
        tsmc_shipment is not None
        and smic_shipment is not None
        and tsmc_shipment > 0
        and smic_shipment > 0
    ):
        tsmc_weight = tsmc_shipment * _TSMC_12INCH_AREA_RATIO
        smic_weight = smic_shipment
        value = round(
            (tsmc_util * tsmc_weight + smic_util * smic_weight) / (tsmc_weight + smic_weight),
            2,
        )
        return value, "shipment_weighted_mean", "proxy"
    method = (
        "equal_company_mean"
        if weights == {"tsmc": 0.5, "smic": 0.5}
        else "configured_company_weighted_mean"
    )
    value = round(tsmc_util * weights["tsmc"] + smic_util * weights["smic"], 2)
    return value, method, "proxy"
