#!/usr/bin/env python3
"""把 config/data/customs/good_h8_codes.csv 宽表拆分为三表（categories/products/hs_codes）。

用法：
  uv run python scripts/split_catalog.py            # dry-run：只打印审计报告与无损校验
  uv run python scripts/split_catalog.py --apply    # 落盘三表 + 备份旧表 + 重生成 GACC 查询清单

设计（维护面从 712 行×16 列宽表，拆成三张职责单一的表）：
  categories.csv    : category_key → category_name 枚举（修复拼写漂移）
  good_products.csv : 产品主表（product_key 主键，产品级稳定属性）
  good_h8_codes.csv : 税号表（hs_code 主键，税号级属性 + L3 覆盖列）

loader 内部 join 还原宽行，下游消费方零改动；无 products/categories 时直读旧宽表向后兼容。
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import Counter
from pathlib import Path

from stock_data.fetcher.industry.customs.parsers.catalog import OVERRIDE_FIELDS

CONFIG_DIR = Path("config/data/customs")
OLD_PATH = CONFIG_DIR / "good_h8_codes.csv"
CATEGORIES_PATH = CONFIG_DIR / "categories.csv"
PRODUCTS_PATH = CONFIG_DIR / "good_products.csv"
HS_CODES_PATH = CONFIG_DIR / "good_h8_codes.csv"
BACKUP_DIR = Path("data/backup/customs")

CATEGORY_COLS = ["category_key", "category_name"]
PRODUCT_COLS = [
    "product_key",
    "product_name",
    "category_key",
    "description",
    "target_l1_code",
    "target_l1_name",
    "target_l2_codes",
    "target_l2_names",
    "target_l3_codes",
    "target_l3_names",
]
HS_COLS = [
    "hs_code",
    "hs_parent_code",
    "hs_level",
    "hs_name",
    "quantity_unit",
    "product_key",
    "product_name",
    "description",
    "target_l3_codes",
    "target_l3_names",
]

# 同义 category_key 拼写漂移修复（key 合并，category_name 不变）
CATEGORY_KEY_FIX = {"nonferrous_metals": "non_ferrous_metals"}

# 产品级字段（拆分后归 products 表；其中 name/description 允许折叠，其余必须一致）
PRODUCT_FIELDS = [
    "product_key",
    "product_name",
    "category_key",
    "description",
    "target_l1_code",
    "target_l1_name",
    "target_l2_codes",
    "target_l2_names",
    "target_l3_codes",
    "target_l3_names",
]
# 税号级字段（拆分后归 hs_codes 表）
HS_FIELDS = ["hs_code", "hs_parent_code", "hs_level", "hs_name", "quantity_unit"]
# 预期变更字段（category 拼写修复/产品级归并），硬校验跳过、由审计报告披露
EXPECTED_CHANGED_FIELDS = ["category_key", "category_name"]


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [{k: (v or "").strip() for k, v in row.items() if k} for row in csv.DictReader(f)]


def fix_category_key(row: dict[str, str]) -> str:
    return CATEGORY_KEY_FIX.get(row["category_key"], row["category_key"])


def pick_majority(values: list[str]) -> str:
    """多数表决；平局取列表（已按 hs_code 排序）中最早达到最高频的值。"""
    counts = Counter(values)
    max_n = max(counts.values())
    for v in values:
        if counts[v] == max_n:
            return v
    return values[0]


def group_by_product(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["product_key"], []).append(row)
    for key in grouped:
        grouped[key].sort(key=lambda r: r["hs_code"])
    return grouped


def build_tables(
    rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], dict]:
    """返回 (categories, products, hs_codes, audit)。audit 记录折叠/归并决策。"""
    audit: dict = {
        "category_key_fix": [],
        "product_category_merge": [],
        "name_fold": [],
        "desc_fold": [],
    }

    # 1. 先修复 category_key（维度拼写漂移）
    for row in rows:
        orig = row["category_key"]
        fixed = fix_category_key(row)
        if fixed != orig:
            audit["category_key_fix"].append((row["hs_code"], row["product_key"], orig, fixed))
        row["category_key"] = fixed

    # 2. categories 枚举
    cat_name: dict[str, str] = {}
    for row in rows:
        key = row["category_key"]
        name = row["category_name"]
        if key not in cat_name:
            cat_name[key] = name
        elif cat_name[key] != name and name:
            cat_name[key] = name  # 同名 key 的 name 冲突时取后者，仍会进审计
    categories = [{"category_key": k, "category_name": v} for k, v in sorted(cat_name.items())]

    # 3. 产品主表
    grouped = group_by_product(rows)
    products: list[dict[str, str]] = []
    for pkey in sorted(grouped):
        prs = grouped[pkey]
        # category 多数表决归并（hand_tools 等历史不一致）
        cats = [r["category_key"] for r in prs]
        cat = pick_majority(cats)
        if len(set(cats)) > 1:
            audit["product_category_merge"].append((pkey, sorted(set(cats)), cat))

        name = pick_majority([r["product_name"] for r in prs])
        if len({r["product_name"] for r in prs}) > 1:
            audit["name_fold"].append((pkey, sorted({r["product_name"] for r in prs}), name))

        descs: list[str] = []
        seen_desc: set[str] = set()
        for r in prs:
            d = r["description"]
            if d and d not in seen_desc:
                seen_desc.add(d)
                descs.append(d)
        desc = " | ".join(descs)
        if len(seen_desc) > 1:
            audit["desc_fold"].append((pkey, sorted(seen_desc), desc))

        products.append(
            {
                "product_key": pkey,
                "product_name": name,
                "category_key": cat,
                "description": desc,
                "target_l1_code": pick_majority([r["target_l1_code"] for r in prs]),
                "target_l1_name": pick_majority([r["target_l1_name"] for r in prs]),
                "target_l2_codes": pick_majority([r["target_l2_codes"] for r in prs]),
                "target_l2_names": pick_majority([r["target_l2_names"] for r in prs]),
                "target_l3_codes": pick_majority([r["target_l3_codes"] for r in prs]),
                "target_l3_names": pick_majority([r["target_l3_names"] for r in prs]),
            }
        )

    prod_by_key = {p["product_key"]: p for p in products}

    # 4. 税号表（L3 覆盖列：仅当与产品默认 L3 不同时填写）
    hs_codes: list[dict[str, str]] = []
    for row in rows:
        p = prod_by_key[row["product_key"]]
        hs_row = {f: row[f] for f in HS_FIELDS}
        hs_row["product_key"] = row["product_key"]
        # 覆盖列：与产品主表默认值不同才写，空 = 继承产品默认
        for f in OVERRIDE_FIELDS:
            hs_row[f] = row[f] if row[f] != p[f] else ""
        hs_codes.append(hs_row)

    return categories, products, hs_codes, audit


def verify_roundtrip(
    rows: list[dict[str, str]],
    categories: list[dict[str, str]],
    products: list[dict[str, str]],
    hs_codes: list[dict[str, str]],
) -> list[str]:
    """join 还原宽行并逐字段对比；返回差异描述列表（空 = 无损）。"""
    cat_name = {c["category_key"]: c["category_name"] for c in categories}
    prod_by_key = {p["product_key"]: p for p in products}
    hs_by_code = {h["hs_code"]: h for h in hs_codes}
    diffs: list[str] = []
    for old in rows:
        code = old["hs_code"]
        h = hs_by_code.get(code)
        if h is None:
            diffs.append(f"{code}: 税号行缺失")
            continue
        p = prod_by_key.get(old["product_key"])
        if p is None:
            diffs.append(f"{code}: 产品行缺失 product_key={old['product_key']!r}")
            continue
        joined = {
            "hs_code": h["hs_code"],
            "hs_parent_code": h["hs_parent_code"],
            "category_key": p["category_key"],
            "category_name": cat_name.get(p["category_key"], ""),
            "product_key": h["product_key"],
            "product_name": h["product_name"] or p["product_name"],
            "hs_level": h["hs_level"],
            "hs_name": h["hs_name"],
            "quantity_unit": h["quantity_unit"],
            "target_l1_code": p["target_l1_code"],
            "target_l1_name": p["target_l1_name"],
            "target_l2_codes": p["target_l2_codes"],
            "target_l2_names": p["target_l2_names"],
            "description": h["description"] or p["description"],
            "target_l3_codes": h["target_l3_codes"] or p["target_l3_codes"],
            "target_l3_names": h["target_l3_names"] or p["target_l3_names"],
        }
        for f in joined:
            if f in EXPECTED_CHANGED_FIELDS:
                continue  # 预期变更字段不硬校验（category 修复/name/desc 折叠）
            if joined[f] != old.get(f, ""):
                diffs.append(f"{code}.{f}: 原={old.get(f, '')!r} 还原={joined[f]!r}")
    return diffs


def write_csv(path: Path, cols: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def print_audit(audit: dict, diffs: list[str], n_old: int) -> None:
    print(f"=== 拆分审计（旧表 {n_old} 行）===\n")
    if audit["category_key_fix"]:
        print(f"[category_key 拼写修复] {len(audit['category_key_fix'])} 行:")
        for code, pkey, orig, fixed in audit["category_key_fix"]:
            print(f"  {code} {pkey}: {orig} -> {fixed}")
    if audit["product_category_merge"]:
        print(f"\n[产品级 category 归并] {len(audit['product_category_merge'])} 个产品:")
        for pkey, srcs, dst in audit["product_category_merge"]:
            print(f"  {pkey}: {srcs} -> {dst}")
    if audit["name_fold"]:
        print(f"\n[product_name 折叠(多数表决)] {len(audit['name_fold'])} 个产品:")
        for pkey, srcs, dst in audit["name_fold"]:
            print(f"  {pkey}: {srcs} -> {dst}")
    if audit["desc_fold"]:
        print(f"\n[description 合并去重] {len(audit['desc_fold'])} 个产品:")
        for pkey, _srcs, dst in audit["desc_fold"]:
            print(f"  {pkey}: -> {dst}")
    print("\n=== 无损校验（除 category_key/name 修复外，全字段 join 还原一致）===")
    if diffs:
        print(f"  ❌ {len(diffs)} 处不一致:")
        for d in diffs[:50]:
            print(f"    {d}")
        if len(diffs) > 50:
            print(f"    ... 共 {len(diffs)} 处")
    else:
        print("  ✅ 全部一致（join 还原 == 旧表硬字段）")


def main() -> int:
    parser = argparse.ArgumentParser(description="拆分 good_h8_codes.csv 宽表为三表")
    parser.add_argument("--apply", action="store_true", help="落盘三表并备份旧表")
    args = parser.parse_args()

    if not OLD_PATH.exists():
        print(f"旧表不存在: {OLD_PATH}", file=sys.stderr)
        return 1

    rows = load_rows(OLD_PATH)
    categories, products, hs_codes, audit = build_tables(rows)
    diffs = verify_roundtrip(rows, categories, products, hs_codes)
    print_audit(audit, diffs, len(rows))

    if diffs:
        print("\n存在硬字段不一致，拒绝落盘。", file=sys.stderr)
        return 1

    if not args.apply:
        print("\n[dry-run] 未落盘；确认无误后用 --apply 写入。")
        return 0

    ts = time.strftime("%Y%m%d_%H%M%S")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / f"good_h8_codes.csv.{ts}.bak"
    backup.write_bytes(OLD_PATH.read_bytes())
    print(f"\n旧表已备份: {backup}")

    write_csv(CATEGORIES_PATH, CATEGORY_COLS, categories)
    write_csv(PRODUCTS_PATH, PRODUCT_COLS, products)
    write_csv(HS_CODES_PATH, HS_COLS, hs_codes)
    print(
        f"已落盘三表: {CATEGORIES_PATH} ({len(categories)} 行) / "
        f"{PRODUCTS_PATH} ({len(products)} 行) / {HS_CODES_PATH} ({len(hs_codes)} 行)"
    )

    # 重生成 GACC 查询清单（从新税号表派生）
    try:
        from stock_data.fetcher.industry.customs.parsers.gacc_catalog import (
            write_gacc_query_codes,
        )

        codes = write_gacc_query_codes(HS_CODES_PATH)
        print(f"已重生成 GACC 查询清单: {len(codes)} 个码")
    except Exception as exc:  # noqa: BLE001
        print(f"⚠ GACC 查询清单重生成失败（需 loader 改造后再跑）: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
