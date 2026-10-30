#!/usr/bin/env python3
"""校验 customs catalog 三表（categories/products/hs_codes）的引用完整性与一致性。

用法：
  uv run python scripts/check_catalog.py              # 基础校验（引用完整性 + 码格式）
  uv run python scripts/check_catalog.py --industry   # 追加 L1/L2/L3 维度黄金表校验
  uv run python scripts/check_catalog.py --pool       # 追加 108 产品回测池 ↔ catalog 校验
  uv run python scripts/check_catalog.py --gold       # 追加 黄金表 ↔ catalog 双向 diff 校验
  uv run python scripts/check_catalog.py --industry --pool --gold   # 全部（L3 parent 断言）

退出码：0 = 通过；1 = 存在 error；2 = 仅 warning。
"""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path

from stock_data.fetcher.industry.customs.parsers.catalog import (
    load_hs_catalog,
    load_hs_catalog_rows,
)

CONFIG_DIR = Path("config/data/customs")
CATEGORIES_PATH = CONFIG_DIR / "categories.csv"
PRODUCTS_PATH = CONFIG_DIR / "good_products.csv"
HS_CODES_PATH = CONFIG_DIR / "good_h8_codes.csv"
DIMENSION_PATH = Path(
    "data/curated/derived/market=CN/sw_2021_industry_dimension_golden/data.parquet"
)
GOLD_PATH = Path("data/curated/industry/customs_trade_gacc.parquet")

# 108 产品回测池（来源：docs/research/customs_export_forward/18_/24_ 号文档，2026-09）。
# 与 good_products.csv 的 diff 属维护审计项，防止产品静默丢失（如 aquatic_products 案例）。
POOL_108 = {
    # A 量价同动（16）
    "battery",
    "copper_wire",
    "battery_copper_foil",
    "battery_electrolyte",
    "aluminum_sheet",
    "auto_chassis",
    "cathode_material",
    "refrigerant",
    "aluminum_foil",
    "semiconductor_ic",
    "vitamins",
    "auto_glass",
    "auto_parts",
    "commercial_nev",
    "nylon_filament",
    "tio2",
    # C 内销/政策（5）
    "forklift",
    "wheel_loader",
    "excavator",
    "crane",
    "machine_tool",
    # D 价格脉冲（21）
    "silver",
    "bev",
    "aluminum_unwrought",
    "caustic_soda",
    "zinc",
    "copper_unwrought",
    "diagnostic_immunological",
    "hev",
    "lithium_chemicals",
    "methanol",
    "ethylene_glycol",
    "urea",
    "coal",
    "pharma_vaccines",
    "fuel_cell",
    "compound_fertilizer",
    "alloy_steel",
    "hot_rolled_steel",
    "phev",
    "soda_ash",
    "potash_fertilizer",
    # B 量驱动/价驱动主导（66）
    "inverter",
    "pcb",
    "auto_electronics",
    "knit_apparel",
    "seamless_steel_tube",
    "shipbuilding",
    "auto_wheel",
    "battery_aluminum_foil",
    "phosphoric_acid",
    "wind_parts",
    "api_paracetamol",
    "auto_tire",
    "battery_separator",
    "electrolyte_salt",
    "phosphate_fertilizer",
    "television",
    "anode_material",
    "auto_body",
    "wind_turbine",
    "cathode_precursor",
    "coke",
    "flat_panel_module",
    "polyester_staple",
    "flat_glass",
    "washing_machine",
    "auto_drive_motor",
    "ceramic_tile",
    "hydrogen_electrolyzer",
    "polyester_fabric",
    "motorcycle",
    "plant_extract",
    "refrigerator",
    "semiconductor_equipment",
    "battery_parts",
    "furniture",
    "mdi",
    "pesticide",
    "server",
    "technical_ceramic",
    "woven_apparel",
    "glass_fiber",
    "power_tools",
    "robot_vacuum",
    "small_appliance",
    "api_heparin",
    "wireless_earbud",
    "pharma_chemicals",
    "refined_products",
    "smartphone",
    "optical_module",
    "viscose_staple",
    "air_conditioner",
    "coated_steel",
    "antibiotics",
    "home_textile",
    "ammonium_nitrate",
    "network_equipment",
    "audio_device",
    "laptop",
    "polyester_filament",
    "seating",
    "solar_cell",
    "aquatic_products",
    "medical_device",
    "polysilicon",
    "transformer",
}


def load_csv(path: Path) -> list[dict[str, str]]:
    import csv

    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [{k: (v or "").strip() for k, v in row.items() if k} for row in csv.DictReader(f)]


def check_basic(errors: list[str], warnings: list[str]) -> None:
    categories = load_csv(CATEGORIES_PATH)
    products = load_csv(PRODUCTS_PATH)
    hs_codes = load_csv(HS_CODES_PATH)

    if not hs_codes:
        errors.append(f"税号表为空或不存在: {HS_CODES_PATH}")
        return
    if not products:
        errors.append(f"产品主表为空或不存在: {PRODUCTS_PATH}")
        return
    if not categories:
        warnings.append(f"分类枚举为空或不存在: {CATEGORIES_PATH}")

    # categories 唯一性
    seen_cat: dict[str, str] = {}
    for r in categories:
        key = r["category_key"]
        if not key:
            errors.append("categories.csv 存在空 category_key")
            continue
        if key in seen_cat:
            errors.append(f"categories.csv category_key 重复: {key}")
        seen_cat[key] = r.get("category_name", "")

    # products 唯一性 + 引用完整性
    prod_keys: dict[str, dict[str, str]] = {}
    for r in products:
        key = r["product_key"]
        if not key:
            errors.append("good_products.csv 存在空 product_key")
            continue
        if key in prod_keys:
            errors.append(f"good_products.csv product_key 重复: {key}")
        prod_keys[key] = r
        ck = r.get("category_key", "")
        if seen_cat and ck not in seen_cat:
            errors.append(f"产品 {key} 引用未知 category_key: {ck!r}")

    # hs_codes 码格式 + 引用完整性 + 唯一性
    seen_code: dict[str, str] = {}
    parent_products: dict[str, set[str]] = defaultdict(set)
    for r in hs_codes:
        code = r["hs_code"]
        if not re.fullmatch(r"\d{8}", code):
            errors.append(f"hs_code 非 8 位数字: {code!r}")
            continue
        if code in seen_code:
            errors.append(f"hs_code 重复: {code}")
        seen_code[code] = r["product_key"]
        if r.get("hs_parent_code", "") != code[:6]:
            errors.append(
                f"{code}: hs_parent_code 应为 {code[:6]}, 实为 {r.get('hs_parent_code')!r}"
            )
        if r.get("hs_level", "") != "8":
            errors.append(f"{code}: hs_level 应为 8, 实为 {r.get('hs_level')!r}")
        pk = r.get("product_key", "")
        if pk not in prod_keys:
            errors.append(f"税号 {code} 引用未知 product_key: {pk!r}")
        else:
            parent_products[code[:6]].add(pk)

    # 混品品目告警（同一 6 位前缀跨多个 product_key）
    for parent in sorted(parent_products):
        prods = parent_products[parent]
        if len(prods) > 1:
            warnings.append(
                f"混品品目 {parent}: 跨 {len(prods)} 个产品 {sorted(prods)}（需确认显式拆分）"
            )


def check_industry(errors: list[str], warnings: list[str]) -> None:
    if not DIMENSION_PATH.exists():
        warnings.append(f"维度黄金表不存在，跳过 L1/L2/L3 校验: {DIMENSION_PATH}")
        return
    import pandas as pd

    dim = pd.read_parquet(DIMENSION_PATH)
    by_index: dict[str, dict] = {}
    for _, r in dim.iterrows():
        by_index[str(r["index_code"])] = {
            "industry_code": str(r["industry_code"]),
            "level": str(r["level"]),
            "parent_code": str(r["parent_code"]),
            "name": str(r["industry_name"]),
        }

    products = load_csv(PRODUCTS_PATH)
    for p in products:
        pk = p["product_key"]
        l2_codes = [c for c in p.get("target_l2_codes", "").split(";") if c]
        l2_industry = set()
        for c in l2_codes:
            info = by_index.get(c)
            if info is None:
                errors.append(f"产品 {pk}: L2 {c} 不在维度黄金表")
                continue
            if info["level"] != "L2":
                errors.append(f"产品 {pk}: L2 {c} 层级为 {info['level']}, 应为 L2")
            l2_industry.add(info["industry_code"])
        for c in [c for c in p.get("target_l3_codes", "").split(";") if c]:
            info = by_index.get(c)
            if info is None:
                errors.append(f"产品 {pk}: L3 {c} 不在维度黄金表")
                continue
            if info["level"] != "L3":
                errors.append(f"产品 {pk}: L3 {c} 层级为 {info['level']}, 应为 L3")
            if l2_industry and info["parent_code"] not in l2_industry:
                errors.append(
                    f"产品 {pk}: L3 {c} parent_code={info['parent_code']} 不属于 L2 {l2_codes}"
                )
        for c in [c for c in p.get("target_l1_code", "").split(";") if c]:
            info = by_index.get(c)
            if info is None:
                errors.append(f"产品 {pk}: L1 {c} 不在维度黄金表")
            elif info["level"] != "L1":
                errors.append(f"产品 {pk}: L1 {c} 层级为 {info['level']}, 应为 L1")


def check_pool(warnings: list[str]) -> None:
    """108 回测池 ↔ good_products.csv 一致性（防静默丢失/静默扩展）。"""
    products = load_csv(PRODUCTS_PATH)
    keys = {p["product_key"] for p in products}
    missing = sorted(POOL_108 - keys)
    extra = sorted(keys - POOL_108)
    if missing:
        warnings.append(
            f"108 回测池缺产品 {len(missing)}: {missing}（18/24 号文档 vs good_products.csv）"
        )
    if extra:
        warnings.append(
            f"现行 catalog 超出 108 池 {len(extra)} 个（须确认是有意扩展）: "
            f"{extra[:20]}{'...' if len(extra) > 20 else ''}"
        )


def check_gold(warnings: list[str]) -> None:
    """黄金表（管线默认输入）↔ catalog 双向一致性：码级与产品级 diff。"""
    if not GOLD_PATH.exists():
        warnings.append(f"黄金表不存在，跳过 gold↔catalog 校验: {GOLD_PATH}")
        return
    import polars as pl

    gold = pl.read_parquet(GOLD_PATH)
    h8 = gold.filter(pl.col("hs_level") == "8").with_columns(
        pl.col("hs_code").cast(pl.String),
        pl.col("product_key").cast(pl.String),
    )
    cat_codes = {r["hs_code"] for r in load_csv(HS_CODES_PATH)}
    cat_prods = {p["product_key"] for p in load_csv(PRODUCTS_PATH)}
    g_codes = set(h8["hs_code"].unique().to_list())
    g_prods = set(h8["product_key"].unique().to_list())

    only_cat_codes = sorted(cat_codes - g_codes)
    only_gold_codes = sorted(g_codes - cat_codes)
    only_cat_prods = sorted(cat_prods - g_prods)
    only_gold_prods = sorted(g_prods - cat_prods)

    warnings.append(
        f"黄金表↔catalog 码级 diff：catalog 有 gold 无 {len(only_cat_codes)} 码 / "
        f"gold 有 catalog 无 {len(only_gold_codes)} 码"
    )
    if only_cat_codes:
        warnings.append(f"  catalog 有 gold 无（前 20）: {only_cat_codes[:20]}")
    if only_gold_codes:
        warnings.append(f"  gold 有 catalog 无（前 20）: {only_gold_codes[:20]}")
    if only_cat_prods:
        warnings.append(f"  catalog 产品在黄金表 0 行（{len(only_cat_prods)}）: {only_cat_prods}")
    if only_gold_prods:
        warnings.append(
            f"  gold hs8 产品不在 catalog（{len(only_gold_prods)}，前 20）: {only_gold_prods[:20]}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 customs catalog 三表一致性")
    parser.add_argument("--industry", action="store_true", help="追加 L1/L2/L3 维度黄金表校验")
    parser.add_argument("--pool", action="store_true", help="追加 108 产品回测池 ↔ catalog 校验")
    parser.add_argument("--gold", action="store_true", help="追加 黄金表 ↔ catalog 双向 diff 校验")
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []
    check_basic(errors, warnings)
    if args.industry:
        check_industry(errors, warnings)
    if args.pool:
        check_pool(warnings)
    if args.gold:
        check_gold(warnings)

    # 加一重：loader join 能否加载且无异常
    try:
        rows = load_hs_catalog_rows(HS_CODES_PATH)
        load_hs_catalog(HS_CODES_PATH)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"loader join 失败: {exc}")

    if warnings:
        print("=== 警告 ===")
        for w in warnings:
            print(f"  ⚠ {w}")
    if errors:
        print("=== 错误 ===")
        for e in errors:
            print(f"  ❌ {e}")
        print(f"\n共 {len(errors)} 处错误。")
        return 1
    print(f"✅ catalog 校验通过（{len(rows) if 'rows' in dir() else '?'} 行税号）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
