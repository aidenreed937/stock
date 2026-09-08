"""公司级出口景气观察表：把商品量价拐点下沉到受益公司（段级修正）。

流程（METHODOLOGY_COMPANY_FINAL §4/§7 口径）：
1. 段定义（taxline_segments.csv）→ (product, segment) → hs 码集合；产品级全码作空段
   兜底与对比基线；
2. 黄金表按 export+hs_level=8 过滤，行打段键；
3. 段级/产品级月度聚合（金额全量；数量仅键内已知单位唯一时加总）；
4. 补全月序重算 3MMA yoy / 驱动 / 拐点 / 二阶导（与 product_panel._derive 同口径）；
5. 公司观察表：每 (company, product, 绑定段) 一行 + 产品级对照列（段-产品差）。

产物路径与既有脚本契约一致：``customs_company_exposure.parquet`` / ``_latest.csv``。
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

import polars as pl

from stock_analytics.pipelines.customs_company.config import (
    EXPOSURE_LATEST_FILE,
    EXPOSURE_PANEL_FILE,
)
from stock_data.fetcher.industry.customs.parsers.company_exposure import (
    TaxlineSegmentMap,
    load_company_exposure_map,
    load_taxline_segments,
)


def load_catalog_hs_codes(catalog_path: Path, golden: pl.DataFrame) -> dict[str, list[str]]:
    """Catalog 产品 → hs 码集合（8 位行优先；纯 6 位产品取其 8 位子码）。

    两个数据坑（2026-09 修复）：
    - 前导 0：catalog 6 位码按数值列读取会丢前导 0，与黄金表 hs_parent_code
      （字符串带 0）失配——schema_overrides 保字符串；
    - 新旧码并存：产品同时有 catalog 8 位历史码与 6 位父码的现行 8 位子码时
      合并去重，避免历史码截断序列。
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
    """构建 {key: {type, product_key, segment_key, segment_name, hs_codes}} 键表。"""
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


def build_exposure_panel(
    customs_trade: pl.DataFrame,
    *,
    exposure_map_path: Path | str,
    hs_catalog_path: Path | str,
    segments_path: Path | str,
) -> tuple[pl.DataFrame, pl.DataFrame, dict[str, object]]:
    """构建公司级出口景气观察表（全序列 panel + 最新月公司快照）。

    Args:
        customs_trade: 海关黄金事实表。
        exposure_map_path: company_exposure_map.csv（暴露度）。
        hs_catalog_path: hs_codes_catalog.csv。
        segments_path: taxline_segments.csv（税号段定义）。

    Returns:
        (panel, latest 快照, 统计)。
    """
    exp = customs_trade.filter(
        pl.col("trade_direction") == "export",
        pl.col("hs_level") == "8",
    )

    map_ = load_company_exposure_map(
        map_path=exposure_map_path,
        catalog_path=hs_catalog_path,
        segments_path=segments_path,
    )
    segments_map = load_taxline_segments(segments_path)
    catalog_hs = load_catalog_hs_codes(Path(hs_catalog_path), exp)
    keys = build_segment_key_map(segments_map, catalog_hs)
    if not keys:
        raise ValueError("无段定义也无 catalog 产品码，无法构建序列")

    # hs_code → 所属键（一个 8 位码可能同时属于段键与产品键）
    hs2key: dict[str, list[str]] = {}
    for k, meta in keys.items():
        for code in meta["hs_codes"]:
            hs2key.setdefault(code, []).append(k)
    in_keys = exp.filter(pl.col("hs_code").is_in(list(hs2key)))
    if in_keys.is_empty():
        raise ValueError("黄金表无匹配 hs 码（段/产品码未落数据）")

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

    d_series = tagged.select(pl.col("report_month").str.to_date("%Y-%m").alias("d")).get_column("d")
    all_months = (
        pl.date_range(d_series.min(), d_series.max(), "1mo", eager=True)  # type: ignore[arg-type]
        .dt.strftime("%Y-%m")
        .to_list()  # type: ignore[union-attr]
    )
    panel = _derive(monthly, "key", all_months).sort(["key", "report_month"])
    panel = panel.filter(pl.col("export_value_usd").is_not_null())

    # 公司观察表：每键取"最近可用月"读数（采集缺口产品不丢行，read 月反映实际读数月）
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
    latest = pl.DataFrame(rows_out).sort(["product_key", "company_name", "bind_segment"])
    stats = {
        "key_count": len(keys),
        "panel_keys": panel["key"].n_unique(),
        "skipped": n_no_series,
        "company_rows": latest.height,
        "companies": latest["company_name"].n_unique(),
        "products": latest["product_key"].n_unique(),
        "latest_month": cast("str", panel["report_month"].max()),
    }
    return panel, latest, stats


def save_exposure_panel(
    panel: pl.DataFrame, latest: pl.DataFrame, output_dir: Path | str
) -> tuple[Path, Path]:
    """落盘公司观察表（全序列 parquet + 最新月 CSV，保持既有契约路径）。"""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    pq = root / EXPOSURE_PANEL_FILE
    csv = root / EXPOSURE_LATEST_FILE
    panel.write_parquet(pq)
    latest.write_csv(csv, include_header=True)
    return pq, csv


__all__ = [
    "build_exposure_panel",
    "build_segment_key_map",
    "load_catalog_hs_codes",
    "save_exposure_panel",
]
