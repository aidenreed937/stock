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


def release_date_from_month(year: int, month: int) -> date:
    """海关月度数据统一发布日：次月 20 日（GACC 官方发布惯例，滞后约 20 天）。

    UN Comtrade 段沿用同一规则，保证历史段与最新段生效口径一致。
    """
    if month == 12:
        return date(year + 1, 1, 20)
    return date(year, month + 1, 20)


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

        release_date = release_date_from_month(year, month)

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
    """从 RAW CSV 行字典列表中加载并标准化为 CustomsTradeRecord (自适应支持 GACC 中文与标准英文)。"""
    records: list[CustomsTradeRecord] = []
    now_iso = now_utc_iso()
    for row in rows:
        # 提取商品编码 (支持 '商品编码' 或 'hs_code')
        raw_code = (row.get("商品编码") or row.get("hs_code") or "").strip()
        if not raw_code:
            continue
        hs_code = raw_code.zfill(8) if len(raw_code) <= 8 and raw_code.isdigit() else raw_code

        catalog_info = catalog_map.get(hs_code) or catalog_map.get(hs_code[:6], {})

        # 提取月份 (支持 '数据年月' 如 202501，或 'report_month' 如 2025-01)
        month_str = (row.get("数据年月") or row.get("report_month") or "").strip()
        if not month_str:
            continue
        if len(month_str) == 6 and month_str.isdigit():
            month_formatted = f"{month_str[:4]}-{month_str[4:]}"
            year = int(month_str[:4])
            month = int(month_str[4:])
        else:
            month_formatted = month_str
            year, month = parse_month_string(month_str)

        t_date = get_month_end_date(year, month)

        # 提取金额 (美元，支持千分位逗号)
        val_raw = row.get("美元") or row.get("export_value_usd") or row.get("金额") or "0"
        val_clean = str(val_raw).replace(",", "").strip()
        export_val = float(val_clean) if val_clean else 0.0

        # 提取数量 (第一数量，支持千分位逗号)
        vol_raw = row.get("第一数量") or row.get("export_volume") or row.get("数量")
        if vol_raw is not None and str(vol_raw).strip() not in ("", "None", "nan", "null"):
            vol_clean = str(vol_raw).replace(",", "").strip()
            export_vol: float | None = float(vol_clean) if vol_clean else None
        else:
            export_vol = None

        # 提取计量单位与商品名称
        unit = (
            row.get("第一计量单位")
            or row.get("quantity_unit")
            or catalog_info.get("quantity_unit", "")
        )
        hs_name = row.get("商品名称") or row.get("hs_name") or catalog_info.get("hs_name", "")

        # 判断数据来源 (若包含中文字段则判定为 GACC)
        is_gacc = "数据年月" in row or "商品编码" in row or "美元" in row
        default_source = "GACC" if is_gacc else "UN_Comtrade"
        default_source_url = (
            "http://stats.customs.gov.cn/" if is_gacc else "https://comtradeplus.un.org/"
        )

        source = row.get("source") or default_source
        source_url = row.get("source_url") or default_source_url

        release_date = release_date_from_month(year, month)

        records.append(
            CustomsTradeRecord(
                category_key=catalog_info.get("category_key", row.get("category_key", "")),
                category_name=catalog_info.get("category_name", row.get("category_name", "")),
                product_key=catalog_info.get("product_key", row.get("product_key", hs_code)),
                product_name=catalog_info.get("product_name", row.get("product_name", hs_code)),
                hs_code=hs_code,
                hs_name=hs_name,
                report_month=month_formatted,
                trade_date=t_date,
                trade_direction=row.get("trade_direction", "export"),
                export_value_usd=export_val,
                export_volume=export_vol,
                quantity_unit=unit,
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
                source=source,
                source_url=source_url,
                release_date=release_date,
                data_status=row.get("data_status", "actual"),
                collected_at=row.get("collected_at", now_iso),
            )
        )
    return records
