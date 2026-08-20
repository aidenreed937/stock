"""行业结构分析面板构建。"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl

from stock_analytics.pipelines.industry_structure.classifier import IndustryClassifier
from stock_analytics.pipelines.industry_structure.panel_aggregations import (
    FastFundamentalContext,
    IndustryMoneyflowContext,
    fast_fundamental_panel,
    industry_moneyflow_panel,
)
from stock_analytics.pipelines.industry_structure.panel_batch import (
    _market_panel,
    _market_panel_batch,
)
from stock_analytics.pipelines.industry_structure.panel_batch_inputs import (
    IndustryPanelBatchInputs,
)
from stock_analytics.pipelines.industry_structure.panel_metrics import (
    fundamental_panel,
    valuation_panel,
)
from stock_analytics.pipelines.industry_structure.panel_sources import (
    load_dataset,
    load_industry_l1_maps,
    optional_text_expr,
)
from stock_analytics.pipelines.market_temperature.cache import CachedCatalog, DatasetFrameCache
from stock_core.contracts import MarketDataCatalog

if TYPE_CHECKING:
    from stock_reporting.interpretation.industry_structure.config import IndustryStructureConfig

__all__ = ["_market_panel_batch"]

BASE_PANEL_SCHEMA: dict[str, Any] = {
    "as_of_date": pl.Date,
    "industry_code": pl.Utf8,
    "industry_name": pl.Utf8,
    "market_data_date": pl.Date,
    "valuation_date": pl.Date,
    "fundamental_date": pl.Date,
    "return_5d": pl.Float64,
    "return_10d": pl.Float64,
    "return_20d": pl.Float64,
    "return_60d": pl.Float64,
    "return_120d": pl.Float64,
    "relative_return_20d": pl.Float64,
    "ma_bias_20d": pl.Float64,
    "amount_yi": pl.Float64,
    "tcr": pl.Float64,
    "tcr_percentile": pl.Float64,
    "moneyflow_date": pl.Date,
    "moneyflow_sample_size": pl.Int64,
    "moneyflow_stock_count": pl.Int64,
    "money_net_inflow_yi_20d": pl.Float64,
    "money_net_inflow_share_20d": pl.Float64,
    "large_money_net_inflow_share_20d": pl.Float64,
    "money_net_inflow_share_5d": pl.Float64,
    "pe_ttm": pl.Float64,
    "pb": pl.Float64,
    "dividend_yield": pl.Float64,
    "pe_percentile_5y": pl.Float64,
    "pb_percentile_5y": pl.Float64,
    "pbroe_residual": pl.Float64,
    "pbroe_undervalued": pl.Boolean,
    "revenue_growth_ttm": pl.Float64,
    "profit_growth_ttm": pl.Float64,
    "roe_ttm": pl.Float64,
    "revenue_growth_percentile": pl.Float64,
    "profit_growth_percentile": pl.Float64,
    "roe_percentile": pl.Float64,
    "forecast_date": pl.Date,
    "forecast_sample_size": pl.Int64,
    "forecast_positive_share": pl.Float64,
    "forecast_p_change_mid_median": pl.Float64,
    "express_date": pl.Date,
    "express_sample_size": pl.Int64,
    "express_profit_growth_median": pl.Float64,
    "express_roe_median": pl.Float64,
    "report_rc_date": pl.Date,
    "report_rc_sample_size": pl.Int64,
    "report_rc_revision_ratio": pl.Float64,
    "report_rc_up_count": pl.Int64,
    "report_rc_down_count": pl.Int64,
}


def empty_industry_panel() -> pl.DataFrame:
    """返回稳定 schema 的空行业面板。"""
    return pl.DataFrame(schema=BASE_PANEL_SCHEMA)


def build_industry_panel(
    config: IndustryStructureConfig,
    *,
    as_of_date: date,
    trade_dates: tuple[date, ...],
    storage_dir: Path | str | None = None,
    dataset_cache: DatasetFrameCache | None = None,
) -> pl.DataFrame:
    """构建每个申万一级行业一行的结构分析基础面板。"""
    from stock_data.catalog import DataCatalog

    base_cat_ts = DataCatalog(data_source="tushare", storage_dir=storage_dir)
    base_cat_lx = DataCatalog(data_source="lixinger", storage_dir=storage_dir)
    cat_ts = CachedCatalog(base_cat_ts, dataset_cache) if dataset_cache is not None else base_cat_ts
    cat_lx = CachedCatalog(base_cat_lx, dataset_cache) if dataset_cache is not None else base_cat_lx
    start_date = _panel_start_date(config, as_of_date, trade_dates)
    raw_sw = load_dataset(
        cat_ts,
        "sw_daily",
        start_date=start_date,
        end_date=as_of_date,
        columns=[
            "symbol",
            "trade_date",
            "name",
            "industry_name",
            "index_name",
            "close",
            "amount",
            "classification",
            "industry_level",
        ],
    )
    daily = _industry_daily_frame(raw_sw, config, cat_ts)
    market_panel = _market_panel(daily, config, as_of_date, cat_ts)
    if market_panel.is_empty():
        return empty_industry_panel()

    _, industry_to_l1 = load_industry_l1_maps(cat_ts, config)
    valuation = valuation_panel(
        cat_lx,
        as_of_date,
        industry_to_l1,
        classification_catalog=cat_ts,
    )
    fundamentals = fundamental_panel(cat_lx, as_of_date, industry_to_l1)
    fast_fundamentals = fast_fundamental_panel(
        cat_ts,
        cat_lx,
        FastFundamentalContext(
            config=config,
            as_of_date=as_of_date,
            trade_dates=trade_dates,
            industry_codes=market_panel["industry_code"].to_list(),
        ),
    )
    panel = market_panel
    if not valuation.is_empty():
        panel = panel.join(valuation, on="industry_code", how="left")
    if not fundamentals.is_empty():
        panel = panel.join(fundamentals, on="industry_code", how="left")
    if not fast_fundamentals.is_empty():
        panel = panel.join(fast_fundamentals, on="industry_code", how="left")
    moneyflow = industry_moneyflow_panel(
        cat_ts,
        cat_lx,
        IndustryMoneyflowContext(
            config=config,
            as_of_date=as_of_date,
            trade_dates=trade_dates,
            industry_codes=market_panel["industry_code"].to_list(),
        ),
    )
    if not moneyflow.is_empty():
        panel = panel.join(moneyflow, on="industry_code", how="left")
    panel = _coalesce_industry_names(panel)
    return _select_base_panel_columns(panel)


def build_industry_panel_from_daily(
    config: IndustryStructureConfig,
    *,
    as_of_date: date,
    trade_dates: tuple[date, ...],
    industry_daily: pl.DataFrame,
    cat_ts: MarketDataCatalog,
    cat_lx: MarketDataCatalog,
    batch_inputs: IndustryPanelBatchInputs | None = None,
    market_panel: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """从已物化的 ``industry_daily`` 构建单个基准日的结构面板。

    该入口只接收 Mart 日频事实和构建阶段的数据目录。报告消费路径应使用
    :func:`load_industry_panel_daily`，不会经过本函数或任何 Curated 聚合。
    """
    market_panel = (
        market_panel
        if market_panel is not None
        else _market_panel(industry_daily, config, as_of_date, cat_ts)
    )
    if market_panel.is_empty():
        return empty_industry_panel()

    _, industry_to_l1 = load_industry_l1_maps(cat_ts, config)
    valuation = (
        batch_inputs.valuation_by_date.get(as_of_date, pl.DataFrame())
        if batch_inputs is not None
        else valuation_panel(
            cat_lx,
            as_of_date,
            industry_to_l1,
            classification_catalog=cat_ts,
        )
    )
    fundamentals = (
        batch_inputs.fundamental_by_date.get(as_of_date, pl.DataFrame())
        if batch_inputs is not None
        else fundamental_panel(cat_lx, as_of_date, industry_to_l1)
    )
    fast_fundamentals = fast_fundamental_panel(
        cat_ts,
        cat_lx,
        FastFundamentalContext(
            config=config,
            as_of_date=as_of_date,
            trade_dates=trade_dates,
            industry_codes=market_panel["industry_code"].to_list(),
        ),
        batch_inputs=batch_inputs,
    )
    panel = market_panel
    if not valuation.is_empty():
        panel = panel.join(valuation, on="industry_code", how="left")
    if not fundamentals.is_empty():
        panel = panel.join(fundamentals, on="industry_code", how="left")
    if not fast_fundamentals.is_empty():
        panel = panel.join(fast_fundamentals, on="industry_code", how="left")
    moneyflow = industry_moneyflow_panel(
        cat_ts,
        cat_lx,
        IndustryMoneyflowContext(
            config=config,
            as_of_date=as_of_date,
            trade_dates=trade_dates,
            industry_codes=market_panel["industry_code"].to_list(),
        ),
        batch_inputs=batch_inputs,
    )
    if not moneyflow.is_empty():
        panel = panel.join(moneyflow, on="industry_code", how="left")
    return _select_base_panel_columns(_coalesce_industry_names(panel))


def load_industry_panel_daily(
    *,
    as_of_date: date,
    storage_dir: Path | str | None = None,
) -> pl.DataFrame:
    """严格从行业结构面板 Mart 读取指定基准日快照。

    Mart 缺失时返回稳定空 Schema；这里不创建 DataCatalog，也不从
    ``sw_daily`` 或其他 Curated 明细回退计算。
    """
    from stock_analytics.features.store import FeatureStore

    store = FeatureStore(mart_dir=Path(storage_dir) / "mart" if storage_dir else None)
    frame = store.get_industry_panel_daily(start_date=as_of_date, end_date=as_of_date)
    if frame.is_empty():
        return empty_industry_panel()
    return _select_base_panel_columns(frame)


def _panel_start_date(
    config: IndustryStructureConfig,
    as_of_date: date,
    trade_dates: tuple[date, ...],
) -> date:
    if trade_dates:
        return trade_dates[0] - timedelta(days=30)
    return as_of_date - timedelta(days=max(config.windows, default=config.main_window) * 4)


def _industry_daily_frame(
    frame: pl.DataFrame,
    config: IndustryStructureConfig,
    catalog: MarketDataCatalog,
) -> pl.DataFrame:
    required = {"symbol", "trade_date", "close"}
    if frame.is_empty() or not required.issubset(frame.columns):
        return pl.DataFrame()
    amount_expr = (
        pl.col("amount").cast(pl.Float64, strict=False)
        if "amount" in frame.columns
        else pl.lit(None, dtype=pl.Float64)
    )
    has_explicit_scope = {"classification", "industry_level"}.issubset(frame.columns)
    select_exprs = [
        pl.col("symbol").cast(pl.String).alias("industry_code"),
        "trade_date",
        optional_text_expr(frame, ("name", "industry_name", "index_name"), "_sw_industry_name"),
        pl.col("close").cast(pl.Float64, strict=False).alias("close"),
        amount_expr.alias("amount"),
    ]
    if has_explicit_scope:
        select_exprs.extend(
            [
                pl.col("classification").cast(pl.String, strict=False).alias("classification"),
                pl.col("industry_level").cast(pl.String, strict=False).alias("industry_level"),
            ]
        )
    base = frame.select(select_exprs).drop_nulls(subset=["industry_code", "trade_date", "close"])
    base = base.filter(pl.col("close") > 0).sort(["industry_code", "trade_date"])
    classifier = IndustryClassifier(catalog)
    if has_explicit_scope:
        base = base.filter(
            (pl.col("classification") == config.classification) & (pl.col("industry_level") == "L1")
        )
    else:
        l1_codes = list(classifier.get_l1_codes(config.classification))
        if l1_codes:
            l1_frame = base.filter(pl.col("industry_code").is_in(l1_codes))
            if l1_frame["industry_code"].n_unique() >= 10:
                base = l1_frame
    name_map = classifier.get_name_map(config.classification)
    return base.with_columns(
        pl.struct(["industry_code", "_sw_industry_name"])
        .map_elements(
            lambda row: _resolve_industry_name(
                str(row["industry_code"]),
                name_map,
                fallback=row.get("_sw_industry_name"),
            ),
            return_dtype=pl.Utf8,
        )
        .alias("industry_name")
    ).drop("_sw_industry_name")


def _resolve_industry_name(code: str, name_map: dict[str, str], *, fallback: object = None) -> str:
    if code in name_map:
        return name_map[code]
    prefix = code.split(".")[0]
    name = name_map.get(prefix)
    if name:
        return name
    fallback_text = str(fallback).strip() if fallback is not None else ""
    return fallback_text if fallback_text and fallback_text != "None" else code


def _coalesce_industry_names(panel: pl.DataFrame) -> pl.DataFrame:
    if "industry_name_from_valuation" not in panel.columns:
        return panel
    return panel.with_columns(
        pl.coalesce(
            pl.col("industry_name"),
            pl.col("industry_name_from_valuation"),
            pl.col("industry_code"),
        ).alias("industry_name")
    ).drop("industry_name_from_valuation")


def _select_base_panel_columns(panel: pl.DataFrame) -> pl.DataFrame:
    columns = []
    for column, dtype in BASE_PANEL_SCHEMA.items():
        if column in panel.columns:
            columns.append(pl.col(column).cast(dtype, strict=False).alias(column))
        else:
            columns.append(pl.lit(None, dtype=dtype).alias(column))
    return panel.select(columns)
