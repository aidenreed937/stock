#!/usr/bin/env python3
"""商品级（product_key × unit_segment 粒度）出口量价拐点面板。

按 METHODOLOGY_FINAL.md 定稿口径（§2 信号定义 / §6.5 桥接强制规则）实现：
  1. 取出口方向、hs_level=8、非组合码（多映射）行；
  2. 单位归一 + 段级可加总判定（复用 stock_data.fetcher.industry.customs.transforms.volume_price）；
  3. 拆段：同一产品跨 HS 混用物理单位（如半导体设备 units vs kg / PCB kg 残行）
     时，按 catalog 定义单位拆成独立子序列（unit_segment），各自可加总；
  4. 按 (product_key, unit_segment, report_month) 聚合金额全量 / 数量仅可加总段；
  5. 补全 2016-01 ~ 末月完整月序，统一重算 3MMA 金额/量/价(ASP) yoy；
  6. 驱动类型四象限（量价齐升/量驱动/价驱动/双弱）；
  7. 拐点（金额 yoy 由负转正=启动、由正转负=见顶）与二阶导（量 yoy 见顶回落）标注；
  8. 桥接校验：L2 组合码行跳过并披露；L3 归属一致性断言（parent_code == L2 码）。

用法:
    uv run python scripts/build_customs_product_volume_price.py
    uv run python scripts/build_customs_product_volume_price.py --output data/analytics/industry/customs_product_volume_price.parquet
"""

from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl

from stock_data.catalog import DataCatalog
from stock_data.catalog.sw_industry_golden import load_sw_2021_industry_dimension
from stock_data.core.runtime import DataRuntimeContext
from stock_data.fetcher.industry.customs.transforms.volume_price import (
    KNOWN_UNITS,
    flag_volume_aggregable,
    normalize_quantity_unit,
)

DEFAULT_INPUT = Path("data/curated/industry/customs_trade.parquet")
DEFAULT_OUTPUT = Path("data/analytics/industry/customs_product_volume_price.parquet")
DEFAULT_CATALOG = Path("config/data/customs/hs_codes_catalog.csv")
DIM_LEVEL = "L3"  # 归属一致性断言基于 L3 维度表
UNMAPPED_SEG = "UNMAPPED"  # 不在 catalog 的 hs 码段（如 pcb 85340000 残行）


def _load_unit_segments(catalog_path: Path) -> pl.DataFrame:
    """从 catalog 构建 (product_key, hs_code/hs_parent_code → 定义单位) 段表。

    只取 6/8 位数字编码行（水产品等 5 位编码行被 polars 读作 Int64 丢失前导 0，
    绕过 load_hs_catalog_rows 的严格校验，且渔业本身单单位不影响分段）。
    """
    cat = pl.read_csv(catalog_path).select(
        ["product_key", "hs_code", "hs_level", "hs_parent_code", "quantity_unit"]
    ).with_columns(pl.col("hs_code").cast(pl.String), pl.col("hs_parent_code").cast(pl.String))
    cat = cat.filter(pl.col("hs_code").str.len_chars().is_in([6, 8]))
    # 8 位行按 hs_code 精确匹配；6 位行使 hs_parent_code 可匹配
    return cat


def _assign_unit_segment(exp: pl.DataFrame, cat: pl.DataFrame) -> pl.DataFrame:
    """按行自身单位 + catalog 定义为每行打段标，(product_key, unit_segment) 粒度。

    分段规则（METHODOLOGY_FINAL §2 量价关系优先扩展）：
    - **单单位产品不拆段**：产品有量行单位唯一且已知 → 全部行（含 catalog 未收录
      HS 码与 N/A/mixed 占位）归入该单位段，金额全量、序列连续（如 solar_cell 全 units）；
    - **混单位产品按行单位拆段**：同一产品跨 HS / 跨数据源混用物理单位（如半导体
      设备 units vs kg、轮胎 UN units vs GACC kg、白银 UN kg vs GACC 克）时，以行
      自身已知单位分段，各自单单位可加总，不再整产品置空数量；
    - 段标优先级：① 行自身已知单位 → ② catalog 8 位精确 → ③ catalog 6 位父码 →
      ④ 仍未知（N/A/mixed/-）归 UNMAPPED（金额照算、量价不判）。
    """
    # 先判定单单位产品（有量行单位归一去重后唯一且已知）
    prod_units = (
        exp.filter(pl.col("export_volume").is_not_null() & (pl.col("export_volume") > 0))
        .group_by("product_key")
        .agg(pl.col("quantity_unit_norm").unique().alias("__units"))
        .with_columns(pl.col("__units").list.len().alias("__n"))
    )
    single = prod_units.filter(
        (pl.col("__n") == 1) & (pl.col("__units").list.first().is_in(KNOWN_UNITS))
    ).with_columns(pl.col("__units").list.first().alias("_unit"))
    single_unit_prods = single["product_key"].to_list()
    single_unit_map = dict(zip(single["product_key"].to_list(), single["_unit"].to_list()))

    seg8 = cat.filter(pl.col("hs_level").cast(pl.String) == "8").select(
        ["product_key", "hs_code", "quantity_unit"]
    ).rename({"hs_code": "seg8", "quantity_unit": "seg_unit"})
    seg6 = cat.filter(pl.col("hs_level").cast(pl.String) == "6").select(
        ["product_key", "hs_parent_code", "quantity_unit"]
    ).rename({"hs_parent_code": "seg6", "quantity_unit": "seg_unit6"})

    single_series = pl.Series(
        "single_unit", [single_unit_map.get(pk) for pk in exp["product_key"].to_list()]
    )
    m = (
        exp.with_columns(single_series.alias("single_unit"))
        .join(seg8, left_on=["product_key", "hs_code"], right_on=["product_key", "seg8"], how="left")
        .join(seg6, left_on=["product_key", "hs_parent_code"], right_on=["product_key", "seg6"], how="left")
        .with_columns(
            pl.when(pl.col("single_unit").is_not_null())
            # 单单位产品：全部行归唯一已知单位段，金额序列连续（含 N/A/mixed 占位）
            .then(pl.col("single_unit"))
            # 混单位产品：行自身已知单位优先 → 无量占位行(N/A 等)按 catalog 兜底保持金额连续
            # → 有量但单位未知的行归 UNMAPPED（不污染已知单位段的纯度）
            .otherwise(
                pl.when(pl.col("quantity_unit_norm").is_in(KNOWN_UNITS))
                .then(pl.col("quantity_unit_norm"))
                .when(
                    pl.col("export_volume").is_null()
                    | (pl.col("export_volume") == 0)
                )
                .then(pl.coalesce([pl.col("seg_unit"), pl.col("seg_unit6")]))
                .otherwise(pl.lit(UNMAPPED_SEG))
            )
            .fill_null(UNMAPPED_SEG)
            .alias("unit_segment")
        )
        .with_columns(
            (pl.col("product_key") + "::" + pl.col("unit_segment")).alias("seg_key")
        )
    )
    n_single = len(single_unit_prods)
    n_unmapped = m.filter(pl.col("unit_segment") == UNMAPPED_SEG).height
    print(f"[拆段] 单单位产品 {n_single} 个整品不拆段; {n_unmapped} 行单位未知归入 UNMAPPED（金额计入、量价不判）")
    keep = [c for c in m.columns if c not in ("seg_unit", "seg_unit6", "seg8", "seg6", "single_unit")]
    return m.select(keep)


def _bridge_validate(exp: pl.DataFrame) -> pl.DataFrame:
    """桥接强制规则（METHODOLOGY_FINAL §6.5）：组合码披露 + L3 归属断言。

    P1-2 修复（2026-09 审计）：组合码行不再整行剔除——tio2 的 L3 850326.SI（钛白粉）
    是明确单一 L3，商品级段数据保留；组合码只在 L2 行业聚合层跳过。
    """
    # 1. L2 组合码（多映射）行统计披露（商品级保留，不剔除）
    combo = exp.filter(pl.col("target_l2_codes").str.contains(";"))
    if combo.height:
        products = sorted(combo["product_key"].unique().to_list())
        print(f"[桥接] 商品级保留 L2 组合码行 {combo.height}（产品: {products}），不参与 L2 行业聚合")

    # 2. L3 归属一致性断言：维度表 parent_code == 该行 L2 六位行业码
    runtime = DataRuntimeContext.from_root("data")
    dim = load_sw_2021_industry_dimension(
        DataCatalog(data_source="derived", runtime=runtime), level="L3",
        columns=("industry_code", "index_code", "parent_code"),
    ).rename({"index_code": "l3_ic", "industry_code": "l3c", "parent_code": "pl2"})
    dim_l2 = load_sw_2021_industry_dimension(
        DataCatalog(data_source="derived", runtime=runtime), level="L2",
        columns=("industry_code", "index_code"),
    ).rename({"index_code": "l2_ic", "industry_code": "l2c"})

    chk = (
        exp.select(["product_key", "target_l2_codes", "target_l3_codes"])
        .unique()
        .join(dim, left_on="target_l3_codes", right_on="l3_ic", how="left")
        .join(dim_l2, left_on="target_l2_codes", right_on="l2_ic", how="left")
    )
    valid = chk.filter(pl.col("pl2").is_not_null() & pl.col("l2c").is_not_null())
    bad = valid.filter(pl.col("pl2") != pl.col("l2c"))
    if bad.height:
        raise SystemExit(
            f"[桥接] L3 归属不一致 {bad.height} 行（parent_code != L2 码）:\n"
            + bad.select(["product_key", "target_l2_codes", "target_l3_codes", "pl2", "l2c"])
            .to_pandas().to_string()
        )
    print(f"[桥接] L3 归属断言通过（{valid.height} 行可校验，0 不一致）")
    return exp


def _derive(df: pl.DataFrame, key: str, all_months: list[str]) -> pl.DataFrame:
    """按 key 补全完整月序，统一重算 3MMA 金额/量/价(ASP) yoy 与驱动类型。"""
    base = pl.DataFrame({key: df[key].unique().to_list()}).join(
        pl.DataFrame({"report_month": all_months}), how="cross"
    )
    df = base.join(df, on=[key, "report_month"], how="left")

    out = (
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
            # NaN 守卫：polars 中 NaN > 0 为 true、is_null 对 NaN 为 false，
            # 不守卫会把量/价不可判(volume 不可聚合)的行误标为“量价齐升”。
            pl.when(
                pl.col("volume_yoy_3mma").is_nan() | pl.col("price_yoy_3mma").is_nan()
            )
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
    )
    # 拐点（金额 yoy 符号翻转）与二阶导（量 yoy 见顶回落）
    return out.with_columns(
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
        # 量 yoy 从 3 个月窗口高位回落（当前 < 前 3 月最大且为正）
        pl.when(
            (pl.col("volume_yoy_3mma") >= 0)
            & (pl.col("volume_yoy_3mma") < pl.col("volume_yoy_3mma").rolling_max(4, min_samples=2).shift(1).over(key))
            & (pl.col("volume_yoy_3mma").rolling_max(6, min_samples=3).over(key) > 0.1)
        )
        .then(pl.lit("量增速回落"))
        .otherwise(None)
        .alias("二阶导"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="构建商品级出口量价拐点面板")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="海关黄金事实表路径")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="面板输出路径")
    args = parser.parse_args()

    df = pl.read_parquet(args.input)
    exp = df.filter(
        pl.col("trade_direction") == "export",
        pl.col("hs_level") == "8",
    )

    # 桥接强制校验（组合码跳过 + L3 归属断言）
    exp = _bridge_validate(exp)

    # 单位归一（复用 fetcher 工具，不复制口径）
    exp = normalize_quantity_unit(exp)

    # 拆段：按 catalog 定义单位打段标（混物理单位产品拆成独立子序列）
    cat = _load_unit_segments(DEFAULT_CATALOG)
    exp = _assign_unit_segment(exp, cat)

    # 段级可加总判定（复用 fetcher 工具，product_col 换为 (product_key, unit_segment) 组合键）
    exp = flag_volume_aggregable(exp, product_col="seg_key")

    # 完整月序（2016-01 ~ 末月）
    d = exp.select(pl.col("report_month").str.to_date("%Y-%m").alias("d"))
    all_months = (
        pl.date_range(d["d"].min(), d["d"].max(), "1mo", eager=True)
        .dt.strftime("%Y-%m")
        .to_list()
    )

    # 段级月度聚合：金额全量；数量仅段内可加总（段级 volume_aggregable）
    monthly = (
        exp.group_by(["seg_key", "product_key", "unit_segment", "report_month"])
        .agg(
            pl.col("export_value_usd").sum().alias("export_value_usd"),
            pl.when(pl.col("volume_aggregable") & pl.col("export_volume").is_not_null())
            .then(pl.col("export_volume"))
            .otherwise(None)
            .sum()
            .alias("export_volume"),
            pl.col("product_name").first().alias("product_name"),
            pl.col("target_l1_code").first().alias("target_l1_code"),
            pl.col("target_l1_name").first().alias("target_l1_name"),
            pl.col("target_l2_codes").first().alias("target_l2_codes"),
            pl.col("target_l2_names").first().alias("target_l2_names"),
            pl.col("target_l3_codes").first().alias("target_l3_codes"),
            pl.col("target_l3_names").first().alias("target_l3_names"),
        )
    )

    panel = _derive(monthly, "seg_key", all_months).sort(["seg_key", "report_month"])
    panel = panel.filter(pl.col("export_value_usd").is_not_null())

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    panel.select(
        [
            "seg_key",
            "product_key",
            "unit_segment",
            "product_name",
            "report_month",
            "export_value_usd",
            "export_volume",
            "value_yoy_3mma",
            "volume_yoy_3mma",
            "price_yoy_3mma",
            "asp_3mma",
            "驱动类型",
            "拐点",
            "二阶导",
            "target_l1_code",
            "target_l1_name",
            "target_l2_codes",
            "target_l2_names",
            "target_l3_codes",
            "target_l3_names",
        ]
    ).write_parquet(out)

    # 汇总
    latest = panel.filter(pl.col("report_month") == panel["report_month"].max())
    n_seg = panel["seg_key"].n_unique()
    n_prod = panel["product_key"].n_unique()
    print(f"产品数: {n_prod}（拆段后段数 {n_seg}）  月份: {panel['report_month'].min()} ~ {panel['report_month'].max()}")
    print(f"最新月 {panel['report_month'].max()} 驱动类型分布:")
    print(latest.group_by("驱动类型").len().sort("len", descending=True).to_pandas().to_string(index=False))
    print(f"最新月拐点: {latest.filter(pl.col('拐点').is_not_null()).select(['seg_key','拐点']).height} 个")
    print(f"最新月二阶导(量增速回落): {latest.filter(pl.col('二阶导').is_not_null()).select(['seg_key']).height} 个")
    print(f"已写出: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
