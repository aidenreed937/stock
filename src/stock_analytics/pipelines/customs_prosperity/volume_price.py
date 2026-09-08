"""L2/L3 行业出口量价分解月度面板（金额/数量/价格三 yoy 分解 + 驱动类型）。

口径来自 METHODOLOGY_FINAL §2.2（四象限驱动）与 §7.5（伪影量价置空）：
- 单位归一（复用 fetcher ``volume_price`` 工具，不复制口径）；
- 数量仅"可加总产品"聚合（真混用单位产品数量置空，金额照常）；
- hydrogen_electrolyzer 伪影（价 +1443%/量 -88%）在行业聚合层量价置空；
- L2 组合码行跳过（§6.5 规则 4），L3 保留对应单一 L3（钛白粉 850326.SI）。

产物路径与既有脚本契约一致：``data/analytics/industry/customs_l2_volume_price_monthly.parquet``。
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from stock_analytics.pipelines.customs_prosperity.config import VOLUME_PRICE_FILE
from stock_data.fetcher.industry.customs.transforms.volume_price import (
    flag_volume_aggregable,
    normalize_quantity_unit,
)

DEFAULT_INPUT = Path("data/curated/industry/customs_trade.parquet")
DEFAULT_OUTPUT = Path("data/analytics/industry") / VOLUME_PRICE_FILE


def build_volume_price_panel(
    customs_trade: pl.DataFrame,
    *,
    skip_l2: frozenset[str] = frozenset({"801033.SI;801034.SI"}),
    skip_vp: frozenset[str] = frozenset({"hydrogen_electrolyzer"}),
) -> pl.DataFrame:
    """构建 L2/L3 行业出口量价分解月度面板。

    Args:
        customs_trade: 海关黄金事实表（``customs_trade.parquet``）。
        skip_l2: L2 聚合跳过的组合码。
        skip_vp: 行业聚合层量价置空的伪影产品（§7.5）。

    Returns:
        L2/L3 合并长表面板（粒度 L2/L3），含 value/volume/price yoy 与驱动类型。
    """
    exp = customs_trade.filter(
        pl.col("trade_direction") == "export",
        pl.col("hs_level") == "8",
    )

    # 1. 单位归一 + 产品级可加总判定
    exp = normalize_quantity_unit(exp)
    exp = flag_volume_aggregable(exp)
    exp = exp.with_columns(
        pl.when(pl.col("product_key").is_in(skip_vp))
        .then(None)
        .otherwise(pl.col("export_volume"))
        .alias("export_volume")
    )

    # 2. 月度聚合：金额全量，数量仅可加总产品（L2 与 L3 双层）
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
            # 不守卫会把量/价不可判(volume 不可聚合)的行误标为"量价齐升"。
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

    # L2 层（code = 六位 industry_code）：组合码组在 L2 聚合后跳过（§6.5 规则 4）
    monthly_l2 = _agg_level(["target_l2_codes"]).rename({"target_l2_codes": "code"})
    monthly_l2 = monthly_l2.filter(pl.col("code").is_in(skip_l2).not_())
    l2_panel = _derive_level(monthly_l2, "code").with_columns(pl.lit("L2").alias("粒度"))

    # L3 层（code = l3 index code, 850xxx.SI 格式）：组合码产品的单一 L3（如钛白粉
    # 850326.SI）保留，不做层级过滤
    monthly_l3 = _agg_level(["target_l3_codes"]).rename({"target_l3_codes": "code"})
    l3_panel = _derive_level(monthly_l3, "code").with_columns(pl.lit("L3").alias("粒度"))

    m = pl.concat([l2_panel, l3_panel], how="vertical").sort(["粒度", "code", "m"])

    return m.select(
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
    )


def save_volume_price_panel(panel: pl.DataFrame, output_dir: Path | str) -> Path:
    """落盘量价分解面板（保持既有契约路径与文件名）。"""
    out = Path(output_dir) / VOLUME_PRICE_FILE
    out.parent.mkdir(parents=True, exist_ok=True)
    panel.write_parquet(out)
    return out


__all__ = [
    "DEFAULT_INPUT",
    "DEFAULT_OUTPUT",
    "build_volume_price_panel",
    "save_volume_price_panel",
]
