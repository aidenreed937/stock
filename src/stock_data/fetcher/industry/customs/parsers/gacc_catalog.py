"""GACC 实际末级子税目目录与查询清单工具。"""

from __future__ import annotations

import re
from pathlib import Path

from stock_data.fetcher.industry.customs.parsers.catalog import load_hs_catalog_rows
from stock_data.fetcher.industry.customs.paths import (
    DEFAULT_GACC_QUERY_CODES_PATH,
    DEFAULT_HS_CATALOG_PATH,
)

GACC_DERIVED_EVIDENCE = "auto-derived from good_h8_codes.csv"


def _normalize_gacc_code(value: object) -> str:
    """归一化并校验 GACC 八位商品编码。"""
    code = str(value or "").strip()
    if not re.fullmatch(r"\d{8}", code):
        raise ValueError(f"GACC 商品编码必须是 8 位数字: {value!r}")
    return code


def _is_active(value: object) -> bool:
    """解析目录中的启用标记。"""
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def is_queryable_gacc_code(row: dict[str, str]) -> bool:
    """判断一行是否为进入 GACC 查询清单的启用末级子目。"""
    return row.get("code_role", "leaf").strip().lower() == "leaf" and _is_active(
        row.get("active", "1")
    )


def _load_hs_catalog_rows(catalog_path: Path | str) -> list[dict[str, str]]:
    """加载统一 HS 主表，保留其原始字段供 GACC 目录派生。"""
    path = Path(catalog_path)
    if not path.exists():
        raise FileNotFoundError(f"HS 编码主表不存在: {path}")
    rows = load_hs_catalog_rows(path)
    if not rows:
        raise ValueError(f"HS 编码主表没有有效行: {path}")
    return rows


def derive_gacc_code_catalog(
    main_catalog_path: Path | str = DEFAULT_HS_CATALOG_PATH,
) -> dict[str, dict[str, str]]:
    """从统一 HS 主表派生 GACC 可查询末级子目目录。

    8 位码化主表默认将全部 8 位行（包括 description 标记的历史码）纳入查询；
    仅显式 ``gacc_active=0`` 等禁用标记会排除。已有末级子目对 ``00`` 补齐
    父级码的排除规则不变。
    """
    rows = _load_hs_catalog_rows(main_catalog_path)
    main_by_code: dict[str, dict[str, str]] = {}
    for row in rows:
        code = row.get("hs_code", "").strip()
        if row.get("hs_level") != "8":
            continue
        previous = main_by_code.get(code)
        if previous is not None and previous != row:
            raise ValueError(f"HS 编码主表存在冲突重复编码: {code}")
        main_by_code[code] = row

    sub_prefixes = {code[:6] for code in main_by_code if not code.endswith("00")}
    derived: dict[str, dict[str, str]] = {}
    for code in sorted(main_by_code):
        row = main_by_code[code]
        gacc_flag = row.get("gacc_active", "").strip().lower()
        if gacc_flag in {"0", "false", "no", "n"}:
            continue
        if code.endswith("00") and code[:6] in sub_prefixes:
            continue
        derived[code] = {
            "product_key": row["product_key"],
            "gacc_code": code,
            "product_name": row["product_name"],
            "hs_version": "GACC-2025",
            "code_role": "leaf",
            "active": "1",
            "valid_from": "",
            "valid_to": "",
            "replacement_code": "",
            "source_evidence": GACC_DERIVED_EVIDENCE,
            "hs_parent_code": row["hs_parent_code"],
            "notes": (
                "待海关 2025 查询验证（00 补齐写法）"
                if code.endswith("00")
                else "主表 8 位码（HS2022 口径）"
            ),
        }
    return derived


def write_gacc_query_codes(
    main_catalog_path: Path | str = DEFAULT_HS_CATALOG_PATH,
    output_path: Path | str = DEFAULT_GACC_QUERY_CODES_PATH,
) -> list[str]:
    """从统一 HS 主表派生 GACC 可查询 8 位码，写单行逗号分隔查询清单。"""
    derived = derive_gacc_code_catalog(main_catalog_path)
    codes = sorted(derived)
    if not codes:
        raise ValueError(f"HS 编码主表没有可派生的 GACC 末级子目: {main_catalog_path}")
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"=== GACC 可查询末级子税号 (单行逗号分隔，共 {len(codes)} 个) ===\n\n{','.join(codes)}\n",
        encoding="utf-8",
    )
    return codes


__all__ = [
    "DEFAULT_HS_CATALOG_PATH",
    "derive_gacc_code_catalog",
    "is_queryable_gacc_code",
    "write_gacc_query_codes",
]
