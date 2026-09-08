"""海关出口金额景气月度面板（hs8/L3/L2 三层，3MMA yoy/MoM）。

口径来自 METHODOLOGY_FINAL §2（3MMA yoy 统一重算）与 §6.5（桥接强制规则）：
- 拼接集 = Comtrade ∩ GACC ∪ GACC-only（HS2027 税则切换后新码进入面板）；
- 完整月序补全后统一重算（缺月置 null，跨源不做分源分段）；
- L2 组合码（`;` 多映射行）跳过并披露（§6.5 规则 4）。

产物路径与既有脚本契约一致：``data/analytics/industry/customs_export_prosperity_panel.parquet``。
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from stock_analytics.pipelines.customs_prosperity.config import AMOUNT_PANEL_FILE

DEFAULT_INPUT = Path("data/curated/industry/customs_trade.parquet")
DEFAULT_OUTPUT = Path("data/analytics/industry") / AMOUNT_PANEL_FILE


def derive_amount_metrics(df: pl.DataFrame, key: str) -> pl.DataFrame:
    """在按月连续序列上计算 3MMA / YoY(12) / MoM(1)，口径与 transform 层一致。"""
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


def complete_months(df: pl.DataFrame, key: str, all_months: list[str]) -> pl.DataFrame:
    """按 key 补全完整月份序列；缺月 export_value_usd 置 null（保证 shift(12) 对位）。"""
    base = pl.DataFrame({key: df[key].unique().to_list()}).join(
        pl.DataFrame({"report_month": all_months}), how="cross"
    )
    return base.join(df, on=[key, "report_month"], how="left")


def build_amount_panel(
    customs_trade: pl.DataFrame,
    *,
    skip_l2: frozenset[str] = frozenset({"801033.SI;801034.SI"}),
) -> pl.DataFrame:
    """构建海关出口金额景气月度面板（hs8/L3/L2 三层合并长表）。

    Args:
        customs_trade: 海关黄金事实表（``customs_trade.parquet``）。
        skip_l2: L2 聚合跳过的组合码（METHODOLOGY §6.5 规则 4）。

    Returns:
        单长表面板，含 ``granularity``（hs8/l3/l2）与 3MMA yoy/mom 列。
    """
    exp = customs_trade.filter(
        pl.col("trade_direction") == "export",
        pl.col("hs_level") == "8",
    )

    ct_codes = set(exp.filter(pl.col("source") == "UN_Comtrade")["hs_code"].unique())
    g_codes = set(exp.filter(pl.col("source") == "GACC")["hs_code"].unique())
    # 拼接集合 = 跨源交集 ∪ GACC-only 码（税则切换后新码保留，避免静默丢段）
    bridge = sorted(ct_codes | g_codes)
    if not bridge:
        raise ValueError("无可拼接码（Comtrade/GACC 出口交集为空）")

    d_series = exp.select(pl.col("report_month").str.to_date("%Y-%m").alias("d")).get_column("d")
    all_months = (
        pl.date_range(d_series.min(), d_series.max(), "1mo", eager=True)  # type: ignore[arg-type]
        .dt.strftime("%Y-%m")
        .to_list()  # type: ignore[union-attr]
    )

    # 1. hs8 粒度：月度金额聚合 + 补全月序 + 统一派生
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
    monthly = complete_months(monthly, "hs_code", all_months)
    hs8 = derive_amount_metrics(monthly, "hs_code").with_columns(pl.lit("hs8").alias("granularity"))

    # 2. L3 聚合（仅基于有观测月度，不引入补全空月）
    l3 = (
        monthly.filter(pl.col("export_value_usd").is_not_null())
        .group_by(["l3_code", "l3_name", "l2_code", "l2_name", "report_month"])
        .agg(
            pl.col("export_value_usd").sum().alias("export_value_usd"),
            pl.len().cast(pl.Int32).alias("n_hs8"),
        )
    )
    l3 = complete_months(l3, "l3_code", all_months)
    l3 = derive_amount_metrics(l3, "l3_code").with_columns(pl.lit("l3").alias("granularity"))

    # 3. L2 聚合（组合码跳过并披露，§6.5 规则 4）
    l2_src = monthly.filter(
        pl.col("export_value_usd").is_not_null(),
        pl.col("l2_code").str.contains(";").not_(),
    )
    l2 = l2_src.group_by(["l2_code", "l2_name", "report_month"]).agg(
        pl.col("export_value_usd").sum().alias("export_value_usd"),
        pl.len().cast(pl.Int32).alias("n_hs8"),
    )
    l2 = complete_months(l2, "l2_code", all_months)
    l2 = derive_amount_metrics(l2, "l2_code").with_columns(pl.lit("l2").alias("granularity"))

    # 4. 合并输出（统一列名）
    hs8_out = _out_frame(
        hs8,
        code_col="hs_code",
        name_col="hs_name",
        product_col="product_key",
        product_name_col="product_name",
        l2_col="l2_code",
        l2_name_col="l2_name",
        l3_col="l3_code",
        l3_name_col="l3_name",
        n_hs8=1,
    )
    l3_out = _out_frame(
        l3,
        code_col="l3_code",
        name_col="l3_name",
        l2_col="l2_code",
        l2_name_col="l2_name",
        l3_col="l3_code",
        l3_name_col="l3_name",
        n_hs8_col="n_hs8",
    )
    l2_out = _out_frame(
        l2,
        code_col="l2_code",
        name_col="l2_name",
        l2_col="l2_code",
        l2_name_col="l2_name",
        n_hs8_col="n_hs8",
    )
    return pl.concat([hs8_out, l3_out, l2_out], how="vertical").sort(
        ["granularity", "code", "report_month"]
    )


def _out_frame(
    df: pl.DataFrame,
    *,
    code_col: str,
    name_col: str,
    product_col: str | None = None,
    product_name_col: str | None = None,
    l2_col: str,
    l2_name_col: str,
    l3_col: str | None = None,
    l3_name_col: str | None = None,
    n_hs8: int | None = None,
    n_hs8_col: str | None = None,
) -> pl.DataFrame:
    """统一输出列形态（granularity/code/name/report_month/指标/n_hs8/映射列）。"""
    return df.select(
        pl.col("granularity"),
        pl.col(code_col).alias("code"),
        pl.col(name_col).alias("name"),
        pl.col("report_month"),
        pl.col("export_value_usd"),
        pl.col("export_value_3mma"),
        pl.col("yoy_growth_3mma"),
        pl.col("mom_growth_3mma"),
        pl.lit(n_hs8, pl.Int32).alias("n_hs8")
        if n_hs8 is not None
        else pl.col(n_hs8_col or "n_hs8"),
        pl.lit(None, pl.String).alias("product_key")
        if product_col is None
        else pl.col(product_col),
        (
            pl.lit(None, pl.String).alias("product_name")
            if product_name_col is None
            else pl.col(product_name_col)
        ),
        pl.lit(None, pl.String).alias("l1_code"),
        pl.lit(None, pl.String).alias("l1_name"),
        pl.col(l2_col),
        pl.col(l2_name_col),
        pl.lit(None, pl.String).alias("l3_code") if l3_col is None else pl.col(l3_col),
        pl.lit(None, pl.String).alias("l3_name") if l3_name_col is None else pl.col(l3_name_col),
    )


def save_amount_panel(panel: pl.DataFrame, output_dir: Path | str) -> Path:
    """落盘金额面板（保持既有契约路径与文件名）。"""
    out = Path(output_dir) / AMOUNT_PANEL_FILE
    out.parent.mkdir(parents=True, exist_ok=True)
    panel.write_parquet(out)
    return out


__all__ = [
    "DEFAULT_INPUT",
    "DEFAULT_OUTPUT",
    "build_amount_panel",
    "complete_months",
    "derive_amount_metrics",
    "save_amount_panel",
]
