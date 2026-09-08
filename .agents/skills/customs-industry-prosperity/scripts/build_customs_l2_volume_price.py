#!/usr/bin/env python3
"""构建 L2/L3 行业出口量价分解月度面板（金额/数量/价格三 yoy 分解）。

数据基础: data/curated/industry/customs_trade.parquet（合并黄金事实表，export + hs8）。
逻辑:
  1. 单位归一（含 UN Comtrade 计量单位代码 u/l/m²/条，见 volume_price.UNIT_CANONICAL）；
  2. 产品级"数量可加总"判定（有量行单单位且已知，0 量占位不计；
     真混用产品如半导体设备/轮胎/PCB 数量置空）；
  3. L2 月度聚合: 金额=全量求和；数量=仅可加总产品求和；
  4. 3MMA yoy 分解: v_yoy(金额) ≈ q_yoy(数量) + p_yoy(价格/ASP)；
  5. 驱动类型分类: 量价齐升(量>0 价>0) / 量驱动(量>0 价≤0) / 价驱动(量≤0 价>0) / 双弱。

用法:
    uv run python scripts/build_customs_l2_volume_price.py
    uv run python scripts/build_customs_l2_volume_price.py --output data/analytics/industry/customs_l2_volume_price_monthly.parquet
"""

from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.customs.transforms.volume_price import (
    flag_volume_aggregable,
    normalize_quantity_unit,
)

DEFAULT_INPUT = Path("data/curated/industry/customs_trade.parquet")
DEFAULT_OUTPUT = Path("data/analytics/industry/customs_l2_volume_price_monthly.parquet")

# 需经行业映射: 出口面板 l2 码(801081.SI) -> 申万六位 industry_code(270100)。
# SKIP_L2 仅作用于 L2 聚合层（组合码行无法归入单一 L2）；L3 层钛白粉
# （850326.SI，单一明确 L3）不受影响，见 `_agg_level` 后处理。
SKIP_L2 = {"801033.SI;801034.SI"}  # 化学原料;化学制品 多映射行

# METHODOLOGY §7.5 量价伪影：hydrogen_electrolyzer 单代码 ASP 伪影（价 +1443%、量 -88%）。
# 行业聚合层（L2/L3）量价置空、仅金额参与；商品级面板保留原始量价供诊断。
SKIP_VP = {"hydrogen_electrolyzer"}


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 L2/L3 行业出口量价分解月度面板")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="合并黄金事实表路径")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="面板输出路径")
    args = parser.parse_args()

    df = pl.read_parquet(args.input)
    # 组合码行保留到聚合层再按层级处理（P1-2 修复：L3 钛白粉 850326.SI 需保留）
    exp = df.filter(
        pl.col("trade_direction") == "export",
        pl.col("hs_level") == "8",
    )

    # 1. 单位归一（含 Comtrade 代码）+ 产品级可加总判定
    exp = normalize_quantity_unit(exp)
    exp = flag_volume_aggregable(exp)
    # §7.5 量价伪影排除：该产品为 801733.SI/857336.SI 的唯一映射产品，
    # 聚合层置空其量后，行业 volume_yoy/price_yoy/驱动类型 即判为不可用（None）。
    n_skip = exp.filter(pl.col("product_key").is_in(SKIP_VP)).height
    if n_skip:
        print(f"[量价排除] §7.5 伪影产品 {sorted(SKIP_VP)} {n_skip} 行量价在行业聚合层置空（金额保留）")
    exp = exp.with_columns(
        pl.when(pl.col("product_key").is_in(SKIP_VP))
        .then(None)
        .otherwise(pl.col("export_volume"))
        .alias("export_volume")
    )

    # 2. 月度聚合: 金额全量, 数量仅可加总产品（L2 与 L3 双层）
    def _agg_level(group_cols: list[str]) -> pl.DataFrame:
        name_col = "target_l3_names" if "target_l3_codes" in group_cols else "target_l2_names"
        return (
            exp.group_by(group_cols + ["report_month"])
            .agg(
                pl.col("export_value_usd").sum().alias("export_value_usd"),
                pl.when(pl.col("volume_aggregable") & pl.col("export_volume").is_not_null())
                .then(pl.col("export_volume"))
                .otherwise(None)
                .sum()
                .alias("export_volume"),
                pl.col(name_col).first().alias("name"),
            )
            .with_columns(pl.col("report_month").str.to_date("%Y-%m").alias("m"))
            .sort(group_cols + ["m"])
        )

    def _derive_level(monthly: pl.DataFrame, code_col: str) -> pl.DataFrame:
        m = monthly.with_columns(
            pl.col("export_value_usd").rolling_mean(3, min_samples=3).over(code_col).alias("v3"),
            pl.col("export_volume").rolling_mean(3, min_samples=3).over(code_col).alias("q3"),
        )
        m = m.with_columns(
            (pl.col("v3") / pl.col("v3").shift(12).over(code_col) - 1).alias("value_yoy_3mma"),
            (pl.col("q3") / pl.col("q3").shift(12).over(code_col) - 1).alias("volume_yoy_3mma"),
            (pl.col("v3") / pl.col("q3")).alias("asp_3mma"),
        )
        m = m.with_columns(
            (pl.col("asp_3mma") / pl.col("asp_3mma").shift(12).over(code_col) - 1).alias(
                "price_yoy_3mma"
            )
        )
        return m.with_columns(
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

    # L2 层（code = 六位 industry_code）：组合码组在 L2 聚合后跳过（§6.5 组合码规则）
    monthly_l2 = _agg_level(["target_l2_codes"]).rename({"target_l2_codes": "code"})
    n_combo = monthly_l2.filter(pl.col("code").is_in(SKIP_L2)).height
    if n_combo:
        combo_prods = (
            monthly_l2.filter(pl.col("code").is_in(SKIP_L2))
            .select("name")
            .unique()["name"]
            .to_list()
        )
        print(f"[桥接] L2 聚合跳过组合码组 {n_combo} 月度行（{combo_prods}），L3 层已保留对应单一 L3")
    monthly_l2 = monthly_l2.filter(pl.col("code").is_in(SKIP_L2).not_())
    l2_panel = _derive_level(monthly_l2, "code").with_columns(pl.lit("L2").alias("粒度"))

    # L3 层（code = l3 index code, 850xxx.SI 格式）：组合码产品的单一 L3（如钛白粉
    # 850326.SI）保留，不做层级过滤
    monthly_l3 = _agg_level(["target_l3_codes"]).rename({"target_l3_codes": "code"})
    l3_panel = _derive_level(monthly_l3, "code").with_columns(pl.lit("L3").alias("粒度"))

    m = pl.concat([l2_panel, l3_panel], how="vertical").sort(["粒度", "code", "m"])

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    m.select(
        [
            "粒度",
            "code",
            "name",
            "report_month",
            "export_value_usd",
            "export_volume",
            "value_yoy_3mma",
            "volume_yoy_3mma",
            "price_yoy_3mma",
            "asp_3mma",
            "驱动类型",
        ]
    ).write_parquet(out)

    # 汇总报告
    for g in ["L2", "L3"]:
        sub = m.filter(pl.col("粒度") == g)
        latest = sub.filter(pl.col("report_month") == sub["report_month"].max()).sort(
            "value_yoy_3mma", descending=True
        )
        print(f"\n== {g} 最新月 {sub['report_month'].max()} 驱动类型分布 ==")
        print(latest.group_by("驱动类型").len().sort("len", descending=True).to_pandas().to_string(index=False))
        print(f"{g} 行业数: {sub['code'].n_unique()}")
    print(f"月份范围: {m['report_month'].min()} ~ {m['report_month'].max()}")
    print(f"\n已写出: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
