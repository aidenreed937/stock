#!/usr/bin/env python3
"""构建海关出口景气月度面板（Comtrade 8 位子目 × GACC 同码拼接统一重算）。

数据基础: data/curated/industry/customs_trade.parquet（合并黄金事实表）。
逻辑:
  1. 取出口方向、8 位子目、且 Comtrade 与 GACC 两段都观测到的"可拼接码"（h8 桥接集）；
  2. 按 (hs_code, report_month) 聚合月度出口金额，得到跨源连续序列；
  3. 在拼接后的连续序列上统一重算 3MMA / YoY(12 月) / MoM(1 月)——
     修复分源计算导致的 GACC 段 2025 全年无同比问题（此前需 2026 才有基数）；
  4. 聚合到申万 L3 / L2 行业层，同样重算 3MMA / YoY / MoM；
  5. 输出单一长表面板（granularity 标识 hs8 / l3 / l2）。

用法:
    uv run python scripts/build_customs_export_prosperity.py
    uv run python scripts/build_customs_export_prosperity.py --output data/analytics/industry/customs_export_prosperity_panel.parquet
"""

from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl

DEFAULT_INPUT = Path("data/curated/industry/customs_trade.parquet")
DEFAULT_OUTPUT = Path("data/analytics/industry/customs_export_prosperity_panel.parquet")


def _derive(df: pl.DataFrame, key: str) -> pl.DataFrame:
    """在按月连续序列上计算 3MMA / YoY(12) / MoM(1)，口径与 transform.py 一致。"""
    return (
        df.sort([key, "report_month"])
        .with_columns(
            pl.col("export_value_usd")
            .rolling_mean(window_size=3, min_samples=1)
            .over(key)
            .alias("export_value_3mma")
        )
        .with_columns(
            pl.when(pl.col("export_value_3mma").shift(12).over(key) > 0)
            .then(
                (pl.col("export_value_3mma") - pl.col("export_value_3mma").shift(12).over(key))
                / pl.col("export_value_3mma").shift(12).over(key)
            )
            .otherwise(None)
            .alias("yoy_growth_3mma"),
            pl.when(pl.col("export_value_3mma").shift(1).over(key) > 0)
            .then(
                (pl.col("export_value_3mma") - pl.col("export_value_3mma").shift(1).over(key))
                / pl.col("export_value_3mma").shift(1).over(key)
            )
            .otherwise(None)
            .alias("mom_growth_3mma"),
        )
    )


def _complete_months(df: pl.DataFrame, key: str, all_months: list[str]) -> pl.DataFrame:
    """按 key 补全完整月份序列；缺月 export_value_usd 置 null（保证 shift(12) 对位）。"""
    base = pl.DataFrame({key: df[key].unique().to_list()}).join(
        pl.DataFrame({"report_month": all_months}), how="cross"
    )
    return base.join(df, on=[key, "report_month"], how="left")


def main() -> int:
    parser = argparse.ArgumentParser(description="构建海关出口景气月度面板")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="合并黄金事实表路径")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="面板输出路径")
    args = parser.parse_args()

    df = pl.read_parquet(args.input)
    exp = df.filter(pl.col("trade_direction") == "export", pl.col("hs_level") == "8")

    ct_codes = set(exp.filter(pl.col("source") == "UN_Comtrade")["hs_code"].unique())
    g_codes = set(exp.filter(pl.col("source") == "GACC")["hs_code"].unique())
    # 拼接集合 = 跨源交集 ∪ GACC-only 码。
    # 交集码跨源 yoy 连续；GACC-only 码（如 HS2027 税则切换后的 27101913/14/24，
    # UN 段无对应旧码）也进入面板——否则税则切换会静默丢失整段商品。
    bridge = sorted(ct_codes | g_codes)
    if not bridge:
        raise SystemExit("无可拼接码（Comtrade/GACC 出口交集为空）")

    # 完整月份序列（2016-01 ~ 数据末月, 月末对齐）
    d = exp.select(pl.col("report_month").str.to_date("%Y-%m").alias("d"))
    all_months = (
        pl.date_range(d["d"].min(), d["d"].max(), "1mo", eager=True)
        .dt.strftime("%Y-%m")
        .to_list()
    )

    # 1. hs8 粒度: 月度金额聚合 + 补全月序 + 统一派生
    monthly = (
        exp.filter(pl.col("hs_code").is_in(bridge))
        .group_by(["hs_code", "report_month"])
        .agg(
            pl.col("export_value_usd").sum().alias("export_value_usd"),
            pl.col("hs_name").first().alias("hs_name"),
            pl.col("product_key").first().alias("product_key"),
            pl.col("product_name").first().alias("product_name"),
            pl.col("target_l1_code").first().alias("l1_code"),
            pl.col("target_l1_name").first().alias("l1_name"),
            pl.col("target_l2_codes").first().alias("l2_code"),
            pl.col("target_l2_names").first().alias("l2_name"),
            pl.col("target_l3_codes").first().alias("l3_code"),
            pl.col("target_l3_names").first().alias("l3_name"),
        )
    )
    monthly = _complete_months(monthly, "hs_code", all_months)
    hs8 = _derive(monthly, "hs_code").with_columns(pl.lit("hs8").alias("granularity"))

    # 2. L3 聚合（基于有观测的月度，不引入补全空月；金额缺失月不计数）
    l3 = (
        monthly.filter(pl.col("export_value_usd").is_not_null())
        .group_by(["l3_code", "l3_name", "l2_code", "l2_name", "report_month"])
        .agg(pl.col("export_value_usd").sum().alias("export_value_usd"), pl.len().cast(pl.Int32).alias("n_hs8"))
    )
    l3 = _complete_months(l3, "l3_code", all_months)
    l3 = _derive(l3, "l3_code").with_columns(pl.lit("l3").alias("granularity"))

    # 3. L2 聚合（METHODOLOGY §6.5 强制规则 4：组合码 `;` 多映射行跳过并披露）
    l2_src = monthly.filter(
        pl.col("export_value_usd").is_not_null(),
        pl.col("l2_code").str.contains(";").not_(),
    )
    n_combo = monthly.filter(
        pl.col("export_value_usd").is_not_null(),
        pl.col("l2_code").str.contains(";"),
    ).height
    if n_combo:
        combo_prods = (
            monthly.filter(pl.col("l2_code").str.contains(";"))
            .select("product_key")
            .unique()["product_key"]
            .to_list()
        )
        print(f"[桥接] 跳过 L2 组合码行 {n_combo}（产品: {sorted(combo_prods)}），不参与行业聚合")
    l2 = (
        l2_src.group_by(["l2_code", "l2_name", "report_month"])
        .agg(pl.col("export_value_usd").sum().alias("export_value_usd"), pl.len().cast(pl.Int32).alias("n_hs8"))
    )
    l2 = _complete_months(l2, "l2_code", all_months)
    l2 = _derive(l2, "l2_code").with_columns(pl.lit("l2").alias("granularity"))

    # 4. 合并输出（统一列名）
    hs8_out = hs8.select(
        pl.col("granularity"),
        pl.col("hs_code").alias("code"),
        pl.col("hs_name").alias("name"),
        pl.col("report_month"),
        pl.col("export_value_usd"),
        pl.col("export_value_3mma"),
        pl.col("yoy_growth_3mma"),
        pl.col("mom_growth_3mma"),
        pl.lit(1, pl.Int32).alias("n_hs8"),
        pl.col("product_key"),
        pl.col("product_name"),
        pl.col("l1_code"),
        pl.col("l1_name"),
        pl.col("l2_code"),
        pl.col("l2_name"),
        pl.col("l3_code"),
        pl.col("l3_name"),
    )
    l3_out = l3.select(
        pl.col("granularity"),
        pl.col("l3_code").alias("code"),
        pl.col("l3_name").alias("name"),
        pl.col("report_month"),
        pl.col("export_value_usd"),
        pl.col("export_value_3mma"),
        pl.col("yoy_growth_3mma"),
        pl.col("mom_growth_3mma"),
        pl.col("n_hs8"),
        pl.lit(None, pl.String).alias("product_key"),
        pl.lit(None, pl.String).alias("product_name"),
        pl.lit(None, pl.String).alias("l1_code"),
        pl.lit(None, pl.String).alias("l1_name"),
        pl.col("l2_code").alias("l2_code"),
        pl.col("l2_name").alias("l2_name"),
        pl.col("l3_code").alias("l3_code"),
        pl.col("l3_name").alias("l3_name"),
    )
    l2_out = l2.select(
        pl.col("granularity"),
        pl.col("l2_code").alias("code"),
        pl.col("l2_name").alias("name"),
        pl.col("report_month"),
        pl.col("export_value_usd"),
        pl.col("export_value_3mma"),
        pl.col("yoy_growth_3mma"),
        pl.col("mom_growth_3mma"),
        pl.col("n_hs8"),
        pl.lit(None, pl.String).alias("product_key"),
        pl.lit(None, pl.String).alias("product_name"),
        pl.lit(None, pl.String).alias("l1_code"),
        pl.lit(None, pl.String).alias("l1_name"),
        pl.col("l2_code").alias("l2_code"),
        pl.col("l2_name").alias("l2_name"),
        pl.lit(None, pl.String).alias("l3_code"),
        pl.lit(None, pl.String).alias("l3_name"),
    )
    panel = pl.concat([hs8_out, l3_out, l2_out], how="vertical").sort(
        ["granularity", "code", "report_month"]
    )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    panel.write_parquet(out)

    # 汇总报告
    n_hs8 = hs8["hs_code"].n_unique()
    n_l3 = l3["l3_code"].n_unique()
    n_l2 = l2["l2_code"].n_unique()
    yoy_total = panel.filter(pl.col("granularity") == "l2", pl.col("yoy_growth_3mma").is_not_null()).height
    l2_rows = panel.filter(pl.col("granularity") == "l2").height
    # GACC 段（2025 起）L2 同比覆盖率
    gacc_l2 = panel.filter(
        pl.col("granularity") == "l2", pl.col("report_month") >= "2025-01"
    )
    gacc_yoy = gacc_l2.filter(pl.col("yoy_growth_3mma").is_not_null()).height
    print(f"可拼接 hs8 码: {n_hs8}  L3 行业: {n_l3}  L2 行业: {n_l2}")
    print(f"面板总行数: {panel.height}")
    print(f"L2 层同比覆盖: {yoy_total}/{l2_rows} 行; GACC 段(2025起)同比覆盖: {gacc_yoy}/{gacc_l2.height}")
    print(f"接口: {df['report_month'].min()} ~ {df['report_month'].max()}")
    print(f"已写出: {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
