"""stats.customs.gov.cn CSV 的纯解析与目录映射。"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.common import get_month_end_date, now_utc_iso
from stock_data.fetcher.industry.customs.models import (
    GACC_BASE_URL,
    CustomsTradeRecord,
    GaccQueryParams,
    GaccSnapshotManifest,
)
from stock_data.fetcher.industry.customs.parsers.catalog import (
    _catalog_info_for_code,
    _catalog_info_for_product_key,
)
from stock_data.fetcher.industry.customs.parsers.gacc_catalog import is_queryable_gacc_code
from stock_data.fetcher.industry.customs.release_calendar import release_date_for


def _normalize_header(value: str) -> str:
    """归一化中英文 CSV 表头。"""
    return re.sub(r"[\s\ufeff]+", "", str(value).strip().lower())


def _parse_number(value: Any) -> float | None:
    """解析带千分位、破折号或空值的数字。"""
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("，", "")
    if not text or text.lower() in {"-", "—", "–", "null", "none", "nan"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """读取 GACC CSV，兼容 UTF-8、GB18030 以及表头前说明行。"""
    raw = path.read_bytes()
    text = ""
    for encoding in ("utf-8-sig", "gb18030", "gbk", "utf-8"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        text = raw.decode("utf-8", errors="replace")

    rows = list(csv.reader(text.splitlines()))
    if not rows:
        return [], []

    header_index = next(
        (
            index
            for index, row in enumerate(rows)
            if any(
                _normalize_header(cell) in {"商品编码", "商品代码", "hscode", "codets"}
                for cell in row
            )
        ),
        0,
    )
    headers = [str(value).strip() for value in rows[header_index]]
    data_rows: list[dict[str, str]] = []
    for row in rows[header_index + 1 :]:
        if not any(str(cell).strip() for cell in row):
            continue
        padded = list(row) + [""] * max(0, len(headers) - len(row))
        data_rows.append(dict(zip(headers, padded[: len(headers)], strict=False)))
    return headers, data_rows


def _first_value(
    headers: list[str], row: dict[str, str], aliases: set[str], contains: tuple[str, ...] = ()
) -> str:
    """按归一化表头从一行中提取首个非空字段。"""
    normalized_headers = [(header, _normalize_header(header)) for header in headers]
    for header, normalized in normalized_headers:
        if normalized in aliases and str(row.get(header, "")).strip():
            return str(row[header]).strip()
    for header, normalized in normalized_headers:
        if any(marker in normalized for marker in contains) and str(row.get(header, "")).strip():
            return str(row[header]).strip()
    return ""


def _parse_month(value: str, params: GaccQueryParams) -> tuple[int, int] | None:
    """解析 GACC 的数据年月字段，缺失时只允许单月查询回填。"""
    text = str(value or "").strip().replace("年", "-").replace("月", "")
    digits = re.sub(r"[^0-9]", "", text)
    if len(digits) >= 6:
        year, month = int(digits[:4]), int(digits[4:6])
        if 1 <= month <= 12:
            return year, month
    if params.month_start == params.month_end:
        return params.year, params.month_start
    return None


@dataclass
class _GaccAggregate:
    """同一商品、月份、方向的 GACC 详细行聚合状态。"""

    value: float = 0.0
    quantity: float = 0.0
    quantity_complete: bool = True
    quantity_unit: str = ""
    hs_name: str = ""
    catalog_info: dict[str, str] | None = None


def parse_gacc_csv(
    path: Path | str,
    *,
    params: GaccQueryParams,
    catalog_map: dict[str, dict[str, str]],
    gacc_code_map: dict[str, dict[str, str]] | None = None,
    manifest: GaccSnapshotManifest | None = None,
    source_url: str = GACC_BASE_URL,
) -> list[CustomsTradeRecord]:
    """解析并聚合 GACC CSV。

    码表命中的 8 位子目按 product_key 归属；码表未命中时回退主表（8 位精确 →
    6 位前缀兜底），支持海关平台"商品编码留空"的全量商品导出；主表完全无
    映射的码丢弃。
    """
    if params.flow_type == "both":
        raise ValueError("GACC 进出口合并查询无法为单个 CSV 确定 trade_direction")

    csv_path = Path(path)
    headers, rows = _read_csv(csv_path)
    if not headers or not rows:
        return []

    now_iso = manifest.downloaded_at if manifest and manifest.downloaded_at else now_utc_iso()
    raw_hash = manifest.raw_content_sha256 if manifest else ""
    raw_path = manifest.raw_snapshot_path if manifest else str(csv_path)
    aggregates: dict[tuple[str, str, str], _GaccAggregate] = defaultdict(_GaccAggregate)

    for row in rows:
        raw_code = _first_value(
            headers,
            row,
            {"商品编码", "商品代码", "hscode", "codets", "hs编码"},
        )
        hs_code = re.sub(r"[^0-9]", "", raw_code)
        if not hs_code:
            continue
        if gacc_code_map is None:
            catalog_info = _catalog_info_for_code(hs_code, catalog_map)
        else:
            gacc_info = gacc_code_map.get(hs_code)
            if gacc_info is not None and is_queryable_gacc_code(gacc_info):
                catalog_info = _catalog_info_for_product_key(
                    gacc_info.get("product_key", ""),
                    catalog_map,
                )
            else:
                # 全量导出模式：码表未命中时回退主表（8 位精确 → 6 位前缀兜底）。
                # 支持海关平台"商品编码留空"的全量商品导出（未登记子目按 6 位父级
                # 归属产品）；主表完全无映射的码仍丢弃。
                catalog_info = _catalog_info_for_code(hs_code, catalog_map)
        if not catalog_info:
            continue

        month_raw = _first_value(
            headers,
            row,
            {"数据年月", "统计年月", "报告期", "reportmonth", "period", "month"},
            contains=("年月", "reportmonth"),
        )
        parsed_month = _parse_month(month_raw, params)
        if parsed_month is None:
            continue
        year, month = parsed_month
        report_month = f"{year:04d}-{month:02d}"

        value_aliases = (
            {"美元", "美元金额", "金额美元", "tradevalueus$", "valueusd", "exportvalueusd"}
            if params.currency == "USD"
            else {"人民币", "人民币元", "金额人民币", "valuecny", "exportvaluecny"}
        )
        value_raw = _first_value(
            headers,
            row,
            value_aliases,
            contains=("美元",) if params.currency == "USD" else ("人民币",),
        )
        value = _parse_number(value_raw)
        if value is None:
            continue

        quantity_raw = _first_value(
            headers,
            row,
            {"第一数量", "数量1", "quantity", "exportvolume", "qty", "qty1"},
            contains=("第一数量",),
        )
        quantity = _parse_number(quantity_raw)
        unit = _first_value(
            headers,
            row,
            {"第一计量单位", "计量单位1", "unit", "quantityunit", "unit1"},
            contains=("第一计量单位",),
        )
        hs_name = _first_value(headers, row, {"商品名称", "hsname", "hscode名称"})
        key = (hs_code, report_month, params.flow_type)
        aggregate = aggregates[key]
        aggregate.value += value
        if quantity is None:
            aggregate.quantity_complete = False
        else:
            aggregate.quantity += quantity
        if aggregate.quantity_unit and unit and aggregate.quantity_unit != unit:
            aggregate.quantity_complete = False
        if unit:
            aggregate.quantity_unit = aggregate.quantity_unit or unit
        aggregate.hs_name = aggregate.hs_name or hs_name
        aggregate.catalog_info = catalog_info

    records: list[CustomsTradeRecord] = []
    for (hs_code, report_month, trade_direction), aggregate in sorted(aggregates.items()):
        info = aggregate.catalog_info or {}
        year, month = (int(report_month[:4]), int(report_month[5:7]))
        records.append(
            CustomsTradeRecord(
                category_key=info.get("category_key", "unknown"),
                category_name=info.get("category_name", "未知"),
                product_key=info.get("product_key", hs_code),
                product_name=info.get("product_name", hs_code),
                hs_code=hs_code,
                hs_name=aggregate.hs_name or info.get("hs_name", ""),
                report_month=report_month,
                trade_date=get_month_end_date(year, month),
                trade_direction=trade_direction,
                export_value_usd=aggregate.value,
                export_volume=aggregate.quantity if aggregate.quantity_complete else None,
                quantity_unit=aggregate.quantity_unit or info.get("quantity_unit", ""),
                target_l1_code=info.get("target_l1_code", ""),
                target_l1_name=info.get("target_l1_name", ""),
                target_l2_codes=info.get("target_l2_codes", ""),
                target_l2_names=info.get("target_l2_names", ""),
                target_l3_codes=info.get("target_l3_codes", ""),
                target_l3_names=info.get("target_l3_names", ""),
                source="GACC",
                source_url=source_url,
                release_date=release_date_for(report_month),
                data_status="actual",
                collected_at=now_iso,
                raw_content_sha256=raw_hash,
                raw_snapshot_path=raw_path,
                trade_value_currency=params.currency,
            )
        )
    return records


__all__ = ["parse_gacc_csv"]
