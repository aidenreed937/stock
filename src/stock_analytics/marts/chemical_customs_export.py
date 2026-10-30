"""化工海关出口高频映射与表观需求领域 Mart (chemical_customs_export)。

基于第一性原理与供需平衡表恒等式：
真实国内表观需求 = 实物产量 + 净进口 - 出口 - 全社会库存变动
出口依存度 (Export Dependency) = 出口量 / 实物产量
海外补库/外需景气相位 (Export Prosperity Regime) = 出口量二阶导 + 离岸均价 ASP 二阶导

核心量化指标：
1. 月度出口实物物理量 (万吨): export_volume_w_tons
2. 离岸出口均价 (美元/吨): export_asp_usd_ton = (export_value_usd / export_volume_tons)
3. 出口依存度 (%): export_dependency_pct = (export_volume_w_tons / nbs_production_w_tons) * 100
4. 终端下游拉动物理量 (万吨): 如纯碱下游平板玻璃拉动折算
5. 表观消费量 (万吨): apparent_consumption_w_tons = nbs_production_w_tons - export_volume_w_tons
6. 外需景气状态机:
   - export_boom: 量价齐升 (YoY > 10% 且 ASP YoY > 0%)，海外强补库；
   - volume_driven: 量增价跌 (YoY > 10% 且 ASP YoY <= 0%)，以价换量抢海外份额；
   - price_driven: 价涨量缩 (YoY <= 0% 且 ASP YoY > 5%)，海外供给受阻或成本推升；
   - export_contraction: 量价双弱 (YoY <= 0% 且 ASP YoY <= 0%)，海外需求萎缩。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import polars as pl

logger = logging.getLogger(__name__)

CHEMICAL_CUSTOMS_EXPORT_MART_NAME = "chemical_customs_export"
CHEMICAL_CUSTOMS_EXPORT_FILE = f"{CHEMICAL_CUSTOMS_EXPORT_MART_NAME}.parquet"
CHEMICAL_CUSTOMS_EXPORT_CSV = f"{CHEMICAL_CUSTOMS_EXPORT_MART_NAME}_latest.csv"

DEFAULT_GACC_PARQUET_PATH = Path("data/curated/industry/customs_trade_gacc.parquet")
DEFAULT_MARKET_PARQUET_PATH = Path("data/curated/industry/chemical_market.parquet")

COMMODITY_MAPPINGS: dict[str, dict[str, Any]] = {
    "TiO2": {
        "name": "钛白粉",
        "gacc_products": ["钛白粉"],
        "nbs_column": None,
        "default_monthly_production_w_tons": 36.0,  # 行业统计月均约 35~38 万吨
        "derived_logic": None,
    },
    "SA": {
        "name": "纯碱",
        "gacc_products": ["纯碱"],
        "nbs_column": "soda_ash_production",
        "default_monthly_production_w_tons": None,
        "derived_logic": "glass_derived",  # 平板玻璃产量 (万重量箱) * 0.05吨/箱 * 0.20吨纯碱/吨玻璃
    },
    "POY": {
        "name": "聚酯长丝",
        "gacc_products": ["聚酯长丝", "聚酯长丝机织物"],
        "nbs_column": "synthetic_fiber_production",
        "default_monthly_production_w_tons": None,
        "derived_logic": None,
    },
    "MDI": {
        "name": "聚合MDI",
        "gacc_products": ["聚合MDI"],
        "nbs_column": None,
        "default_monthly_production_w_tons": 28.0,  # 行业统计中枢约 28 万吨
        "derived_logic": None,
    },
    "SH": {
        "name": "烧碱",
        "gacc_products": ["烧碱"],
        "nbs_column": "caustic_soda_production",
        "default_monthly_production_w_tons": None,
        "derived_logic": None,
    },
    "UR": {
        "name": "尿素",
        "gacc_products": ["尿素"],
        "nbs_column": "chemical_fertilizer_production",
        "default_monthly_production_w_tons": None,
        "derived_logic": None,
    },
    "MEG": {
        "name": "乙二醇",
        "gacc_products": ["乙二醇"],
        "nbs_column": None,
        "default_monthly_production_w_tons": 160.0,
        "derived_logic": None,
    },
    "MA": {
        "name": "甲醇",
        "gacc_products": ["甲醇"],
        "nbs_column": None,
        "default_monthly_production_w_tons": 650.0,
        "derived_logic": None,
    },
    "R32": {
        "name": "制冷剂(三代氟化工)",
        "gacc_products": ["制冷剂(三代氟化工)"],
        "nbs_column": None,
        "default_monthly_production_w_tons": 6.5,
        "derived_logic": None,
    },
    "TA": {
        "name": "精对苯二甲酸",
        "gacc_products": ["精对苯二甲酸"],
        "nbs_column": None,
        "default_monthly_production_w_tons": 550.0,
        "derived_logic": None,
    },
    "V": {
        "name": "聚氯乙烯",
        "gacc_products": ["聚氯乙烯"],
        "nbs_column": None,
        "default_monthly_production_w_tons": 190.0,
        "derived_logic": None,
    },
    "EB": {
        "name": "苯乙烯",
        "gacc_products": ["苯乙烯"],
        "nbs_column": None,
        "default_monthly_production_w_tons": 150.0,
        "derived_logic": None,
    },
    "PP": {
        "name": "聚丙烯",
        "gacc_products": ["聚丙烯"],
        "nbs_column": None,
        "default_monthly_production_w_tons": 290.0,
        "derived_logic": None,
    },
    "PX": {
        "name": "对二甲苯",
        "gacc_products": ["对二甲苯"],
        "nbs_column": None,
        "default_monthly_production_w_tons": 300.0,
        "derived_logic": None,
    },
}

CHEMICAL_CUSTOMS_EXPORT_SCHEMA: dict[str, Any] = {
    "report_month": pl.Utf8,
    "trade_date": pl.Date,
    "commodity_code": pl.Utf8,
    "commodity_name": pl.Utf8,
    "export_volume_w_tons": pl.Float64,
    "export_value_m_usd": pl.Float64,
    "export_asp_usd_ton": pl.Float64,
    "export_volume_yoy_pct": pl.Float64,
    "export_volume_mom_pct": pl.Float64,
    "export_asp_yoy_pct": pl.Float64,
    "nbs_production_w_tons": pl.Float64,
    "export_dependency_pct": pl.Float64,
    "derived_terminal_demand_w_tons": pl.Float64,
    "apparent_consumption_w_tons": pl.Float64,
    "apparent_consumption_yoy_pct": pl.Float64,
    "export_regime": pl.Utf8,
}


def _classify_export_regime(volume_yoy: float | None, asp_yoy: float | None) -> str:
    """分类判定外需出口景气四象限相位。"""
    if volume_yoy is None or asp_yoy is None:
        return "neutral"
    if volume_yoy > 10.0 and asp_yoy > 0.0:
        return "export_boom"
    if volume_yoy > 10.0 and asp_yoy <= 0.0:
        return "volume_driven"
    if volume_yoy <= 0.0 and asp_yoy > 5.0:
        return "price_driven"
    if volume_yoy <= 0.0 and asp_yoy <= 0.0:
        return "export_contraction"
    return "stable"


def build_chemical_customs_export_mart(
    gacc_path: Path | str | None = None,
    market_path: Path | str | None = None,
    as_of_month: str | None = None,
    output_dir: Path | str | None = None,
) -> pl.DataFrame:
    """构建化工海关出口、外需前瞻与表观需求领域 Mart。"""
    g_path = Path(gacc_path) if gacc_path else DEFAULT_GACC_PARQUET_PATH
    m_path = Path(market_path) if market_path else DEFAULT_MARKET_PARQUET_PATH

    if not g_path.exists():
        logger.warning(f"GACC 海关出口事实表不存在: {g_path}")
        return pl.DataFrame(schema=CHEMICAL_CUSTOMS_EXPORT_SCHEMA)

    gacc_df = pl.read_parquet(g_path)
    if gacc_df.is_empty():
        return pl.DataFrame(schema=CHEMICAL_CUSTOMS_EXPORT_SCHEMA)

    # 读取 NBS 月度实物产量
    market_df = pl.read_parquet(m_path) if m_path.exists() else pl.DataFrame()

    frames: list[pl.DataFrame] = []

    for code, info in COMMODITY_MAPPINGS.items():
        c_name = info["name"]
        products = info["gacc_products"]
        nbs_col = info.get("nbs_column")
        default_prod = info.get("default_monthly_production_w_tons")
        derived_type = info.get("derived_logic")

        matched = gacc_df.filter(pl.col("product_name").is_in(products))
        if matched.is_empty():
            continue
        # 出口口径：只统计 export 行，剔除 import（防止进出口混入抬高“出口量/均价”）
        if "trade_direction" in matched.columns:
            matched = matched.filter(pl.col("trade_direction") == "export")
            if matched.is_empty():
                continue

        # 按月份聚合出口量与出口额
        monthly_agg = (
            matched.group_by("report_month")
            .agg(
                [
                    (pl.col("export_volume").sum() / 1.0e7).alias("export_volume_w_tons"),
                    (pl.col("export_value_usd").sum() / 1.0e6).alias("export_value_m_usd"),
                    pl.col("trade_date").max().alias("trade_date"),
                ]
            )
            .sort("report_month")
        )

        if as_of_month:
            monthly_agg = monthly_agg.filter(pl.col("report_month") <= as_of_month)

        # 匹配 NBS 产量
        if not market_df.is_empty() and "report_month" in market_df.columns:
            mkt_sub_cols = ["report_month"]
            if nbs_col and nbs_col in market_df.columns:
                mkt_sub_cols.append(nbs_col)
            if derived_type == "glass_derived" and "plate_glass_production" in market_df.columns:
                mkt_sub_cols.append("plate_glass_production")

            mkt_sub = market_df.select(list(set(mkt_sub_cols)))
            joined = monthly_agg.join(mkt_sub, on="report_month", how="left")
        else:
            joined = monthly_agg.with_columns(
                pl.lit(None, dtype=pl.Float64).alias(nbs_col or "dummy_prod")
            )

        # 补全产量列
        if nbs_col and nbs_col in joined.columns:
            prod_expr = pl.col(nbs_col).cast(pl.Float64)
            if default_prod:
                prod_expr = prod_expr.fill_null(float(default_prod))
        elif default_prod:
            prod_expr = pl.lit(float(default_prod), dtype=pl.Float64)
        else:
            prod_expr = pl.lit(None, dtype=pl.Float64)

        # 终端下游拉动物理量 (纯碱由平板玻璃折算)
        if derived_type == "glass_derived" and "plate_glass_production" in joined.columns:
            # plate_glass_production 为万重量箱，1重量箱=50kg=0.05吨，1吨玻璃需约0.20吨纯碱 => 系数 0.01
            derived_expr = (pl.col("plate_glass_production").cast(pl.Float64) * 0.01).round(2)
        else:
            derived_expr = pl.lit(None, dtype=pl.Float64)

        enriched = joined.with_columns(
            pl.lit(code).alias("commodity_code"),
            pl.lit(c_name).alias("commodity_name"),
            prod_expr.alias("nbs_production_w_tons"),
            derived_expr.alias("derived_terminal_demand_w_tons"),
        )

        # 计算均价与表观需求
        with_metrics = enriched.with_columns(
            ((pl.col("export_value_m_usd") / pl.col("export_volume_w_tons")) * 100.0).alias(
                "export_asp_usd_ton"
            ),
            ((pl.col("export_volume_w_tons") / pl.col("nbs_production_w_tons")) * 100.0).alias(
                "export_dependency_pct"
            ),
            (pl.col("nbs_production_w_tons") - pl.col("export_volume_w_tons")).alias(
                "apparent_consumption_w_tons"
            ),
        )

        # 计算同比与环比
        with_rates = with_metrics.with_columns(
            (
                (pl.col("export_volume_w_tons") - pl.col("export_volume_w_tons").shift(12))
                / pl.col("export_volume_w_tons").shift(12)
                * 100.0
            )
            .round(2)
            .alias("export_volume_yoy_pct"),
            (
                (pl.col("export_volume_w_tons") - pl.col("export_volume_w_tons").shift(1))
                / pl.col("export_volume_w_tons").shift(1)
                * 100.0
            )
            .round(2)
            .alias("export_volume_mom_pct"),
            (
                (pl.col("export_asp_usd_ton") - pl.col("export_asp_usd_ton").shift(12))
                / pl.col("export_asp_usd_ton").shift(12)
                * 100.0
            )
            .round(2)
            .alias("export_asp_yoy_pct"),
            (
                (
                    pl.col("apparent_consumption_w_tons")
                    - pl.col("apparent_consumption_w_tons").shift(12)
                )
                / pl.col("apparent_consumption_w_tons").shift(12)
                * 100.0
            )
            .round(2)
            .alias("apparent_consumption_yoy_pct"),
        )

        # 判定外需状态机
        regimes: list[str] = []
        for row in with_rates.to_dicts():
            r = _classify_export_regime(
                row.get("export_volume_yoy_pct"),
                row.get("export_asp_yoy_pct"),
            )
            regimes.append(r)

        final_df = with_rates.with_columns(
            pl.Series("export_regime", regimes, dtype=pl.Utf8),
            pl.col("export_volume_w_tons").round(4),
            pl.col("export_value_m_usd").round(4),
            pl.col("export_asp_usd_ton").round(2),
            pl.col("export_dependency_pct").round(2),
            pl.col("apparent_consumption_w_tons").round(4),
        ).select(list(CHEMICAL_CUSTOMS_EXPORT_SCHEMA.keys()))

        frames.append(final_df)

    if not frames:
        return pl.DataFrame(schema=CHEMICAL_CUSTOMS_EXPORT_SCHEMA)

    combined_df = pl.concat(frames).sort(["report_month", "commodity_code"])

    out_dir = Path(output_dir) if output_dir else Path("data/curated/mart")
    out_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = out_dir / CHEMICAL_CUSTOMS_EXPORT_FILE
    csv_path = out_dir / CHEMICAL_CUSTOMS_EXPORT_CSV

    combined_df.write_parquet(parquet_path)
    combined_df.write_csv(csv_path)

    logger.info(f"成功物化化工海关出口与外需前瞻 Mart: {parquet_path} ({len(combined_df)} 行)")

    return combined_df


def get_latest_chemical_export_summary(mart_df: pl.DataFrame) -> pl.DataFrame:
    """提取各品类最新报告月的出口与外需概览。"""
    if mart_df.is_empty():
        return mart_df
    return (
        mart_df.sort(["commodity_code", "report_month"], descending=[False, True])
        .group_by("commodity_code", maintain_order=True)
        .first()
    )
