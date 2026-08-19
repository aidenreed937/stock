"""领域 Mart 的分阶段构建步骤。"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from stock_analytics.features.store import FeatureStore
from stock_analytics.marts.convertible_bond import CB_MART_NAME, build_convertible_bond_mart
from stock_analytics.marts.corporate_actions import (
    BLOCK_TRADE_MART_NAME,
    INSIDER_MART_NAME,
    REPURCHASE_MART_NAME,
    build_block_trade_mart,
    build_insider_activity_mart,
    build_repurchase_mart,
)
from stock_analytics.marts.option_volatility import (
    SETTLEMENT_IV_PROXY_MART_NAME,
    build_settlement_iv_proxy_mart,
)
from stock_data.catalog import DataCatalog

if TYPE_CHECKING:
    from stock_data.core.runtime import DataRuntimeContext


def _incremental_start_date(
    store: FeatureStore,
    mart_name: str,
    *,
    date_column: str,
    requested_start: date | None,
    end_date: date | None,
    overwrite: bool,
) -> date | None:
    """非覆盖构建时从已有 Mart 最新日期继续计算。"""
    if overwrite:
        return requested_start
    existing = store.get_domain_mart(
        mart_name,
        date_column=date_column,
        columns=[date_column],
    )
    if existing.is_empty() or date_column not in existing.columns:
        return requested_start
    latest_value = existing[date_column].drop_nulls().max()
    latest = latest_value if isinstance(latest_value, date) else None
    if latest is None or (end_date is not None and latest > end_date):
        return requested_start
    if requested_start is None or requested_start <= latest:
        return latest
    return requested_start


def build_convertible_bond(
    catalog: DataCatalog,
    store: FeatureStore,
    *,
    start_date: date | None,
    end_date: date | None,
    overwrite: bool,
) -> pl.DataFrame:
    """加载可转债行情并物化日频聚合。"""
    effective_start = _incremental_start_date(
        store,
        CB_MART_NAME,
        date_column="trade_date",
        requested_start=start_date,
        end_date=end_date,
        overwrite=overwrite,
    )
    daily = catalog.load_dataset(
        "cb_daily",
        start_date=effective_start,
        end_date=end_date,
        columns=["symbol", "trade_date", "close", "cb_over_rate", "bond_over_rate"],
    )
    result = build_convertible_bond_mart(daily)
    if not result.is_empty():
        store.save_domain_mart(
            CB_MART_NAME,
            result,
            keys=["trade_date"],
            date_column="trade_date",
            overwrite=overwrite,
        )
    return result


def build_corporate_actions(
    catalog: DataCatalog,
    store: FeatureStore,
    *,
    start_date: date | None,
    end_date: date | None,
    overwrite: bool,
    include_block_trade_discount: bool,
) -> dict[str, pl.DataFrame]:
    """加载并物化增减持、回购与大宗交易聚合。"""
    incremental_starts = (
        _incremental_start_date(
            store,
            INSIDER_MART_NAME,
            date_column="announcement_date",
            requested_start=start_date,
            end_date=end_date,
            overwrite=overwrite,
        ),
        _incremental_start_date(
            store,
            REPURCHASE_MART_NAME,
            date_column="announcement_date",
            requested_start=start_date,
            end_date=end_date,
            overwrite=overwrite,
        ),
        _incremental_start_date(
            store,
            BLOCK_TRADE_MART_NAME,
            date_column="trade_date",
            requested_start=start_date,
            end_date=end_date,
            overwrite=overwrite,
        ),
    )
    available_starts = [value for value in incremental_starts if value is not None]
    effective_start = (
        min(available_starts) if len(available_starts) == len(incremental_starts) else None
    )
    holdertrade = catalog.load_dataset(
        "stk_holdertrade",
        start_date=effective_start,
        end_date=end_date,
        columns=["symbol", "ann_date", "holder_name", "in_de", "change_vol", "avg_price"],
    )
    repurchase = catalog.load_dataset(
        "repurchase",
        start_date=effective_start,
        end_date=end_date,
        columns=["symbol", "ann_date", "proc", "vol", "amount"],
    )
    block_trade = catalog.load_dataset(
        "block_trade",
        start_date=effective_start,
        end_date=end_date,
        columns=[
            "symbol",
            "trade_date",
            "price",
            "volume",
            "vol",
            "amount",
            "buyer",
            "seller",
        ],
    )
    bars = None
    if include_block_trade_discount and not block_trade.is_empty():
        bars = catalog.load_bars(
            start_date=effective_start,
            end_date=end_date,
            columns=["symbol", "trade_date", "close"],
        )

    results = {
        INSIDER_MART_NAME: build_insider_activity_mart(holdertrade),
        REPURCHASE_MART_NAME: build_repurchase_mart(repurchase),
        BLOCK_TRADE_MART_NAME: build_block_trade_mart(block_trade, bars),
    }
    date_columns = {
        INSIDER_MART_NAME: "announcement_date",
        REPURCHASE_MART_NAME: "announcement_date",
        BLOCK_TRADE_MART_NAME: "trade_date",
    }
    keys = {
        INSIDER_MART_NAME: ["announcement_date"],
        REPURCHASE_MART_NAME: ["announcement_date"],
        BLOCK_TRADE_MART_NAME: ["trade_date"],
    }
    for name, frame in results.items():
        if not frame.is_empty():
            store.save_domain_mart(
                name,
                frame,
                keys=keys[name],
                date_column=date_columns[name],
                overwrite=overwrite,
            )
    return results


def build_settlement_iv_proxy(
    catalog: DataCatalog,
    store: FeatureStore,
    *,
    runtime: DataRuntimeContext | None,
    start_date: date | None,
    end_date: date | None,
    overwrite: bool,
    underlying_symbols: tuple[str, ...],
    risk_free_rates: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """加载期权结算价及标的行情并物化波动率代理。"""
    effective_start = _incremental_start_date(
        store,
        SETTLEMENT_IV_PROXY_MART_NAME,
        date_column="trade_date",
        requested_start=start_date,
        end_date=end_date,
        overwrite=overwrite,
    )
    daily = catalog.load_dataset(
        "opt_daily",
        start_date=effective_start,
        end_date=end_date,
        columns=["symbol", "trade_date", "settle"],
    )
    basic = catalog.load_dataset(
        "opt_basic",
        columns=[
            "symbol",
            "call_put",
            "exercise_price",
            "maturity_date",
            "opt_code",
            "opt_type",
        ],
    )
    underlying_frames = [
        frame
        for frame in (
            catalog.load_dataset(
                "fund_daily",
                start_date=effective_start,
                end_date=end_date,
                symbols=list(underlying_symbols),
                columns=["symbol", "trade_date", "close"],
            ),
            catalog.load_dataset(
                "index_daily_bar",
                start_date=effective_start,
                end_date=end_date,
                symbols=list(underlying_symbols),
                columns=["symbol", "trade_date", "close"],
            ),
        )
        if not frame.is_empty()
    ]
    underlying = (
        pl.concat(underlying_frames, how="diagonal_relaxed")
        if underlying_frames
        else pl.DataFrame()
    )
    risk_free = risk_free_rates
    if risk_free is None:
        risk_free = _load_risk_free_rates(
            catalog,
            runtime=runtime,
            start_date=effective_start,
            end_date=end_date,
        )
    result = build_settlement_iv_proxy_mart(
        daily,
        basic,
        underlying,
        risk_free_rates=risk_free,
        underlying_symbols=underlying_symbols,
    )
    if not result.is_empty():
        store.save_domain_mart(
            SETTLEMENT_IV_PROXY_MART_NAME,
            result,
            keys=["trade_date", "underlying_symbol"],
            date_column="trade_date",
            overwrite=overwrite,
        )
    return result


def _load_risk_free_rates(
    catalog: DataCatalog,
    *,
    runtime: DataRuntimeContext | None,
    start_date: date | None,
    end_date: date | None,
) -> pl.DataFrame:
    """加载中债一年期收益率，并转成 Black-Scholes 所需的小数形式。"""
    try:
        risk_catalog = DataCatalog(
            data_source="lixinger",
            storage_dir=catalog.storage_dir,
            runtime=runtime,
        )
        frame = risk_catalog.load_dataset(
            "national_debt",
            start_date=start_date,
            end_date=end_date,
            columns=["trade_date", "tcm_y1"],
        )
        if frame.is_empty() or "tcm_y1" not in frame.columns:
            return pl.DataFrame()
        return frame.select(
            "trade_date",
            (pl.col("tcm_y1").cast(pl.Float64, strict=False) / 100.0).alias("risk_free_rate"),
        )
    except (FileNotFoundError, ValueError):
        return pl.DataFrame()


__all__ = ["build_convertible_bond", "build_corporate_actions", "build_settlement_iv_proxy"]
