"""行业结构分析面板构建。"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

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
from stock_analytics.pipelines.industry_structure.panel_normalization import (
    _coalesce_industry_names,
    _industry_daily_frame,
    _panel_start_date,
)
from stock_analytics.pipelines.industry_structure.panel_schema import (
    BASE_PANEL_SCHEMA,
    empty_industry_panel,
    select_base_panel_columns,
)
from stock_analytics.pipelines.industry_structure.panel_sources import (
    load_dataset,
    load_industry_l1_maps,
)
from stock_analytics.pipelines.market_temperature.cache import CachedCatalog, DatasetFrameCache
from stock_core.contracts import MarketDataCatalog

if TYPE_CHECKING:
    from stock_reporting.interpretation.industry_structure.config import IndustryStructureConfig

__all__ = [
    "BASE_PANEL_SCHEMA",
    "_industry_daily_frame",
    "_market_panel_batch",
    "empty_industry_panel",
]


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
    return select_base_panel_columns(panel)


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
    return select_base_panel_columns(_coalesce_industry_names(panel))


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
    return select_base_panel_columns(frame)
