#!/usr/bin/env python3
"""公司级出口景气观察表：把商品量价拐点下沉到受益公司（段级修正）。

背景（2026-09 skill 优化）：
- 行业层（L2/L3）区分度不足，同一产品内税号段 yoy 分化可达 +13%~+566%
  （transformer 各容量段），公司绑定段级序列才能体现真实受益；
- 复用 METHODOLOGY_FINAL §2 信号口径（3MMA yoy 四象限/拐点/二阶导）与
  §6.5 桥接规则，公司资产：company_exposure_map.csv（393 公司暴露度）+
  taxline_segments.csv（14 段/5 产品税号段）。

流程：
  1. 段定义（taxline_segments.csv）→ (product, segment) → hs 码集合；
     产品级（hs_codes_catalog.csv 全部 8 位码）作为空段兜底与对比基线；
  2. 黄金表（customs_trade.parquet）按 export+hs_level=8 过滤，行打段键；
  3. 段级/产品级月度聚合：金额全量；数量仅段内已知单位唯一时加总（否则置空）；
  4. 补全月序（2016-01~末月）重算 3MMA 金额/量/价(ASP) yoy、驱动四象限、
     拐点（金额 yoy 符号翻转）与二阶导（量 yoy 见顶回落）——与
     build_customs_product_volume_price._derive 同口径；
  5. 公司观察表：每 (company, product, 绑定段) 一行，空段绑定=产品级；
     附产品级 yoy 对照列（段-产品差即"产品内部分化"）。

用法:
    uv run python scripts/build_customs_company_exposure.py
    uv run python scripts/build_customs_company_exposure.py --output-csv scratch/company_exposure_latest.csv
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any, cast

import polars as pl

from stock_data.fetcher.industry.customs.parsers.company_exposure import (
    TaxlineSegmentMap,
    load_company_exposure_map,
    load_taxline_segments,
)

DEFAULT_INPUT = Path("data/curated/industry/customs_trade.parquet")
DEFAULT_OUTPUT_PQ = Path("data/analytics/industry/customs_company_exposure.parquet")
DEFAULT_OUTPUT_CSV = Path("data/analytics/industry/customs_company_exposure_latest.csv")
DEFAULT_MAP = Path("config/data/customs/company_exposure_map.csv")
DEFAULT_CATALOG = Path("config/data/customs/hs_codes_catalog.csv")
DEFAULT_SEGMENTS = Path("config/data/customs/taxline_segments.csv")


def load_catalog_hs_codes(catalog_path: Path, golden: pl.DataFrame) -> dict[str, list[str]]:
    """catalog 产品 → hs 码集合（8 位行优先；纯 6 位产品取其 8 位子码）。

    口径与 build_customs_product_volume_price 一致：聚合用黄金表 hs_level=8 行，
    6 位父码经 hs_parent_code 匹配其 8 位子码（如 zinc 790111 → 790111xx）。

    两个数据坑（2026-09 修复）：
    - 前导 0：catalog 6 位码 030323 按数值列读取会丢前导 0（变 30323），与
      黄金表 hs_parent_code（字符串带 0）失配——schema_overrides 保字符串；
    - 新旧码并存：产品同时有 catalog 8 位历史码（如疫苗 30022000，数据止
      2021-12）与 6 位父码的现行 8 位子码（30024100）时合并去重，避免
      历史码截断序列。
    """
    cat = pl.read_csv(
        catalog_path,
        schema_overrides={"hs_code": pl.String, "hs_parent_code": pl.String},
    ).select(["product_key", "hs_code", "hs_level"])
    cat = cat.with_columns(pl.col("hs_level").cast(pl.String))
    cat8 = cat.filter(pl.col("hs_level") == "8")
    out: dict[str, list[str]] = {
        r["product_key"]: r["hs_code"]
        for r in cat8.sort("product_key", "hs_code")
        .group_by("product_key")
        .agg(pl.col("hs_code").implode().alias("hs_code"))
        .iter_rows(named=True)
    }
    cat6 = cat.filter(pl.col("hs_level") == "6")
    parent8 = (
        golden.filter(pl.col("hs_level") == "8").select(["hs_parent_code", "hs_code"]).unique()
    )
    six_map = {
        r["hs_parent_code"]: r["hs_code"]
        for r in parent8.sort("hs_parent_code", "hs_code")
        .group_by("hs_parent_code")
        .agg(pl.col("hs_code").implode().alias("hs_code"))
        .iter_rows(named=True)
    }
    for row in (
        cat6.sort("product_key", "hs_code")
        .group_by("product_key")
        .agg(pl.col("hs_code").implode().alias("hs_code"))
        .iter_rows(named=True)
    ):
        product: str = row["product_key"]
        parents: Iterable[str] = row["hs_code"]
        extra = sorted({c for p in parents for c in six_map.get(p, [])})
        out[product] = sorted(set(out.get(product, [])) | set(extra))
    return out


def build_segment_key_map(
    segments_map: TaxlineSegmentMap, catalog_hs: dict[str, list[str]]
) -> dict[str, dict[str, Any]]:
    """构建 {key: {type, product_key, segment_key, segment_name, hs_codes}} 键表。

    键类型：segment（税号段）与 product（产品级全码，空段兜底与对比基线）。
    """
    keys: dict[str, dict[str, Any]] = {}
    for seg in segments_map.segments:
        k = f"{seg.product_key}::{seg.segment_key}"
        keys[k] = {
            "type": "segment",
            "product_key": seg.product_key,
            "segment_key": seg.segment_key,
            "segment_name": seg.segment_name,
            "hs_codes": list(seg.hs_codes),
        }
    for product, codes in catalog_hs.items():
        k = f"{product}::product"
        keys[k] = {
            "type": "product",
            "product_key": product,
            "segment_key": "product",
            "segment_name": "产品级(全码)",
            "hs_codes": codes,
        }
    return keys


def _derive(df: pl.DataFrame, key: str, all_months: list[str]) -> pl.DataFrame:
    """按 key 补全月序，重算 3MMA 值/量/价 yoy、驱动与拐点（product 面板同口径）。"""
    base = pl.DataFrame({key: df[key].unique().to_list()}).join(
        pl.DataFrame({"report_month": all_months}), how="cross"
    )
    df = base.join(df, on=[key, "report_month"], how="left")
    return (
        df.sort([key, "report_month"])
        .with_columns(
            pl.col("export_value_usd").rolling_mean(3, min_samples=3).over(key).alias("v3"),
            pl.col("export_volume").rolling_mean(3, min_samples=3).over(key).alias("q3"),
        )
        .with_columns(
            (pl.col("v3") / pl.col("v3").shift(12).over(key) - 1).alias("value_yoy_3mma"),
            (pl.col("q3") / pl.col("q3").shift(12).over(key) - 1).alias("volume_yoy_3mma"),
        )
        .with_columns((pl.col("v3") / pl.col("q3")).alias("asp_3mma"))
        .with_columns(
            (pl.col("asp_3mma") / pl.col("asp_3mma").shift(12).over(key) - 1).alias(
                "price_yoy_3mma"
            )
        )
        .with_columns(
            pl.when(pl.col("volume_yoy_3mma").is_nan() | pl.col("price_yoy_3mma").is_nan())
            .then(None)
            .when((pl.col("volume_yoy_3mma") > 0) & (pl.col("price_yoy_3mma") > 0))
            .then(pl.lit("量价齐升"))
            .when((pl.col("volume_yoy_3mma") > 0) & (pl.col("price_yoy_3mma") <= 0))
            .then(pl.lit("量驱动"))
            .when((pl.col("volume_yoy_3mma") <= 0) & (pl.col("price_yoy_3mma") > 0))
            .then(pl.lit("价驱动"))
            .when((pl.col("volume_yoy_3mma") <= 0) & (pl.col("price_yoy_3mma") <= 0))
            .then(pl.lit("双弱"))
            .otherwise(None)
            .alias("驱动类型")
        )
        .with_columns(
            pl.when(
                (pl.col("value_yoy_3mma").shift(1).over(key) < 0) & (pl.col("value_yoy_3mma") >= 0)
            )
            .then(pl.lit("启动拐点"))
            .when(
                (pl.col("value_yoy_3mma").shift(1).over(key) > 0) & (pl.col("value_yoy_3mma") <= 0)
            )
            .then(pl.lit("见顶拐点"))
            .otherwise(None)
            .alias("拐点"),
            pl.when(
                (pl.col("volume_yoy_3mma") >= 0)
                & (
                    pl.col("volume_yoy_3mma")
                    < pl.col("volume_yoy_3mma").rolling_max(4, min_samples=2).shift(1).over(key)
                )
                & (pl.col("volume_yoy_3mma").rolling_max(6, min_samples=3).over(key) > 0.1)
            )
            .then(pl.lit("量增速回落"))
            .otherwise(None)
            .alias("二阶导"),
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="海关黄金事实表路径")
    parser.add_argument("--output-pq", default=str(DEFAULT_OUTPUT_PQ), help="全序列 parquet")
    parser.add_argument("--output-csv", default=str(DEFAULT_OUTPUT_CSV), help="最新月公司快照 CSV")
    parser.add_argument("--map", default=str(DEFAULT_MAP), help="company exposure map")
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG), help="hs catalog")
    parser.add_argument("--segments", default=str(DEFAULT_SEGMENTS), help="税号段定义")
    args = parser.parse_args()

    df = pl.read_parquet(args.input)
    exp = df.filter(
        pl.col("trade_direction") == "export",
        pl.col("hs_level") == "8",
    )

    map_ = load_company_exposure_map(
        map_path=args.map, catalog_path=args.catalog, segments_path=args.segments
    )
    segments_map = load_taxline_segments(args.segments)
    catalog_hs = load_catalog_hs_codes(args.catalog, exp)
    keys = build_segment_key_map(segments_map, catalog_hs)
    if not keys:
        print("[FAIL] 无段定义也无 catalog 产品码，无法构建序列")
        return 1

    # hs_code → 所属键（一个 8 位码可能同时属于段键与产品键）；join 打键保持类型
    hs2key: dict[str, list[str]] = {}
    for k, meta in keys.items():
        for code in meta["hs_codes"]:
            hs2key.setdefault(code, []).append(k)
    in_keys = exp.filter(pl.col("hs_code").is_in(list(hs2key)))
    if in_keys.is_empty():
        print("[FAIL] 黄金表无匹配 hs 码（段/产品码未落数据）")
        return 1

    key_df = pl.DataFrame(
        [{"hs_code": code, "key": k} for k, meta in keys.items() for code in meta["hs_codes"]]
    )
    need = [
        "hs_code",
        "report_month",
        "export_value_usd",
        "export_volume",
        "quantity_unit_norm",
        "unit_known",
    ]
    tagged = in_keys.select(need).join(key_df, on="hs_code", how="inner")

    # 月度聚合：金额全量；数量仅键内已知单位唯一时加总
    unit_n = (
        tagged.filter(pl.col("unit_known"))
        .group_by("key")
        .agg(pl.col("quantity_unit_norm").unique().len().alias("n_units"))
    )
    tagged = tagged.join(unit_n, on="key", how="left")
    monthly = (
        tagged.group_by(["key", "report_month"])
        .agg(
            pl.col("export_value_usd").sum().alias("export_value_usd"),
            pl.col("export_volume").sum().alias("_vsum"),
            pl.col("n_units").first().alias("_nu"),
        )
        .with_columns(
            pl.when(pl.col("_nu") == 1).then(pl.col("_vsum")).otherwise(None).alias("export_volume")
        )
        .drop(["_vsum", "_nu"])
    )

    d = tagged.select(pl.col("report_month").str.to_date("%Y-%m").alias("d"))
    all_months = (
        pl.date_range(cast("date", d["d"].min()), cast("date", d["d"].max()), "1mo", eager=True)
        .dt.strftime("%Y-%m")
        .to_list()
    )
    panel = _derive(monthly, "key", all_months).sort(["key", "report_month"])
    panel = panel.filter(pl.col("export_value_usd").is_not_null())
    latest_month: str = cast("str", panel["report_month"].max())

    out_pq = Path(args.output_pq)
    out_pq.parent.mkdir(parents=True, exist_ok=True)
    panel.write_parquet(out_pq)

    # 公司观察表：每键取"最近可用月"读数（robot_vacuum 等采集缺口产品不丢行，
    # report_month 列反映实际读数月）
    def _last_obs(key: str) -> dict[str, Any] | None:
        sub = panel.filter(pl.col("key") == key)
        return sub.sort("report_month").tail(1).row(0, named=True) if not sub.is_empty() else None

    rows_out = []
    n_no_series = 0
    for e in map_.entries:
        product = e.product_key
        prod_key = f"{product}::product"
        segments = [s.strip() for s in e.taxline_segment.split(";") if s.strip()]
        if not segments:
            segments = ["product"]  # 空段=绑整个产品
        for seg in segments:
            k = f"{product}::{seg}"
            key_meta: dict[str, Any] | None = keys.get(k)
            if key_meta is None:
                n_no_series += 1
                continue
            row = _last_obs(k)
            if row is None:
                n_no_series += 1
                continue
            prod_row = _last_obs(prod_key)
            rows_out.append(
                {
                    "company_name": e.company_name,
                    "stock_code": e.stock_code,
                    "product_key": product,
                    "exposure": e.exposure,
                    "bind_segment": seg if seg != "product" else "",
                    "segment_name": key_meta["segment_name"],
                    "n_hs_codes": len(key_meta["hs_codes"]),
                    "report_month": row["report_month"],
                    "value_yoy_3mma": row["value_yoy_3mma"],
                    "volume_yoy_3mma": row["volume_yoy_3mma"],
                    "price_yoy_3mma": row["price_yoy_3mma"],
                    "驱动类型": row["驱动类型"],
                    "拐点": row["拐点"],
                    "二阶导": row["二阶导"],
                    "product_value_yoy": (prod_row["value_yoy_3mma"] if prod_row else None),
                    "segment_minus_product": (
                        (row["value_yoy_3mma"] - prod_row["value_yoy_3mma"])
                        if (prod_row and row["value_yoy_3mma"] is not None)
                        else None
                    ),
                }
            )
    out_df = pl.DataFrame(rows_out).sort(["product_key", "company_name", "bind_segment"])
    out_df.write_csv(Path(args.output_csv), include_header=True)

    # 汇总：同产品公司间区分度
    print(
        f"序列键数: {len(keys)}  段级/产品级序列落数据: {panel['key'].n_unique()}  "
        f"跳过(无序列): {n_no_series}"
    )
    print(
        f"公司-段行: {out_df.height}  覆盖公司: {out_df['company_name'].n_unique()}  "
        f"产品: {out_df['product_key'].n_unique()}"
    )
    print(f"最新月 {latest_month} 公司段级 yoy 分布:")
    print(
        out_df.filter(pl.col("value_yoy_3mma").is_not_null())
        .group_by("驱动类型")
        .len()
        .sort("len", descending=True)
        .to_pandas()
        .to_string(index=False)
    )
    print(f"\n已写出: {out_pq} / {Path(args.output_csv)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
