"""商品级（product_key × unit_segment 粒度）出口量价拐点面板。

口径来自 METHODOLOGY_FINAL §2.3（拐点/二阶导）、§5（量价伪影）与 §6.5（桥接强制规则）：
- 研究口径只消费 GACC 官方数据（source=GACC，2018-01 起）；底层
  customs_trade_gacc.parquet 为纯 GACC（2026-10 起不再驻留 UN 桥接行，UN 数据见
  customs_trade.parquet）；research_sources 过滤保留为防御性；
- 单位归一并按 catalog 定义拆段（混物理单位产品拆成独立子序列）；
- 段级可加总判定（复用 fetcher ``volume_price`` 工具，product_col 换为 seg_key）；
- 桥接校验：L2 组合码行披露保留（不剔除）、L3 归属断言（parent_code == L2 码）；
- 拐点（金额 yoy 符号翻转）与二阶导（量 yoy 见顶回落）在段级序列上判定。

产物路径与既有脚本契约一致：``data/analytics/industry/customs_product_volume_price.parquet``。
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from stock_analytics.pipelines.customs_prosperity.config import (
    PRODUCT_PANEL_FILE,
    RESEARCH_SOURCES,
)
from stock_data.catalog import DataCatalog
from stock_data.catalog.sw_industry_golden import load_sw_2021_industry_dimension
from stock_data.core.runtime import DataRuntimeContext
from stock_data.fetcher.industry.customs.transforms.volume_price import (
    KNOWN_UNITS,
    flag_volume_aggregable,
    normalize_quantity_unit,
)

DEFAULT_INPUT = Path("data/curated/industry/customs_trade_gacc.parquet")
DEFAULT_CATALOG = Path("config/data/customs/good_h8_codes.csv")
DEFAULT_OUTPUT = Path("data/analytics/industry") / PRODUCT_PANEL_FILE

UNMAPPED_SEG = "UNMAPPED"  # 不在 catalog 的 hs 码段（如 pcb 85340000 残行）


def load_unit_segments(catalog_path: Path) -> pl.DataFrame:
    """从 catalog 构建 (product_key, hs_code/hs_parent_code → 定义单位) 段表。

    只取 6/8 位数字编码行（水产品等 5 位编码行被 polars 读作 Int64 丢失前导 0，
    绕过 load_hs_catalog_rows 的严格校验，且渔业本身单单位不影响分段）。
    """
    cat = (
        pl.read_csv(catalog_path)
        .select(["product_key", "hs_code", "hs_level", "hs_parent_code", "quantity_unit"])
        .with_columns(pl.col("hs_code").cast(pl.String), pl.col("hs_parent_code").cast(pl.String))
    )
    return cat.filter(pl.col("hs_code").str.len_chars().is_in([6, 8]))


def assign_unit_segment(exp: pl.DataFrame, cat: pl.DataFrame) -> pl.DataFrame:
    """按行自身单位 + catalog 定义为每行打段标，(product_key, unit_segment) 粒度。

    分段规则（METHODOLOGY_FINAL §2 量价关系优先扩展）：
    - 单单位产品不拆段：有量行单位唯一且已知 → 全部行归该单位段，金额全量、序列连续；
    - 混单位产品按行单位拆段：各自单单位可加总，不再整产品置空数量；
    - 段标优先级：① 行自身已知单位 → ② catalog 8 位精确 → ③ catalog 6 位父码 →
      ④ 仍未知归 UNMAPPED（金额照算、量价不判）。
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
    single_unit_map = dict(zip(single["product_key"].to_list(), single["_unit"].to_list()))

    seg8 = (
        cat.filter(pl.col("hs_level").cast(pl.String) == "8")
        .select(["product_key", "hs_code", "quantity_unit"])
        .rename({"hs_code": "seg8", "quantity_unit": "seg_unit"})
    )
    seg6 = (
        cat.filter(pl.col("hs_level").cast(pl.String) == "6")
        .select(["product_key", "hs_parent_code", "quantity_unit"])
        .rename({"hs_parent_code": "seg6", "quantity_unit": "seg_unit6"})
    )

    single_series = pl.Series(
        "single_unit", [single_unit_map.get(pk) for pk in exp["product_key"].to_list()]
    )
    m = (
        exp.with_columns(single_series.alias("single_unit"))
        .join(
            seg8, left_on=["product_key", "hs_code"], right_on=["product_key", "seg8"], how="left"
        )
        .join(
            seg6,
            left_on=["product_key", "hs_parent_code"],
            right_on=["product_key", "seg6"],
            how="left",
        )
        .with_columns(
            pl.when(pl.col("single_unit").is_not_null())
            # 单单位产品：全部行归唯一已知单位段，金额序列连续（含 N/A/mixed 占位）
            .then(pl.col("single_unit"))
            # 混单位产品：行自身已知单位优先 → 无量占位行按 catalog 兜底保持金额连续
            # → 有量但单位未知的行归 UNMAPPED（不污染已知单位段的纯度）
            .otherwise(
                pl.when(pl.col("quantity_unit_norm").is_in(KNOWN_UNITS))
                .then(pl.col("quantity_unit_norm"))
                .when(pl.col("export_volume").is_null() | (pl.col("export_volume") == 0))
                .then(pl.coalesce([pl.col("seg_unit"), pl.col("seg_unit6")]))
                .otherwise(pl.lit(UNMAPPED_SEG))
            )
            .fill_null(UNMAPPED_SEG)
            .alias("unit_segment")
        )
        .with_columns((pl.col("product_key") + "::" + pl.col("unit_segment")).alias("seg_key"))
    )
    keep = [
        c for c in m.columns if c not in ("seg_unit", "seg_unit6", "seg8", "seg6", "single_unit")
    ]
    return m.select(keep)


def validate_bridge(exp: pl.DataFrame, storage_dir: Path | str = "data") -> pl.DataFrame:
    """桥接强制规则（METHODOLOGY_FINAL §6.5）：组合码披露 + L3 归属断言。

    组合码行在商品级保留（tio2 的 L3 850326.SI 是明确单一 L3），只在 L2 行业聚合层跳过。
    """
    # 1. L3 归属一致性断言：维度表 parent_code == 该行 L2 六位行业码
    runtime = DataRuntimeContext.from_root(storage_dir)
    dim = load_sw_2021_industry_dimension(
        DataCatalog(data_source="derived", runtime=runtime),
        level="L3",
        columns=("industry_code", "index_code", "parent_code"),
    ).rename({"index_code": "l3_ic", "industry_code": "l3c", "parent_code": "pl2"})
    dim_l2 = load_sw_2021_industry_dimension(
        DataCatalog(data_source="derived", runtime=runtime),
        level="L2",
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
        raise ValueError(f"[桥接] L3 归属不一致 {bad.height} 行（parent_code != L2 码）")
    return exp


def _derive(df: pl.DataFrame, key: str, all_months: list[str]) -> pl.DataFrame:
    """按 key 补全完整月序，统一重算 3MMA 金额/量/价(ASP) yoy、驱动类型与拐点/二阶导。"""
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
    )
    # 拐点（金额 yoy 符号翻转）与二阶导（量 yoy 见顶回落）
    return out.with_columns(
        pl.when((pl.col("value_yoy_3mma").shift(1).over(key) < 0) & (pl.col("value_yoy_3mma") >= 0))
        .then(pl.lit("启动拐点"))
        .when((pl.col("value_yoy_3mma").shift(1).over(key) > 0) & (pl.col("value_yoy_3mma") <= 0))
        .then(pl.lit("见顶拐点"))
        .otherwise(None)
        .alias("拐点"),
        # 量 yoy 从 3 个月窗口高位回落（当前 < 前 3 月最大且为正）
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


def build_product_panel(
    customs_trade: pl.DataFrame,
    catalog_path: Path | str = DEFAULT_CATALOG,
    *,
    storage_dir: Path | str = "data",
    validate_bridge_flag: bool = True,
    sources: tuple[str, ...] = RESEARCH_SOURCES,
) -> pl.DataFrame:
    """构建商品级（product_key × unit_segment）出口量价拐点面板。

    Args:
        customs_trade: 海关黄金事实表（``customs_trade_gacc.parquet``）。
        catalog_path: hs 码 catalog 路径（拆段定义单位）。
        storage_dir: 数据根目录（L3 归属校验维度表读取）。
        validate_bridge_flag: 是否执行桥接校验（组合码披露 + L3 归属断言）。
        sources: 消费的 source 白名单；默认仅 GACC 官方数据。

    Returns:
        段级拐点面板（seg_key/product_key/unit_segment + 三 yoy + 驱动 + 拐点 + 二阶导）。
    """
    exp = customs_trade.filter(
        pl.col("trade_direction") == "export",
        pl.col("hs_level") == "8",
        pl.col("source").is_in(sources),
    )

    if validate_bridge_flag:
        exp = validate_bridge(exp, storage_dir=storage_dir)

    # 单位归一再拆段（复用 fetcher 工具，不复制口径）
    exp = normalize_quantity_unit(exp)
    cat = load_unit_segments(Path(catalog_path))
    exp = assign_unit_segment(exp, cat)

    # 段级可加总判定（product_col 换为 (product_key, unit_segment) 组合键）
    exp = flag_volume_aggregable(exp, product_col="seg_key")

    # 完整月序（数据起点 ~ 末月，GACC 段为 2018-01 起）
    d_series = exp.select(pl.col("report_month").str.to_date("%Y-%m").alias("d")).get_column("d")
    all_months = (
        pl.date_range(d_series.min(), d_series.max(), "1mo", eager=True)  # type: ignore[arg-type]
        .dt.strftime("%Y-%m")
        .to_list()  # type: ignore[union-attr]
    )

    # 段级月度聚合：金额全量；数量仅段内可加总（段级 volume_aggregable）
    monthly = exp.group_by(["seg_key", "product_key", "unit_segment", "report_month"]).agg(
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

    panel = _derive(monthly, "seg_key", all_months).sort(["seg_key", "report_month"])
    panel = panel.filter(pl.col("export_value_usd").is_not_null())

    return panel.select(
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
    )


def save_product_panel(panel: pl.DataFrame, output_dir: Path | str) -> Path:
    """落盘商品级拐点面板（保持既有契约路径与文件名）。"""
    out = Path(output_dir) / PRODUCT_PANEL_FILE
    out.parent.mkdir(parents=True, exist_ok=True)
    panel.write_parquet(out)
    return out


__all__ = [
    "DEFAULT_CATALOG",
    "DEFAULT_INPUT",
    "DEFAULT_OUTPUT",
    "UNMAPPED_SEG",
    "assign_unit_segment",
    "build_product_panel",
    "load_unit_segments",
    "save_product_panel",
    "validate_bridge",
]
