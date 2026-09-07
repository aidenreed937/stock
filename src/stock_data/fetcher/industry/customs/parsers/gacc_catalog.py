"""GACC 实际末级子税目目录与查询清单工具。"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from stock_data.fetcher.industry.customs.parsers.catalog import load_hs_catalog_rows
from stock_data.fetcher.industry.customs.paths import (
    DEFAULT_GACC_CATALOG_PATH,
    DEFAULT_GACC_CODES_CSV_PATH,
    DEFAULT_GACC_CODES_PATH,
    DEFAULT_HS_CATALOG_PATH,
)

GACC_DERIVED_EVIDENCE = "auto-derived from hs_codes_catalog.csv"
HISTORY_MARKERS = ("HS2017", "历史", "历史/代理", "HS 2017")
GACC_CATALOG_REQUIRED_COLUMNS = (
    "product_key",
    "gacc_code",
    "hs_version",
    "code_role",
    "active",
)
GACC_CODES_CSV_COLUMNS = (
    "gacc_code",
    "product_key",
    "product_name",
    "hs_version",
    "code_role",
    "active",
    "valid_from",
    "valid_to",
    "replacement_code",
    "source_evidence",
    "notes",
    "hs_parent_code",
)


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

    主表的 ``gacc_active=1`` 可覆盖历史码过滤，但仍不会覆盖已有末级子目
    对 ``00`` 补齐父级码的排除规则。
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
        is_history = any(marker in row.get("description", "") for marker in HISTORY_MARKERS)
        if is_history and gacc_flag not in {"1", "true", "yes", "y"}:
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


def write_gacc_code_catalog(
    main_catalog_path: Path | str = DEFAULT_HS_CATALOG_PATH,
    output_path: Path | str = DEFAULT_GACC_CATALOG_PATH,
) -> list[str]:
    """将统一 HS 主表派生出的 GACC 目录全量写出。"""
    catalog = derive_gacc_code_catalog(main_catalog_path)
    if not catalog:
        raise ValueError(f"HS 编码主表没有可派生的 GACC 末级子目: {main_catalog_path}")

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=GACC_CODES_CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(catalog.values())
    return list(catalog)


def load_gacc_code_catalog(
    catalog_path: Path | str = DEFAULT_GACC_CATALOG_PATH,
) -> dict[str, dict[str, str]]:
    """加载 GACC 专用编码目录，按完整八位编码建立索引。"""
    path = Path(catalog_path)
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8-sig", newline="") as file_obj:
        reader = csv.DictReader(file_obj)
        fieldnames = set(reader.fieldnames or ())
        missing = set(GACC_CATALOG_REQUIRED_COLUMNS) - fieldnames
        if missing:
            raise ValueError(f"GACC 编码目录缺少字段: {sorted(missing)}")

        catalog: dict[str, dict[str, str]] = {}
        for raw_row in reader:
            row = {key: str(value or "").strip() for key, value in raw_row.items()}
            code = _normalize_gacc_code(row.get("gacc_code"))
            row["gacc_code"] = code
            previous = catalog.get(code)
            if previous is not None and previous != row:
                raise ValueError(f"GACC 编码目录存在冲突重复编码: {code}")
            catalog[code] = row
    return catalog


def get_gacc_hs_codes(
    catalog_path: Path | str = DEFAULT_GACC_CATALOG_PATH,
) -> list[str]:
    """从 GACC 专用目录提取启用的末级八位查询码。"""
    catalog = load_gacc_code_catalog(catalog_path)
    return sorted(code for code, row in catalog.items() if is_queryable_gacc_code(row))


def write_gacc_hs_codes(
    catalog_path: Path | str = DEFAULT_GACC_CATALOG_PATH,
    output_path: Path | str = DEFAULT_GACC_CODES_PATH,
) -> list[str]:
    """根据 GACC 专用目录生成单行逗号分隔查询清单。"""
    codes = get_gacc_hs_codes(catalog_path)
    if not codes:
        raise ValueError(f"GACC 编码目录没有可查询末级子目: {catalog_path}")
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"=== GACC 可查询末级子税号 (单行逗号分隔，共 {len(codes)} 个) ===\n\n{','.join(codes)}\n",
        encoding="utf-8",
    )
    return codes


def write_gacc_hs_codes_csv(
    catalog_path: Path | str = DEFAULT_GACC_CATALOG_PATH,
    output_path: Path | str = DEFAULT_GACC_CODES_CSV_PATH,
) -> list[str]:
    """根据 GACC 专用目录生成自动采集使用的 CSV 白名单。"""
    catalog = load_gacc_code_catalog(catalog_path)
    rows = [catalog[code] for code in sorted(catalog) if is_queryable_gacc_code(catalog[code])]
    if not rows:
        raise ValueError(f"GACC 编码目录没有可查询末级子目: {catalog_path}")

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=GACC_CODES_CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(
            {column: row.get(column, "") for column in GACC_CODES_CSV_COLUMNS} for row in rows
        )
    return [row["gacc_code"] for row in rows]


__all__ = [
    "DEFAULT_GACC_CATALOG_PATH",
    "DEFAULT_GACC_CODES_CSV_PATH",
    "DEFAULT_GACC_CODES_PATH",
    "DEFAULT_HS_CATALOG_PATH",
    "GACC_CATALOG_REQUIRED_COLUMNS",
    "GACC_CODES_CSV_COLUMNS",
    "derive_gacc_code_catalog",
    "get_gacc_hs_codes",
    "is_queryable_gacc_code",
    "load_gacc_code_catalog",
    "write_gacc_code_catalog",
    "write_gacc_hs_codes",
    "write_gacc_hs_codes_csv",
]
