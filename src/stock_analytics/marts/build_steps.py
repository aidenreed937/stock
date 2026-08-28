"""领域 Mart 的分阶段构建步骤。"""

from __future__ import annotations

from datetime import date, timedelta
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
from stock_analytics.marts.dragon_tiger import (
    DRAGON_TIGER_MART_NAME,
    build_dragon_tiger_frame,
)
from stock_analytics.marts.etf_flow import ETF_FLOW_MART_NAME, build_etf_flow_frame
from stock_analytics.marts.global_macro import (
    GLOBAL_MACRO_MART_NAME,
    build_global_macro_daily_frame,
)
from stock_analytics.marts.industry_l2 import (
    INDUSTRY_L2_MART_NAME,
    build_industry_l2_frame,
)
from stock_analytics.marts.northbound_industry import (
    NORTHBOUND_INDUSTRY_MART_NAME,
    build_northbound_industry_frame,
)
from stock_analytics.marts.option_volatility import (
    SETTLEMENT_IV_PROXY_MART_NAME,
    build_settlement_iv_proxy_mart,
)
from stock_analytics.marts.unlock_pressure import (
    UNLOCK_PRESSURE_MART_NAME,
    build_unlock_pressure_frame,
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
        risk_catalog = _catalog_for(catalog, "lixinger", runtime=runtime)
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


def _catalog_for(
    catalog: DataCatalog,
    data_source: str,
    *,
    runtime: DataRuntimeContext | None,
) -> DataCatalog:
    """按数据源构造兄弟目录 Catalog（共享 storage_dir 与 runtime）。"""
    return DataCatalog(
        data_source=data_source,
        storage_dir=getattr(catalog, "storage_dir", None),
        runtime=runtime,
    )


def _slice_frame(
    frame: pl.DataFrame,
    *,
    start_date: date | None,
    end_date: date | None,
    date_column: str = "trade_date",
) -> pl.DataFrame:
    """按日期列裁剪输出窗口。"""
    result = frame
    if start_date is not None and date_column in result.columns:
        result = result.filter(pl.col(date_column) >= start_date)
    if end_date is not None and date_column in result.columns:
        result = result.filter(pl.col(date_column) <= end_date)
    return result


def build_global_macro(
    catalog: DataCatalog,
    store: FeatureStore,
    *,
    runtime: DataRuntimeContext | None,
    start_date: date | None,
    end_date: date | None,
    overwrite: bool,
) -> pl.DataFrame:
    """加载五源宏观序列并物化全球大类资产日频宽表。

    宏观序列总量小，采用全量重算；输出按请求窗口裁剪后增量合并。
    """
    effective_start = _incremental_start_date(
        store,
        GLOBAL_MACRO_MART_NAME,
        date_column="trade_date",
        requested_start=start_date,
        end_date=end_date,
        overwrite=overwrite,
    )
    cat_ts = catalog
    cat_yf = _catalog_for(catalog, "yfinance", runtime=runtime)
    cat_fred = _catalog_for(catalog, "fred", runtime=runtime)
    cat_lx = _catalog_for(catalog, "lixinger", runtime=runtime)

    yf_macro = cat_yf.load_dataset(
        "macro_indicators",
        columns=["trade_date", "symbol", "close"],
    )
    fred_macro = cat_fred.load_dataset(
        "macro_indicators",
        columns=["trade_date", "symbol", "close"],
    )
    cn_debt = cat_lx.load_dataset(
        "national_debt",
        columns=["trade_date", "tcm_y1", "tcm_y5", "tcm_y10", "tcm_y30"],
    )
    shibor = cat_ts.load_dataset("shibor", columns=["trade_date", "on", "3m"])
    lpr = cat_ts.load_dataset("shibor_lpr", columns=["trade_date", "1y"])

    # CNH 20 日动量：全历史计算再裁剪，避免窗口截断
    if not yf_macro.is_empty():
        cnh = yf_macro.filter(pl.col("symbol") == "CNH=X").select(
            "trade_date", pl.col("close").cast(pl.Float64, strict=False).alias("close")
        )
    else:
        cnh = pl.DataFrame()
    cnh_momentum = pl.DataFrame()
    if not cnh.is_empty():
        cnh_momentum = (
            cnh.unique(subset=["trade_date"], keep="last")
            .sort("trade_date")
            .with_columns(
                (pl.col("close") / pl.col("close").shift(20) - 1.0).alias("cnh_return_20d")
            )
            .select("trade_date", "cnh_return_20d")
        )

    result = build_global_macro_daily_frame(
        yf_macro,
        fred_macro,
        cn_debt,
        shibor,
        lpr,
    )
    if result.is_empty():
        return result
    if not cnh_momentum.is_empty():
        result = result.join(cnh_momentum, on="trade_date", how="left")

    sliced = _slice_frame(result, start_date=effective_start, end_date=end_date)
    if not sliced.is_empty():
        store.save_domain_mart(
            GLOBAL_MACRO_MART_NAME,
            sliced,
            keys=["trade_date"],
            date_column="trade_date",
            overwrite=overwrite,
        )
    return result


def build_dragon_tiger(
    catalog: DataCatalog,
    store: FeatureStore,
    *,
    start_date: date | None,
    end_date: date | None,
    overwrite: bool,
) -> pl.DataFrame:
    """加载龙虎榜席位明细并物化机构/游资日频聚合。

    全市场成交额分母取自 ``FeatureStore.market_daily.total_turnover``（物化宽表，
    与全市场 A 股日成交额对账一致），避免扫描全市场 ``stock_daily_bar``。
    """
    effective_start = _incremental_start_date(
        store,
        DRAGON_TIGER_MART_NAME,
        date_column="trade_date",
        requested_start=start_date,
        end_date=end_date,
        overwrite=overwrite,
    )
    top_inst = catalog.load_dataset(
        "top_inst",
        start_date=effective_start,
        end_date=end_date,
        columns=["trade_date", "symbol", "exalter", "side", "buy", "sell", "net_buy"],
    )
    top_list = catalog.load_dataset(
        "top_list",
        start_date=effective_start,
        end_date=end_date,
        columns=["trade_date", "symbol", "amount", "net_amount"],
    )
    market_turnover = store.get_market_daily(
        start_date=effective_start,
        end_date=end_date,
        columns=["trade_date", "total_turnover"],
    )
    if market_turnover.is_empty() or "total_turnover" not in market_turnover.columns:
        market_turnover = pl.DataFrame()
    else:
        market_turnover = market_turnover.select(
            "trade_date",
            pl.col("total_turnover").cast(pl.Float64, strict=False).alias("market_amount"),
        )
    result = build_dragon_tiger_frame(top_inst, top_list, market_turnover=market_turnover)
    if not result.is_empty():
        store.save_domain_mart(
            DRAGON_TIGER_MART_NAME,
            result,
            keys=["trade_date"],
            date_column="trade_date",
            overwrite=overwrite,
        )
    return result


def build_etf_flow(
    catalog: DataCatalog,
    store: FeatureStore,
    *,
    start_date: date | None,
    end_date: date | None,
    overwrite: bool,
    etf_universe: list[str] | None = None,
) -> pl.DataFrame:
    """加载观察池 ETF 份额与行情并物化风格资金流聚合。"""
    effective_start = _incremental_start_date(
        store,
        ETF_FLOW_MART_NAME,
        date_column="trade_date",
        requested_start=start_date,
        end_date=end_date,
        overwrite=overwrite,
    )
    # 份额/行情序列整体较小，全量加载保证首日 Δ份额可计算
    share_size = catalog.load_dataset(
        "etf_share_size",
        columns=["trade_date", "symbol", "etf_name", "total_share", "close"],
    )
    fund_daily = catalog.load_dataset(
        "fund_daily",
        columns=["trade_date", "symbol", "close"],
    )
    universe = etf_universe
    if universe is None:
        from stock_core.config.loader import load_watchlist_config

        watchlist = load_watchlist_config()
        universe = list(watchlist.tushare.funds)
    result = build_etf_flow_frame(
        share_size,
        fund_daily,
        etf_universe=universe,
    )
    if result.is_empty():
        return result
    sliced = _slice_frame(result, start_date=effective_start, end_date=end_date)
    if not sliced.is_empty():
        store.save_domain_mart(
            ETF_FLOW_MART_NAME,
            sliced,
            keys=["trade_date"],
            date_column="trade_date",
            overwrite=overwrite,
        )
    return result


def build_industry_l2(
    catalog: DataCatalog,
    store: FeatureStore,
    *,
    runtime: DataRuntimeContext | None,
    start_date: date | None,
    end_date: date | None,
    overwrite: bool,
) -> pl.DataFrame:
    """加载申万二级行业行情与理杏仁估值并物化下钻 Mart。

    滚动分位要求 5Y/10Y 历史窗口，但仅对请求窗口内的行计算分位（增量语义）：
    加载区间 = 请求区间 + 约 10 年前的窗口回看，分位输出从增量起点开始。
    """
    effective_start = _incremental_start_date(
        store,
        INDUSTRY_L2_MART_NAME,
        date_column="trade_date",
        requested_start=start_date,
        end_date=end_date,
        overwrite=overwrite,
    )
    cat_lx = _catalog_for(catalog, "lixinger", runtime=runtime)
    load_start = None
    if effective_start is not None:
        lookback_days = 2 * 366 * 10  # 覆盖 10Y 窗口约 2500 个交易日
        load_start = effective_start - timedelta(days=lookback_days)
    l2_fundamental = cat_lx.load_dataset(
        "sw_2021_l2_fundamental",
        start_date=load_start,
        end_date=end_date,
        columns=["trade_date", "symbol", "pe_ttm.ew", "pb.ew", "dyr.ew", "mc"],
    )
    sw_daily = catalog.load_dataset(
        "sw_daily",
        start_date=load_start,
        end_date=end_date,
        columns=[
            "trade_date",
            "symbol",
            "name",
            "close",
            "amount",
            "industry_level",
            "industry_code",
            "parent_code",
        ],
    )
    result = build_industry_l2_frame(
        sw_daily,
        l2_fundamental,
        percentile_cutoff=effective_start,
    )
    if result.is_empty():
        return result
    sliced = _slice_frame(result, start_date=effective_start, end_date=end_date)
    if not sliced.is_empty():
        store.save_domain_mart(
            INDUSTRY_L2_MART_NAME,
            sliced,
            keys=["trade_date", "industry_code"],
            date_column="trade_date",
            overwrite=overwrite,
        )
    return result


def build_unlock_pressure(
    catalog: DataCatalog,
    store: FeatureStore,
    *,
    start_date: date | None,
    end_date: date | None,
    overwrite: bool,
) -> pl.DataFrame:
    """加载限售解禁明细并按解禁日聚合解禁压力 Mart。

    解禁日为事件日，直接按请求窗口加载聚合；收盘价 as-of 前移 60 天覆盖
    非交易日/节假日的顺延取值。
    """
    effective_start = _incremental_start_date(
        store,
        UNLOCK_PRESSURE_MART_NAME,
        date_column="trade_date",
        requested_start=start_date,
        end_date=end_date,
        overwrite=overwrite,
    )
    share_float = catalog.load_dataset(
        "share_float",
        start_date=effective_start,
        end_date=end_date,
        columns=["symbol", "float_date", "float_share", "float_ratio"],
    )
    if share_float.is_empty():
        return build_unlock_pressure_frame(pl.DataFrame(), pl.DataFrame())
    close_start = effective_start - timedelta(days=60) if effective_start is not None else None
    daily_close = catalog.load_dataset(
        "stock_daily_bar",
        start_date=close_start,
        end_date=end_date,
        columns=["symbol", "trade_date", "close"],
    )
    result = build_unlock_pressure_frame(
        share_float, daily_close, start_date=effective_start, end_date=end_date
    )
    if not result.is_empty():
        store.save_domain_mart(
            UNLOCK_PRESSURE_MART_NAME,
            result,
            keys=["trade_date"],
            date_column="trade_date",
            overwrite=overwrite,
        )
    return result


def build_northbound_industry(
    catalog: DataCatalog,
    store: FeatureStore,
    *,
    start_date: date | None,
    end_date: date | None,
    overwrite: bool,
) -> pl.DataFrame:
    """加载沪深股通持股与申万一级成分并物化北向行业持仓 Mart。

    覆盖按交易所披露节奏如实保留：2024-08-19 前日频 + 其后季度末快照 +
    2016-2023 零星采样日。
    """
    effective_start = _incremental_start_date(
        store,
        NORTHBOUND_INDUSTRY_MART_NAME,
        date_column="trade_date",
        requested_start=start_date,
        end_date=end_date,
        overwrite=overwrite,
    )
    hk_hold = catalog.load_dataset(
        "hk_hold",
        start_date=effective_start,
        end_date=end_date,
        columns=["trade_date", "symbol", "vol", "ratio"],
    )
    if hk_hold.is_empty():
        return build_northbound_industry_frame(
            pl.DataFrame(),
            pl.DataFrame(),
            pl.DataFrame(),
            pl.DataFrame(),
        )
    hk_min = hk_hold["trade_date"].min()
    hk_max = hk_hold["trade_date"].max()
    # 非空过滤后日期列必有标量，收窄类型供 mypy 推导
    if not isinstance(hk_min, date) or not isinstance(hk_max, date):
        return build_northbound_industry_frame(
            pl.DataFrame(),
            pl.DataFrame(),
            pl.DataFrame(),
            pl.DataFrame(),
        )
    close_start = hk_min - timedelta(days=60)
    daily_close = catalog.load_dataset(
        "stock_daily_bar",
        start_date=close_start,
        end_date=hk_max,
        columns=["symbol", "trade_date", "close"],
    )
    constituents = catalog.load_dataset(
        "index_member",
        columns=["con_code", "index_code", "in_date", "out_date"],
    )
    sw_l1 = catalog.load_dataset(
        "sw_daily",
        start_date=close_start,
        end_date=hk_max,
        columns=["trade_date", "symbol", "name", "industry_level", "industry_code"],
    ).filter(pl.col("industry_level") == "L1")
    result = build_northbound_industry_frame(
        hk_hold,
        constituents,
        sw_l1,
        daily_close,
    )
    if not result.is_empty():
        store.save_domain_mart(
            NORTHBOUND_INDUSTRY_MART_NAME,
            result,
            keys=["trade_date", "industry_code"],
            date_column="trade_date",
            overwrite=overwrite,
        )
    return result


__all__ = [
    "build_convertible_bond",
    "build_corporate_actions",
    "build_dragon_tiger",
    "build_etf_flow",
    "build_global_macro",
    "build_industry_l2",
    "build_northbound_industry",
    "build_settlement_iv_proxy",
    "build_unlock_pressure",
]
