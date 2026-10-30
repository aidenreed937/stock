#!/usr/bin/env python3
"""A 股中高端出口商品覆盖审计：good_products.csv × good_h8_codes.csv。

用途（配合 docs/research/customs_export_forward/34_*_coverage_audit_2026_10.md）：
  1. 内部完整性：每个产品是否有税号行、税号引用是否合法、码格式/重复/父码；
  2. 108 产品回测池 diff：仓库权威口径（04/18/24 号文档）应覆盖的池 vs 现行 catalog；
  3. 中高端制造子集分层：按类别白名单 + 高端材料白名单，输出子集覆盖统计；
  4. 代理/限定口径标记：description 是否含代理、无独立 h8、品目级无数量等标记。

只读审计，不修改 config/data/customs/ 任何文件；事实表落盘 data/analytics/
（gitignore 目录）。用法：uv run python scripts/audit_customs_catalog_coverage.py
"""

from __future__ import annotations

import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

CONFIG_DIR = Path("config/data/customs")
PRODUCTS_PATH = CONFIG_DIR / "good_products.csv"
HS_PATH = CONFIG_DIR / "good_h8_codes.csv"
CATEGORIES_PATH = CONFIG_DIR / "categories.csv"
GACC_QUERY_PATH = CONFIG_DIR / "gacc_query_codes.txt"
OUT_CSV = Path("data/analytics/industry/customs_catalog_coverage_audit_2026_10.csv")

# ---- 仓库权威口径：108 产品回测池（docs 18/24 号文档，2026-09） ----
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

# ---- 中高端制造子集分层（审计口径假设，见 34 号文档 §4） ----
# 核心中高端制造类目（整机/设备/部件/电子/医药/家电/汽车/军工）
MID_HIGH_CATEGORIES = {
    "automotive",
    "machinery_and_equipment",
    "power_and_new_energy",
    "tmt_and_electronics",
    "healthcare",
    "consumer_and_appliances",
    "defense_aerospace",
    "furniture_and_home",
}
# 其余类目中的高附加值材料/加工材白名单（不属于大宗原材料或低端纺织）
MID_HIGH_EXTRA = {
    "rare_earth_magnet",  # 稀土永磁
    "battery_aluminum_foil",  # 锂电铝箔
    "battery_copper_foil",  # 锂电铜箔
    "aluminum_foil",  # 铝箔（加工材）
    "aluminum_sheet",  # 铝板带（加工材）
    "lithium_chemicals",  # 锂盐（电池链上游材料）
    "mdi",  # 聚合 MDI（聚氨酯核心原料）
    "refrigerant",  # 三代制冷剂（HFC，配额制出口）
    "tio2",  # 钛白粉（高附加值颜料）
    "feed_additives",  # 饲料级赖氨酸（生物发酵）
    "alloy_steel",  # 合金钢板材（特钢）
    "seamless_steel_tube",  # 无缝钢管（管材加工）
    "glass_fiber",  # 玻璃纤维（风电/电子级材料）
}

# 代理/限定口径标记（description 中出现任一即视为“非物理全集口径”）
PROXY_PATTERNS = (
    "代理口径",
    "无独立 h8",
    "品目级无数量",
    "限定口径",
    "暂由",
    "不扩",
    "防双计",
    "桥接",
    "口径待定",
)

# 仓库口径之外、A 股中高端出口商品的候选缺口（外部推断，待人工确认后算数）
EXTERNAL_CANDIDATES = [
    (
        "ev_charger",
        "充电桩（新能源车充电设备）",
        "中高端",
        "曾见于 04 号文档补码记录，现行 catalog 无产品行",
    ),
    ("bearing", "轴承（新强联/五洲新春等）", "中高端", "HS 8482，不在现行 catalog"),
    (
        "industrial_valve",
        "工业阀门（纽威股份等）",
        "中高端",
        "HS 8481 仅覆盖电子膨胀阀/减压阀 3 码，未覆盖工业阀门全类",
    ),
    ("hydraulic", "液压件（恒立液压/艾迪精密）", "中高端", "HS 8412/8413 部分，不在现行 catalog"),
    ("gas_turbine", "燃气轮机（东方电气等）", "中高端", "HS 8411，不在现行 catalog"),
    (
        "tractor",
        "拖拉机（一拖股份等）",
        "中高端",
        "HS 8701 仅半挂牵引车（heavy_truck），未覆盖拖拉机",
    ),
    ("container", "集装箱（中集集团）", "中高端", "HS 8609，不在现行 catalog"),
    (
        "port_machine",
        "港口机械（振华重工岸桥）",
        "中高端",
        "HS 8426 仅覆盖起重机代表码，岸桥/场桥未单列",
    ),
    ("industrial_motor", "工业电机/微电机（卧龙电驱等）", "中高端", "HS 8501 仅覆盖汽车驱动电机段"),
    (
        "semiconductor_material",
        "半导体材料（光刻胶/电子特气/抛光材料）",
        "中高端",
        "catalog 只有设备+IC，材料层空白",
    ),
]


def load_csv(path: Path) -> list[dict[str, str]]:
    """读取 CSV，剔除空 key，返回行 dict 列表。"""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [{k: (v or "").strip() for k, v in row.items() if k} for row in csv.DictReader(f)]


def gacc_query_count(path: Path) -> int | None:
    """从 gacc_query_codes.txt 首行解析查询码总数。"""
    if not path.exists():
        return None
    first = path.read_text(encoding="utf-8").splitlines()[0]
    m = re.search(r"共\s*(\d+)\s*个", first)
    return int(m.group(1)) if m else None


def main() -> int:
    products = load_csv(PRODUCTS_PATH)
    hs_rows = load_csv(HS_PATH)
    categories = load_csv(CATEGORIES_PATH)

    errors: list[str] = []
    warnings: list[str] = []

    cat_names = {r["category_key"]: r.get("category_name", "") for r in categories}
    prod_by_key: dict[str, dict[str, str]] = {}
    for r in products:
        key = r.get("product_key", "")
        if not key:
            errors.append("good_products.csv 存在空 product_key")
            continue
        if key in prod_by_key:
            errors.append(f"good_products.csv product_key 重复: {key}")
        prod_by_key[key] = r

    codes_by_product: dict[str, list[str]] = defaultdict(list)
    seen_code: dict[str, str] = {}
    parent_products: dict[str, set[str]] = defaultdict(set)
    for r in hs_rows:
        code = r.get("hs_code", "")
        if not re.fullmatch(r"\d{8}", code):
            errors.append(f"hs_code 非 8 位数字: {code!r}")
            continue
        if code in seen_code:
            errors.append(f"hs_code 重复: {code}")
        seen_code[code] = r.get("product_key", "")
        if r.get("hs_parent_code", "") != code[:6]:
            errors.append(
                f"{code}: hs_parent_code 应为 {code[:6]}, 实为 {r.get('hs_parent_code')!r}"
            )
        if r.get("hs_level", "") != "8":
            errors.append(f"{code}: hs_level 应为 8, 实为 {r.get('hs_level')!r}")
        pk = r.get("product_key", "")
        if pk not in prod_by_key:
            errors.append(f"税号 {code} 引用未知 product_key: {pk!r}")
        else:
            codes_by_product[pk].append(code)
            parent_products[code[:6]].add(pk)

    # 内部完整性结论
    n_prod = len(prod_by_key)
    n_codes = len(seen_code)
    zero_code = sorted(p for p in prod_by_key if not codes_by_product.get(p))
    counts = Counter({p: len(c) for p, c in codes_by_product.items()})
    mixed_parents = sorted(p for p, prods in parent_products.items() if len(prods) > 1)

    # 108 池 diff
    cur_keys = set(prod_by_key)
    missing_108 = sorted(POOL_108 - cur_keys)
    added_beyond_108 = sorted(cur_keys - POOL_108)

    # 中高端子集
    is_mid_high = {
        p: (
            (prod_by_key[p].get("category_key", "") in MID_HIGH_CATEGORIES) or (p in MID_HIGH_EXTRA)
        )
        for p in cur_keys
    }
    mid_high = sorted(p for p in cur_keys if is_mid_high[p])
    non_mid_high = sorted(p for p in cur_keys if not is_mid_high[p])
    mid_high_zero = sorted(p for p in mid_high if not codes_by_product.get(p))

    # 代理/限定口径标记
    def proxy_marker(p: str) -> str:
        desc = prod_by_key[p].get("description", "")
        hits = [pat for pat in PROXY_PATTERNS if pat in desc]
        return "；".join(hits) if hits else ""

    proxy_products = sorted(p for p in cur_keys if proxy_marker(p))

    # ---- 打印 ----
    out = sys.stdout
    out.write("=== A股中高端出口商品覆盖审计（config/data/customs） ===\n")
    out.write(f"good_products.csv   产品行：{n_prod}\n")
    out.write(f"good_h8_codes.csv   税号行：{n_codes}\n")
    q = gacc_query_count(GACC_QUERY_PATH)
    out.write(f"gacc_query_codes.txt 查询码：{q if q is not None else 'N/A'}\n")
    out.write(
        f"taxline_segments.csv 段数：{len(load_csv(CONFIG_DIR / 'taxline_segments.csv'))}\n\n"
    )

    if zero_code:
        out.write(f"⚠ 无独立税号的产品（{len(zero_code)}）：{zero_code}\n")
    if missing_108:
        out.write(f"⚠ 108 回测池缺产品（{len(missing_108)}）：{missing_108}\n")
    if added_beyond_108:
        out.write(f"ℹ 现行 catalog 超出 108 池的新增产品（{len(added_beyond_108)}）\n")
    out.write(
        f"ℹ 税号数分布：min={min(counts.values()) if counts else 0}, "
        f"median={sorted(counts.values())[len(counts) // 2] if counts else 0}, "
        f"max={max(counts.values()) if counts else 0}\n"
    )
    out.write(f"ℹ 混品品目（同一 6 位前缀跨产品，需显式拆分确认）：{len(mixed_parents)} 个\n")
    out.write(
        f"ℹ 中高端制造子集：{len(mid_high)}/{n_prod} 产品（"
        f"无独立税号 {len(mid_high_zero)}：{mid_high_zero or '无'})\n"
    )
    out.write(f"ℹ 代理/限定口径产品（{len(proxy_products)}）：{proxy_products}\n\n")

    # ---- 外部候选缺口（不参与仓库口径结论） ----
    out.write("=== 仓库口径之外的中高端出口商品候选缺口（待确认，不计入结论） ===\n")
    for key, name, tier, note in EXTERNAL_CANDIDATES:
        in_cat = "已在 catalog" if key in cur_keys else "不在 catalog"
        out.write(f"• {key}（{name}）：{tier}｜{in_cat}｜{note}\n")
    out.write("\n")

    if errors:
        out.write("=== 内部错误 ===\n")
        for e in errors:
            out.write(f"  ❌ {e}\n")
        out.write(f"\n共 {len(errors)} 处错误。\n")
    else:
        out.write(f"✅ 内部引用完整性通过（{n_codes} 行税号 / {n_prod} 产品）\n")

    # ---- 事实表落盘 ----
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "product_key",
                "product_name",
                "category_key",
                "category_name",
                "hs_code_count",
                "has_hs_codes",
                "in_pool_108",
                "is_mid_high",
                "proxy_or_limited",
                "target_l1_name",
                "target_l2_names",
                "description",
            ],
        )
        writer.writeheader()
        for p in sorted(cur_keys):
            r = prod_by_key[p]
            writer.writerow(
                {
                    "product_key": p,
                    "product_name": r.get("product_name", ""),
                    "category_key": r.get("category_key", ""),
                    "category_name": cat_names.get(r.get("category_key", ""), ""),
                    "hs_code_count": len(codes_by_product[p]),
                    "has_hs_codes": "Y" if codes_by_product[p] else "N",
                    "in_pool_108": "Y" if p in POOL_108 else "N",
                    "is_mid_high": "Y" if is_mid_high[p] else "N",
                    "proxy_or_limited": proxy_marker(p),
                    "target_l1_name": r.get("target_l1_name", ""),
                    "target_l2_names": r.get("target_l2_names", ""),
                    "description": r.get("description", ""),
                }
            )
    out.write(f"事实表已落盘：{OUT_CSV}\n")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
