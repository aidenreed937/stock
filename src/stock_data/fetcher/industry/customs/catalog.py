"""UN Comtrade 海关税号目录字典与解析转换工具。"""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    parse_month_string,
)
from stock_data.fetcher.industry.models import CustomsTradeRecord

logger = logging.getLogger(__name__)


def load_hs_catalog(catalog_path: Path | str) -> dict[str, dict[str, str]]:
    """加载本地 HS 编码对照字典，支持 8 位完整税号与 6 位前缀双向索引。"""
    p = Path(catalog_path)
    if not p.exists():
        logger.warning("未找到海关税目对照字典: %s", p)
        return {}

    cat_map: dict[str, dict[str, str]] = {}
    with p.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            hs8 = row["hs_code"].strip()
            cat_map[hs8] = row
            hs6 = hs8[:6]
            if hs6 not in cat_map:
                cat_map[hs6] = row
    return cat_map


def get_hs6_query_list(catalog_path: Path | str) -> list[str]:
    """从字典表中提取去重后的 6 位国际通用 HS 编码列表。"""
    p = Path(catalog_path)
    if not p.exists():
        return []
    codes: set[str] = set()
    with p.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            hs = row["hs_code"].strip()
            if hs:
                codes.add(hs[:6])
    return sorted(codes)


def parse_comtrade_items(
    items: list[dict[str, Any]],
    catalog_map: dict[str, dict[str, str]],
) -> list[CustomsTradeRecord]:
    """将 UN Comtrade API / JSON 返回的字典列表转换为标准 CustomsTradeRecord 列表。"""
    records: list[CustomsTradeRecord] = []
    now_iso = now_utc_iso()

    for item in items:
        flow_code = str(item.get("flowCode", "")).upper()
        if flow_code not in ("X", "M", ""):
            continue
        trade_dir = "export" if flow_code in ("X", "") else "import"

        cmd_code = str(item.get("cmdCode", "")).strip()
        catalog_info = catalog_map.get(cmd_code) or catalog_map.get(cmd_code[:6], {})

        period_str = str(item.get("period", "")).strip()
        if not period_str:
            continue

        if len(period_str) == 6 and period_str.isdigit():
            report_month = f"{period_str[:4]}-{period_str[4:]}"
            year = int(period_str[:4])
            month = int(period_str[4:])
        else:
            report_month = period_str
            year, month = parse_month_string(period_str)

        t_date = get_month_end_date(year, month)
        export_val = float(item.get("primaryValue", 0.0) or 0.0)
        qty = float(item.get("qty", 0.0)) if item.get("qty") is not None else None
        unit = item.get("qtyUnitAbbr") or catalog_info.get("quantity_unit", "")

        release_date: date | None = None
        if item.get("updated"):
            try:
                release_date = date.fromisoformat(str(item["updated"])[:10])
            except (ValueError, TypeError):
                release_date = None

        records.append(
            CustomsTradeRecord(
                category_key=catalog_info.get("category_key", "unknown"),
                category_name=catalog_info.get("category_name", "未知"),
                product_key=catalog_info.get("product_key", cmd_code),
                product_name=catalog_info.get("product_name", cmd_code),
                hs_code=cmd_code,
                hs_name=catalog_info.get("hs_name", item.get("cmdDesc", "")),
                report_month=report_month,
                trade_date=t_date,
                trade_direction=trade_dir,
                export_value_usd=export_val,
                export_volume=qty,
                quantity_unit=unit,
                target_l1_code=catalog_info.get("target_l1_code", ""),
                target_l1_name=catalog_info.get("target_l1_name", ""),
                target_l2_codes=catalog_info.get("target_l2_codes", ""),
                target_l2_names=catalog_info.get("target_l2_names", ""),
                source="UN_Comtrade",
                source_url="https://comtradeplus.un.org/",
                release_date=release_date,
                data_status="actual",
                collected_at=now_iso,
            )
        )

    records.sort(key=lambda r: (r.product_key, r.hs_code, r.trade_date))
    return records


def parse_raw_csv_rows(
    rows: list[dict[str, str]],
    catalog_map: dict[str, dict[str, str]],
) -> list[CustomsTradeRecord]:
    """从 RAW CSV 行字典列表中加载并标准化为 CustomsTradeRecord。"""
    records: list[CustomsTradeRecord] = []
    now_iso = now_utc_iso()
    for row in rows:
        hs_code = row["hs_code"].strip()
        catalog_info = catalog_map.get(hs_code) or catalog_map.get(hs_code[:6], {})
        month_str = row["report_month"].strip()
        year, month = parse_month_string(month_str)
        t_date = get_month_end_date(year, month)

        records.append(
            CustomsTradeRecord(
                category_key=catalog_info.get("category_key", row.get("category_key", "")),
                category_name=catalog_info.get("category_name", row.get("category_name", "")),
                product_key=catalog_info.get("product_key", row.get("product_key", hs_code)),
                product_name=catalog_info.get("product_name", row.get("product_name", hs_code)),
                hs_code=hs_code,
                hs_name=catalog_info.get("hs_name", row.get("hs_name", "")),
                report_month=month_str,
                trade_date=t_date,
                trade_direction=row.get("trade_direction", "export"),
                export_value_usd=float(row["export_value_usd"]),
                export_volume=float(row["export_volume"]) if row.get("export_volume") else None,
                quantity_unit=row.get("quantity_unit") or catalog_info.get("quantity_unit", ""),
                export_asp_usd=float(row["export_asp_usd"]) if row.get("export_asp_usd") else None,
                target_l1_code=catalog_info.get("target_l1_code", row.get("target_l1_code", "")),
                target_l1_name=catalog_info.get("target_l1_name", row.get("target_l1_name", "")),
                target_l2_codes=catalog_info.get("target_l2_codes", row.get("target_l2_codes", "")),
                target_l2_names=catalog_info.get("target_l2_names", row.get("target_l2_names", "")),
                export_value_3mma=float(row["export_value_3mma"])
                if row.get("export_value_3mma")
                else None,
                yoy_growth_3mma=float(row["yoy_growth_3mma"])
                if row.get("yoy_growth_3mma")
                else None,
                mom_growth_3mma=float(row["mom_growth_3mma"])
                if row.get("mom_growth_3mma")
                else None,
                source=row.get("source", "UN_Comtrade"),
                source_url=row.get("source_url", "https://comtradeplus.un.org/"),
                release_date=date.fromisoformat(row["release_date"])
                if row.get("release_date")
                else None,
                data_status=row.get("data_status", "actual"),
                collected_at=row.get("collected_at", now_iso),
            )
        )
    return records
