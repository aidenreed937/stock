"""申万行业资本开支与库存先导特征的自底向上聚合与面板构建。

通过自底向上汇总全市场个股的资产负债表与现金流量表事实：
- 在建工程 (CIP) 同比与固定资产 (FA) 同比：朱格拉周期先导与达产确认；
- 在建/固资比 (CIP/FA Ratio)：潜在产能投放强度；
- 资本开支 TTM 同比 (Capex Growth TTM)：真实购建长期资产现金流扩张斜率；
- 供需/库存剪刀差 (Inventory Scissors)：营收增速与存货增速剪刀差。
"""

from __future__ import annotations

import warnings
from datetime import date
from typing import TYPE_CHECKING, Any

import polars as pl

from stock_analytics.catalog_compat import load_dataset_compat
from stock_analytics.marts.shared.industry_structure.industry_mapping import (
    load_industry_l1_maps,
    prepare_stock_industry_members,
)
from stock_data.pipeline.sw_industry_golden import load_sw_2021_industry_members

if TYPE_CHECKING:
    from stock_core.config.analytics_industry_structure import IndustryStructureConfig
    from stock_core.contracts import MarketDataCatalog

INDUSTRY_CAPEX_SCHEMA: dict[str, Any] = {
    "industry_code": pl.Utf8,
    "eff_date": pl.Date,
    "cip_yoy": pl.Float64,
    "fix_assets_yoy": pl.Float64,
    "cip_to_fa_ratio": pl.Float64,
    "capex_growth_ttm": pl.Float64,
    "inventory_growth_ttm": pl.Float64,
    "inventory_scissors": pl.Float64,
}


def empty_industry_capex_frame() -> pl.DataFrame:
    """返回稳定 Schema 的空行业资本开支事实帧。"""
    return pl.DataFrame(schema=INDUSTRY_CAPEX_SCHEMA)


def _load_dataset(
    catalog: MarketDataCatalog,
    dataset: str,
    *,
    columns: list[str] | None = None,
) -> pl.DataFrame:
    try:
        return load_dataset_compat(catalog, dataset, columns=columns)
    except Exception:
        return pl.DataFrame()


def _safe_growth_expr(curr: pl.Expr, prev: pl.Expr) -> pl.Expr:
    """安全计算同比增速，除数为零或非正时返回 None。"""
    return (
        pl.when((prev.is_not_null()) & (prev > 0.0) & (curr.is_not_null()))
        .then((curr - prev) / prev * 100.0)
        .otherwise(None)
    )


def _safe_ratio_expr(num: pl.Expr, den: pl.Expr) -> pl.Expr:
    """安全计算比率，分母为零或非正时返回 None。"""
    return (
        pl.when((den.is_not_null()) & (den > 0.0) & (num.is_not_null()))
        .then(num / den)
        .otherwise(None)
    )


def _same_sample_yoy_expr(
    curr_common_col: str,
    prev_common_col: str,
    common_stocks_col: str,
    total_stocks_col: str = "total_stocks",
    min_common_stocks: int = 2,
    min_common_ratio: float = 0.40,
) -> pl.Expr:
    """计算同口径可比样本同比增速，当共同样本不足或覆盖率不足时返回 None。"""
    return (
        pl.when(
            (pl.col(common_stocks_col) >= min_common_stocks)
            & (pl.col(common_stocks_col) / pl.col(total_stocks_col) >= min_common_ratio)
            & (pl.col(prev_common_col) > 0.0)
            & (pl.col(curr_common_col).is_not_null())
        )
        .then((pl.col(curr_common_col) - pl.col(prev_common_col)) / pl.col(prev_common_col) * 100.0)
        .otherwise(None)
    )


def _derive_quarterly_flow(col_name: str) -> pl.Expr:
    """由累计季报流式数据恢复单季度发生额。"""
    prev = pl.col(col_name).shift(1).over("stock_key")
    diff = pl.col(col_name) - prev
    return (
        pl.when(pl.col("end_date").dt.month() == 3)
        .then(pl.col(col_name))
        .otherwise(pl.when(pl.col(col_name) >= prev).then(diff).otherwise(pl.col(col_name)))
    )


def _build_aggregated_financial_metrics(
    stock_fs: pl.DataFrame,
    stock_industry_map: pl.DataFrame,
) -> pl.DataFrame:
    """把个股财报与行业映射内连接并执行同口径可比样本总计法汇总。"""
    if stock_fs.is_empty() or stock_industry_map.is_empty():
        return empty_industry_capex_frame()

    joined = stock_fs.join(stock_industry_map, on="stock_key", how="inner").sort(
        ["stock_key", "end_date"]
    )
    if joined.is_empty():
        return empty_industry_capex_frame()

    # 1. 单股单季数值恢复与 TTM 滚动求和
    stock_metrics = joined.with_columns(
        _derive_quarterly_flow("c_pay_acq_const_fiolta").alias("capex_q"),
        _derive_quarterly_flow("total_revenue").alias("revenue_q"),
    ).with_columns(
        pl.col("capex_q")
        .rolling_sum(window_size=4, min_samples=4)
        .over("stock_key")
        .alias("capex_ttm"),
        pl.col("revenue_q")
        .rolling_sum(window_size=4, min_samples=4)
        .over("stock_key")
        .alias("revenue_ttm"),
    )

    # 2. 1Y 错位自连接以对齐同期共同样本 (Same-Sample Matching)
    stock_prev = stock_metrics.select(
        [
            "stock_key",
            pl.col("end_date").dt.offset_by("1y").alias("end_date"),
            pl.col("cip").alias("prev_cip"),
            pl.col("fix_assets").alias("prev_fix_assets"),
            pl.col("inventories").alias("prev_inventories"),
            pl.col("capex_ttm").alias("prev_capex_ttm"),
            pl.col("revenue_ttm").alias("prev_revenue_ttm"),
        ]
    )
    paired = stock_metrics.join(stock_prev, on=["stock_key", "end_date"], how="left")

    # 3. 按报告期与行业聚合共同样本
    agg = (
        paired.group_by(["end_date", "industry_code"])
        .agg(
            [
                pl.col("stock_key").n_unique().alias("total_stocks"),
                pl.col("cip").fill_null(0.0).sum().alias("cip"),
                pl.col("fix_assets").fill_null(0.0).sum().alias("fix_assets"),
                pl.col("ann_date").quantile(0.8).alias("eff_date"),
                # CIP 同口径
                pl.col("prev_cip").is_not_null().sum().alias("cip_common_stocks"),
                pl.col("cip")
                .filter(pl.col("prev_cip").is_not_null())
                .fill_null(0.0)
                .sum()
                .alias("curr_common_cip"),
                pl.col("prev_cip").fill_null(0.0).sum().alias("prev_common_cip"),
                # 固定资产同口径
                pl.col("prev_fix_assets").is_not_null().sum().alias("fa_common_stocks"),
                pl.col("fix_assets")
                .filter(pl.col("prev_fix_assets").is_not_null())
                .fill_null(0.0)
                .sum()
                .alias("curr_common_fa"),
                pl.col("prev_fix_assets").fill_null(0.0).sum().alias("prev_common_fa"),
                # 存货同口径
                pl.col("prev_inventories").is_not_null().sum().alias("inv_common_stocks"),
                pl.col("inventories")
                .filter(pl.col("prev_inventories").is_not_null())
                .fill_null(0.0)
                .sum()
                .alias("curr_common_inv"),
                pl.col("prev_inventories").fill_null(0.0).sum().alias("prev_common_inv"),
                # Capex TTM 同口径
                pl.col("prev_capex_ttm").is_not_null().sum().alias("capex_common_stocks"),
                pl.col("capex_ttm")
                .filter(pl.col("prev_capex_ttm").is_not_null())
                .fill_null(0.0)
                .sum()
                .alias("curr_common_capex"),
                pl.col("prev_capex_ttm").fill_null(0.0).sum().alias("prev_common_capex"),
                # 营收 TTM 同口径
                pl.col("prev_revenue_ttm").is_not_null().sum().alias("rev_common_stocks"),
                pl.col("revenue_ttm")
                .filter(pl.col("prev_revenue_ttm").is_not_null())
                .fill_null(0.0)
                .sum()
                .alias("curr_common_rev"),
                pl.col("prev_revenue_ttm").fill_null(0.0).sum().alias("prev_common_rev"),
            ]
        )
        .sort(["industry_code", "end_date"])
    )

    if agg.is_empty():
        return empty_industry_capex_frame()

    # 4. 同口径同比增速与剪刀差计算 (百分比尺度 %)
    agg = agg.with_columns(
        [
            _same_sample_yoy_expr("curr_common_cip", "prev_common_cip", "cip_common_stocks").alias(
                "cip_yoy"
            ),
            _same_sample_yoy_expr("curr_common_fa", "prev_common_fa", "fa_common_stocks").alias(
                "fix_assets_yoy"
            ),
            _safe_ratio_expr(pl.col("cip"), pl.col("fix_assets")).alias("cip_to_fa_ratio"),
            _same_sample_yoy_expr(
                "curr_common_capex", "prev_common_capex", "capex_common_stocks"
            ).alias("capex_growth_ttm"),
            _same_sample_yoy_expr("curr_common_inv", "prev_common_inv", "inv_common_stocks").alias(
                "inventory_growth_ttm"
            ),
            _same_sample_yoy_expr("curr_common_rev", "prev_common_rev", "rev_common_stocks").alias(
                "revenue_growth_ttm"
            ),
        ]
    )

    agg = agg.with_columns(
        pl.when(
            pl.col("revenue_growth_ttm").is_not_null()
            & pl.col("inventory_growth_ttm").is_not_null()
        )
        .then(pl.col("revenue_growth_ttm") - pl.col("inventory_growth_ttm"))
        .otherwise(None)
        .alias("inventory_scissors")
    )

    # 统一 eff_date 为 Date 类型，过滤空行并投影
    result = agg.with_columns(pl.col("eff_date").cast(pl.Date).alias("eff_date")).select(
        list(INDUSTRY_CAPEX_SCHEMA)
    )
    return result.sort(["industry_code", "eff_date"])


def load_raw_financial_statement_pool(cat_ts: MarketDataCatalog) -> pl.DataFrame:
    """一次读取并归一 TuShare 资产负债表、现金流量表与利润表。"""
    bs_cols = ["symbol", "ann_date", "end_date", "cip", "fix_assets", "inventories", "total_assets"]
    bs = _load_dataset(cat_ts, "balancesheet", columns=bs_cols)
    cf = _load_dataset(
        cat_ts, "cashflow", columns=["symbol", "ann_date", "end_date", "c_pay_acq_const_fiolta"]
    )
    inc = _load_dataset(
        cat_ts, "income", columns=["symbol", "ann_date", "end_date", "total_revenue"]
    )

    if bs.is_empty():
        return pl.DataFrame()

    bs = bs.with_columns(
        pl.col("symbol").cast(pl.Utf8).str.slice(0, 6).alias("stock_key"),
        pl.col("ann_date").cast(pl.Date, strict=False).alias("ann_date"),
        pl.col("end_date").cast(pl.Date, strict=False).alias("end_date"),
        pl.col("cip").cast(pl.Float64, strict=False),
        pl.col("fix_assets").cast(pl.Float64, strict=False),
        pl.col("inventories").cast(pl.Float64, strict=False),
        pl.col("total_assets").cast(pl.Float64, strict=False),
    ).drop_nulls(subset=["stock_key", "end_date"])

    if not cf.is_empty():
        cf = cf.with_columns(
            pl.col("symbol").cast(pl.Utf8).str.slice(0, 6).alias("stock_key"),
            pl.col("end_date").cast(pl.Date, strict=False).alias("end_date"),
            pl.col("c_pay_acq_const_fiolta").cast(pl.Float64, strict=False),
        ).drop_nulls(subset=["stock_key", "end_date"])
        bs = bs.join(
            cf.select(["stock_key", "end_date", "c_pay_acq_const_fiolta"]),
            on=["stock_key", "end_date"],
            how="left",
        )
    else:
        bs = bs.with_columns(pl.lit(None, dtype=pl.Float64).alias("c_pay_acq_const_fiolta"))

    if not inc.is_empty():
        inc = inc.with_columns(
            pl.col("symbol").cast(pl.Utf8).str.slice(0, 6).alias("stock_key"),
            pl.col("end_date").cast(pl.Date, strict=False).alias("end_date"),
            pl.col("total_revenue").cast(pl.Float64, strict=False),
        ).drop_nulls(subset=["stock_key", "end_date"])
        bs = bs.join(
            inc.select(["stock_key", "end_date", "total_revenue"]),
            on=["stock_key", "end_date"],
            how="left",
        )
    else:
        bs = bs.with_columns(pl.lit(None, dtype=pl.Float64).alias("total_revenue"))

    return bs.unique(subset=["stock_key", "end_date"], keep="last")


def load_industry_l1_capex_facts(
    cat_ts: MarketDataCatalog,
    config: IndustryStructureConfig,
) -> pl.DataFrame:
    """加载申万一级行业（31 行业）资本开支事实长表。"""
    stock_fs = load_raw_financial_statement_pool(cat_ts)
    if stock_fs.is_empty():
        return empty_industry_capex_frame()

    index_to_l1, _ = load_industry_l1_maps(cat_ts, config)
    members = prepare_stock_industry_members(
        cat_ts, index_to_l1, classification=config.classification
    )
    if members.is_empty():
        return empty_industry_capex_frame()

    l1_map = members.select(["stock_key", "industry_code"]).unique(subset=["stock_key"])
    return _build_aggregated_financial_metrics(stock_fs, l1_map)


def load_industry_l2_capex_facts(
    cat_ts: MarketDataCatalog,
    cat_lx: MarketDataCatalog,
) -> pl.DataFrame:
    """加载申万二级行业（134 行业 / 13 共振方向池）资本开支事实长表。"""
    stock_fs = load_raw_financial_statement_pool(cat_ts)
    if stock_fs.is_empty():
        return empty_industry_capex_frame()

    golden = load_sw_2021_industry_members(
        cat_ts,
        level="L2",
        canonical_only=True,
        current_only=True,
        columns=("symbol", "industry_code", "level", "src", "is_canonical"),
    )
    if golden.is_empty():
        golden = load_sw_2021_industry_members(
            cat_lx,
            level="L2",
            canonical_only=True,
            current_only=True,
            columns=("symbol", "industry_code", "level", "src", "is_canonical"),
        )
    if golden.is_empty() or not {"industry_code", "symbol"}.issubset(golden.columns):
        return empty_industry_capex_frame()

    l2_map = (
        golden.with_columns(pl.col("symbol").cast(pl.Utf8).str.slice(0, 6).alias("stock_key"))
        .select(["stock_key", "industry_code"])
        .sort(["stock_key", "industry_code"])
        .unique(subset=["stock_key"], keep="first", maintain_order=True)
    )
    return _build_aggregated_financial_metrics(stock_fs, l2_map)


def industry_capex_panel_batch(
    cat_ts: MarketDataCatalog,
    config: IndustryStructureConfig,
    as_of_dates: tuple[date, ...],
) -> dict[date, pl.DataFrame]:
    """批量构建一级行业资本开支面板，按基准日执行无前视 backward join。"""
    if not as_of_dates:
        return {}
    facts = load_industry_l1_capex_facts(cat_ts, config)
    if facts.is_empty():
        return {}

    codes = facts["industry_code"].unique().to_list()
    grid = pl.DataFrame(
        {
            "trade_date": [d for d in as_of_dates for _ in codes],
            "industry_code": [c for _ in as_of_dates for c in codes],
        }
    )

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*Sortedness of columns.*")
        cols = [
            "trade_date",
            "industry_code",
            "cip_yoy",
            "fix_assets_yoy",
            "cip_to_fa_ratio",
            "capex_growth_ttm",
            "inventory_scissors",
        ]
        joined = (
            grid.sort("trade_date")
            .join_asof(
                facts.sort("eff_date"),
                left_on="trade_date",
                right_on="eff_date",
                by="industry_code",
                strategy="backward",
            )
            .select(cols)
        )

    results: dict[date, pl.DataFrame] = {}
    for raw_key, part in joined.partition_by("trade_date", as_dict=True).items():
        key = raw_key[0] if isinstance(raw_key, tuple) else raw_key
        if isinstance(key, date):
            results[key] = part.drop("trade_date")
    return results
