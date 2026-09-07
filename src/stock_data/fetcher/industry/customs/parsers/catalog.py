"""UN Comtrade 海关税号目录字典与解析转换工具。"""

from __future__ import annotations

import csv
import logging
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    parse_month_string,
)
from stock_data.fetcher.industry.customs.models import CustomsTradeRecord

logger = logging.getLogger(__name__)

HS_CATALOG_HIERARCHY_COLUMNS = ("hs_level", "hs_parent_code")


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if not text or text.lower() in {"none", "nan", "null"}:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _normalize_hs_code(value: Any) -> str:
    """归一化 Comtrade/GACC 返回的 HS 编码，保留六位历史前缀。"""
    return str(value or "").strip().replace(".", "").replace(" ", "")


def normalize_hs_catalog_row(row: dict[str, Any]) -> dict[str, str] | None:
    """规范统一 HS 主表行并补全/校验显式层级字段。"""
    catalog_row = {key: str(value or "").strip() for key, value in row.items() if key}
    hs_code = _normalize_hs_code(catalog_row.get("hs_code"))
    if not hs_code:
        return None
    if not hs_code.isdigit() or len(hs_code) not in {6, 8}:
        raise ValueError(f"HS 主表编码必须是 6 位或 8 位数字: {hs_code!r}")

    expected_level = str(len(hs_code))
    hs_level = catalog_row.get("hs_level") or expected_level
    if hs_level != expected_level:
        raise ValueError(f"HS 主表层级与编码长度不一致: hs_code={hs_code}, hs_level={hs_level}")

    expected_parent = hs_code[:6]
    hs_parent_code = catalog_row.get("hs_parent_code") or expected_parent
    if hs_parent_code != expected_parent:
        raise ValueError(f"HS 主表父码不一致: hs_code={hs_code}, hs_parent_code={hs_parent_code}")

    catalog_row["hs_code"] = hs_code
    catalog_row["hs_level"] = hs_level
    catalog_row["hs_parent_code"] = hs_parent_code
    return catalog_row


def load_hs_catalog_rows(catalog_path: Path | str) -> list[dict[str, str]]:
    """读取统一 HS 主表，兼容旧文件并规范为带层级信息的行。"""
    p = Path(catalog_path)
    if not p.exists():
        logger.warning("未找到海关税目对照字典: %s", p)
        return []

    rows: list[dict[str, str]] = []
    by_code: dict[str, dict[str, str]] = {}
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        for raw_row in csv.DictReader(f):
            catalog_row = normalize_hs_catalog_row(raw_row)
            if catalog_row is None:
                continue
            code = catalog_row["hs_code"]
            previous = by_code.get(code)
            if previous is not None and previous != catalog_row:
                raise ValueError(f"HS 主表存在冲突重复编码: {code}")
            if previous is None:
                by_code[code] = catalog_row
                rows.append(catalog_row)
    return rows


def _normalize_trade_direction(value: Any, default: str = "export") -> str:
    """把 CSV/Comtrade 方向标记统一为 import/export。"""
    normalized = str(value or "").strip().lower()
    if normalized in {"m", "import", "imports", "inbound", "进口"}:
        return "import"
    if normalized in {"x", "export", "exports", "outbound", "出口"}:
        return "export"
    return default


def _catalog_info_for_code(
    hs_code: str,
    catalog_map: dict[str, dict[str, str]],
) -> dict[str, str]:
    """按完整税号或六位前缀解析税号目录映射。"""
    normalized = _normalize_hs_code(hs_code)
    prefix = normalized[:6]
    return catalog_map.get(normalized) or catalog_map.get(prefix, {})


def _catalog_info_for_product_key(
    product_key: str,
    catalog_map: dict[str, dict[str, str]],
) -> dict[str, str]:
    """按 GACC 专用目录给出的产品键解析统一行业映射。"""
    for info in catalog_map.values():
        if info.get("product_key") == product_key:
            return info
    return {}


def load_hs_catalog(catalog_path: Path | str) -> dict[str, dict[str, str]]:
    """加载 HS 主表，按完整码与显式六位父码建立索引。"""
    rows = load_hs_catalog_rows(catalog_path)
    cat_map = {row["hs_code"]: row for row in rows}
    parent_rows: dict[str, dict[str, str]] = {}
    children_by_parent: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        parent = row["hs_parent_code"]
        if row["hs_level"] == "6":
            parent_rows[parent] = row
        else:
            children_by_parent[parent].append(row)

    for parent, children in children_by_parent.items():
        if parent in parent_rows:
            continue
        product_keys = {row.get("product_key", "") for row in children}
        if len(product_keys) > 1:
            raise ValueError(
                f"HS6 父码 {parent} 下存在多个 product_key，必须维护一行明确的 6 位父级映射: "
                f"{sorted(product_keys)}"
            )
        parent_rows[parent] = sorted(children, key=lambda row: row["hs_code"])[0]

    cat_map.update(parent_rows)
    return cat_map


def get_hs6_query_list(catalog_path: Path | str) -> list[str]:
    """从统一主表显式父码提取去重后的 Comtrade HS6 查询列表。"""
    return sorted({row["hs_parent_code"] for row in load_hs_catalog_rows(catalog_path)})


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

        cmd_code = _normalize_hs_code(item.get("cmdCode"))
        catalog_info = _catalog_info_for_code(cmd_code, catalog_map)

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
        export_val = _parse_float(item.get("primaryValue"))
        if export_val is None:
            continue
        qty = _parse_float(item.get("qty"))
        if qty is None:
            qty = _parse_float(item.get("netWgt"))
        unit = item.get("qtyUnitAbbr") or catalog_info.get("quantity_unit", "")

        release_date = (
            date.fromisoformat(str(item["release_date"]).strip())
            if item.get("release_date")
            else None
        )

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
                target_l3_codes=catalog_info.get("target_l3_codes", ""),
                target_l3_names=catalog_info.get("target_l3_names", ""),
                source="UN_Comtrade",
                source_url="https://comtradeplus.un.org/",
                release_date=release_date,
                data_status="actual",
                collected_at=now_iso,
                trade_value_currency="USD",
            )
        )

    records.sort(key=lambda r: (r.product_key, r.hs_code, r.trade_date))
    return records


def parse_raw_csv_rows(
    rows: list[dict[str, str]],
    catalog_map: dict[str, dict[str, str]],
    default_trade_direction: str = "export",
) -> list[CustomsTradeRecord]:
    """从 RAW CSV 行字典列表中加载并标准化为 CustomsTradeRecord (自适应支持 GACC 中文与标准英文)。"""
    records: list[CustomsTradeRecord] = []
    now_iso = now_utc_iso()
    for row in rows:
        # 提取商品编码 (支持 '商品编码' 或 'hs_code')
        raw_code = (row.get("商品编码") or row.get("hs_code") or "").strip()
        if not raw_code:
            continue
        hs_code = (
            raw_code
            if len(raw_code) in {6, 8} and raw_code.isdigit()
            else raw_code.zfill(8)
            if len(raw_code) < 8 and raw_code.isdigit()
            else raw_code
        )

        catalog_info = _catalog_info_for_code(hs_code, catalog_map)

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
        val_raw = row.get("美元") or row.get("export_value_usd") or row.get("金额")
        export_val = _parse_float(val_raw)
        if export_val is None:
            continue

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

        release_date = (
            date.fromisoformat(str(row["release_date"]).strip())
            if row.get("release_date")
            else None
        )

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
                trade_direction=_normalize_trade_direction(
                    row.get("trade_direction") or row.get("flowCode"),
                    default_trade_direction,
                ),
                export_value_usd=export_val,
                export_volume=export_vol,
                quantity_unit=unit,
                export_asp_usd=float(row["export_asp_usd"]) if row.get("export_asp_usd") else None,
                target_l1_code=catalog_info.get("target_l1_code", row.get("target_l1_code", "")),
                target_l1_name=catalog_info.get("target_l1_name", row.get("target_l1_name", "")),
                target_l2_codes=catalog_info.get("target_l2_codes", row.get("target_l2_codes", "")),
                target_l2_names=catalog_info.get("target_l2_names", row.get("target_l2_names", "")),
                target_l3_codes=catalog_info.get("target_l3_codes", row.get("target_l3_codes", "")),
                target_l3_names=catalog_info.get("target_l3_names", row.get("target_l3_names", "")),
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
                trade_value_currency=row.get("trade_value_currency", "USD") or "USD",
                raw_content_sha256=row.get("raw_content_sha256", "") or "",
                raw_snapshot_path=row.get("raw_snapshot_path", "") or "",
            )
        )
    return records
