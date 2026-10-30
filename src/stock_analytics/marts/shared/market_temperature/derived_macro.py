"""市场温度计宏观流动性派生指标。"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from stock_analytics.features.dataset_cache import DatasetFrameCache
from stock_analytics.primitives import add_dff_availability_date
from stock_core.contracts import MarketDataCatalog

from . import external_risk_facts as _risk_facts
from .derived_external import (
    _external_environment_row,
    _external_pressure_rows,
    _fred_symbol_frame,
    _fred_yoy_frame,
    _return_percentile_metric_row,
)
from .derived_helpers import (
    _load_dataset,
    _percentile_metric_row,
    _real_rate_frame,
    _with_month_date,
    _with_social_finance_yoy,
)

_FRED_TO_LEGACY_MACRO_SYMBOL = {
    "DGS10": "^TNX",
    "DGS3MO": "^IRX",
    "VIXCLS": "^VIX",
    "DCOILWTICO": "CL=F",
    "DTWEXBGS": "DX-Y.NYB",
}


def _canonical_macro_symbols(frame: pl.DataFrame) -> pl.DataFrame:
    """将 FRED 宏观序列映射为既有外部指标使用的稳定 symbol。"""
    if frame.is_empty() or "symbol" not in frame.columns:
        return frame
    return frame.with_columns(
        pl.col("symbol").replace(_FRED_TO_LEGACY_MACRO_SYMBOL).alias("symbol")
    )


def _merge_macro_sources(
    *source_frames: pl.DataFrame,
) -> pl.DataFrame:
    """合并宏观来源，后传入的来源在同日同序列时优先。"""
    frames = [_canonical_macro_symbols(frame) for frame in source_frames if not frame.is_empty()]
    if not frames:
        return pl.DataFrame()
    merged = pl.concat(frames, how="diagonal_relaxed")
    if {"symbol", "trade_date"}.issubset(merged.columns):
        merged = merged.unique(subset=["symbol", "trade_date"], keep="last")
    return merged.sort(["symbol", "trade_date"])


def _macro_liquidity_rows(
    as_of_date: date,
    storage_dir: Path | str | None,
    dataset_cache: DatasetFrameCache | None = None,
    *,
    external_cutoff_date: date | None = None,
) -> list[dict[str, Any]]:
    from stock_data.catalog import DataCatalog

    cat_ts = DataCatalog(data_source="tushare", storage_dir=storage_dir)
    cat_lx = DataCatalog(data_source="lixinger", storage_dir=storage_dir)
    cat_yf = DataCatalog(data_source="yfinance", storage_dir=storage_dir)
    cat_av = DataCatalog(data_source="alphavantage", storage_dir=storage_dir)
    cat_fred = DataCatalog(data_source="fred", storage_dir=storage_dir)
    rows: list[dict[str, Any]] = []
    national_debt = _load_dataset(
        cat_lx,
        "national_debt",
        columns=["trade_date", "tcm_y10"],
        end_date=as_of_date,
        dataset_cache=dataset_cache,
    )
    cn_cpi = _with_month_date(
        _load_dataset(
            cat_ts,
            "cn_cpi",
            columns=["month", "nt_yoy"],
            end_date=as_of_date,
            dataset_cache=dataset_cache,
        )
    )
    rows.append(
        _percentile_metric_row(
            national_debt,
            "macro_bond_yield_10y_temperature",
            "tcm_y10",
            as_of_date,
            inverse=True,
            note="10年国债收益率历史反向分位",
        )
    )
    rows.append(
        _percentile_metric_row(
            _load_dataset(
                cat_ts,
                "shibor",
                columns=["trade_date", "on"],
                end_date=as_of_date,
                dataset_cache=dataset_cache,
            ),
            "macro_shibor_on_temperature",
            "on",
            as_of_date,
            inverse=True,
            note="Shibor O/N 历史反向分位",
        )
    )
    rows.extend(
        _money_credit_rows(
            cat_ts,
            cat_lx,
            as_of_date,
            national_debt=national_debt,
            cn_cpi=cn_cpi,
            dataset_cache=dataset_cache,
        )
    )
    rows.extend(
        _external_macro_rows(
            cat_yf,
            cat_av,
            as_of_date,
            macro_cat=cat_fred,
            gold_cat=cat_lx,
            metal_cat=cat_lx,
            dataset_cache=dataset_cache,
            external_cutoff_date=external_cutoff_date,
        )
    )
    rows.extend(
        _us_macro_background_rows(
            cat_fred,
            as_of_date,
            dataset_cache=dataset_cache,
            external_cutoff_date=external_cutoff_date,
        )
    )
    return [*rows, *_external_pressure_rows(rows, as_of_date)]


def _money_credit_rows(
    cat_ts: MarketDataCatalog,
    cat_lx: MarketDataCatalog,
    as_of_date: date,
    *,
    national_debt: pl.DataFrame | None = None,
    cn_cpi: pl.DataFrame | None = None,
    dataset_cache: DatasetFrameCache | None = None,
) -> list[dict[str, Any]]:
    cn_m = _with_month_date(
        _load_dataset(
            cat_lx,
            "cn_m",
            columns=["month", "m1_yoy", "m2_yoy"],
            end_date=as_of_date,
            dataset_cache=dataset_cache,
        )
    )
    sf_month = _with_month_date(
        _load_dataset(
            cat_lx,
            "sf_month",
            columns=["month", "stk_endval"],
            end_date=as_of_date,
            dataset_cache=dataset_cache,
        )
    )
    if cn_cpi is None:
        cn_cpi = _with_month_date(
            _load_dataset(
                cat_ts,
                "cn_cpi",
                columns=["month", "nt_yoy"],
                end_date=as_of_date,
                dataset_cache=dataset_cache,
            )
        )
    rows = [
        _percentile_metric_row(
            cn_m,
            "macro_m2_yoy_temperature",
            "m2_yoy",
            as_of_date,
            date_col="_month_date",
            note="M2同比历史分位",
        ),
        _percentile_metric_row(
            cn_m.with_columns((pl.col("m1_yoy") - pl.col("m2_yoy")).alias("_m1_m2_gap")),
            "macro_m1_m2_gap_temperature",
            "_m1_m2_gap",
            as_of_date,
            date_col="_month_date",
            note="M1-M2剪刀差历史分位",
        ),
        _percentile_metric_row(
            _with_social_finance_yoy(sf_month),
            "macro_social_finance_stock_temperature",
            "_sf_stock_yoy",
            as_of_date,
            date_col="_month_date",
            note="社融存量同比历史分位",
        ),
    ]
    if national_debt is None:
        national_debt = _load_dataset(
            cat_lx,
            "national_debt",
            columns=["trade_date", "tcm_y10"],
            end_date=as_of_date,
            dataset_cache=dataset_cache,
        )
    real_rate = _real_rate_frame(national_debt, cn_cpi)
    rows.append(
        _percentile_metric_row(
            real_rate,
            "macro_real_rate_temperature",
            "_real_rate",
            as_of_date,
            date_col="_month_date",
            inverse=True,
            note="10年国债-CPI同比的实际利率反向分位",
        )
    )
    return rows


def _external_macro_rows(
    cat: MarketDataCatalog,
    fx_cat: MarketDataCatalog,
    as_of_date: date,
    *,
    macro_cat: MarketDataCatalog | None = None,
    gold_cat: MarketDataCatalog | None = None,
    metal_cat: MarketDataCatalog | None = None,
    dataset_cache: DatasetFrameCache | None = None,
    external_cutoff_date: date | None = None,
) -> list[dict[str, Any]]:
    external_end_date = (
        external_cutoff_date if external_cutoff_date is not None else as_of_date - timedelta(days=1)
    )
    legacy_macro = _load_dataset(
        cat,
        "macro_indicators",
        columns=["symbol", "trade_date", "close", "value"],
        end_date=external_end_date,
        dataset_cache=dataset_cache,
    )
    if macro_cat is not None and macro_cat is not cat:
        macro_frame = _load_dataset(
            macro_cat,
            "macro_indicators",
            columns=["symbol", "trade_date", "close", "value"],
            end_date=external_end_date,
            dataset_cache=dataset_cache,
        )
        macro_frame = _merge_macro_sources(legacy_macro, macro_frame)
    else:
        macro_frame = _canonical_macro_symbols(legacy_macro)

    if gold_cat is not None:
        gold_raw = _load_dataset(
            gold_cat,
            "gold_price",
            columns=["trade_date", "lbma_pm_usd"],
            end_date=external_end_date,
            dataset_cache=dataset_cache,
        )
        if not gold_raw.is_empty() and "lbma_pm_usd" in gold_raw.columns:
            gold_frame = gold_raw.select(
                "trade_date",
                pl.lit("GC=F").alias("symbol"),
                pl.col("lbma_pm_usd").cast(pl.Float64, strict=False).alias("close"),
                pl.col("lbma_pm_usd").cast(pl.Float64, strict=False).alias("value"),
            ).drop_nulls(subset=["close"])
            macro_frame = _merge_macro_sources(macro_frame, gold_frame)

    if metal_cat is not None:
        copper_raw = _load_dataset(
            metal_cat,
            "non_ferrous_metals",
            columns=["trade_date", "l_cu_p"],
            end_date=external_end_date,
            dataset_cache=dataset_cache,
        )
        if not copper_raw.is_empty() and "l_cu_p" in copper_raw.columns:
            copper_frame = copper_raw.select(
                "trade_date",
                pl.lit("HG=F").alias("symbol"),
                pl.col("l_cu_p").cast(pl.Float64, strict=False).alias("close"),
                pl.col("l_cu_p").cast(pl.Float64, strict=False).alias("value"),
            ).drop_nulls(subset=["close"])
            macro_frame = _merge_macro_sources(macro_frame, copper_frame)
    fx_frame = _load_dataset(
        fx_cat,
        "macro_indicators",
        columns=["symbol", "trade_date", "close", "value"],
        end_date=external_end_date,
        dataset_cache=dataset_cache,
    )
    index_frame = _load_dataset(
        cat,
        "index_daily_bar",
        columns=["symbol", "trade_date", "close"],
        end_date=external_end_date,
        dataset_cache=dataset_cache,
    )
    if index_frame.is_empty():
        index_frame = macro_frame
    rows = [
        _return_percentile_metric_row(
            index_frame,
            "^GSPC",
            "macro_sp500_20d_return_temperature",
            as_of_date,
            note="标普500 20日收益历史分位",
        ),
        _return_percentile_metric_row(
            index_frame,
            "^IXIC",
            "macro_nasdaq_20d_return_temperature",
            as_of_date,
            note="纳斯达克综合指数20日收益历史分位",
        ),
        _percentile_metric_row(
            macro_frame.filter(pl.col("symbol") == "^VIX"),
            "macro_vix_temperature",
            "close",
            as_of_date,
            inverse=True,
            note="VIX历史反向分位",
        ),
        _return_percentile_metric_row(
            macro_frame,
            "DX-Y.NYB",
            "macro_usd_index_20d_change_temperature",
            as_of_date,
            inverse=True,
            note="美元指数20日变化历史反向分位",
        ),
        _percentile_metric_row(
            macro_frame.filter(pl.col("symbol") == "^TNX"),
            "macro_us_10y_temperature",
            "close",
            as_of_date,
            inverse=True,
            note="美债10年收益率历史反向分位",
        ),
        _return_percentile_metric_row(
            macro_frame,
            "HG=F",
            "macro_copper_20d_return_temperature",
            as_of_date,
            note="伦敦铜现货代理20日收益历史分位",
        ),
        _return_percentile_metric_row(
            macro_frame,
            "GC=F",
            "macro_gold_20d_return_pressure",
            as_of_date,
            note="黄金20日收益历史分位，作为避险压力观察项",
        ),
        _return_percentile_metric_row(
            macro_frame,
            "CL=F",
            "macro_oil_20d_return_pressure",
            as_of_date,
            note="原油20日收益历史分位，作为通胀压力观察项",
        ),
        _percentile_metric_row(
            macro_frame.filter(pl.col("symbol") == "DX-Y.NYB"),
            "macro_usd_index_temperature",
            "close",
            as_of_date,
            inverse=True,
            note="美元指数水平历史反向分位，辅助观察",
        ),
        _return_percentile_metric_row(
            fx_frame,
            "CNH=X",
            "macro_cnh_20d_change_temperature",
            as_of_date,
            inverse=True,
            note=("Alpha Vantage 离岸人民币USD/CNH 20日变化历史反向分位，人民币贬值压力外部观察"),
        ),
    ]
    rows.extend(_risk_facts.raw_external_change_rows(index_frame, macro_frame, as_of_date))
    rows.append(_external_environment_row(rows, as_of_date))
    return rows


def _us_macro_background_rows(
    cat: MarketDataCatalog,
    as_of_date: date,
    *,
    dataset_cache: DatasetFrameCache | None = None,
    external_cutoff_date: date | None = None,
) -> list[dict[str, Any]]:
    external_end_date = (
        external_cutoff_date if external_cutoff_date is not None else as_of_date - timedelta(days=1)
    )
    frame = _load_dataset(
        cat,
        "macro_indicators",
        columns=["symbol", "trade_date", "value", "close"],
        end_date=external_end_date,
        dataset_cache=dataset_cache,
    )
    return [
        _percentile_metric_row(
            _fred_symbol_frame(frame, "T10Y2Y"),
            "macro_fred_t10y2y_temperature",
            "_value",
            as_of_date,
            note="FRED T10Y2Y期限利差历史分位，美国期限结构压力日频背景观察",
        ),
        _percentile_metric_row(
            _dff_available_frame(frame),
            "macro_fred_fedfunds_temperature",
            "_value",
            as_of_date,
            inverse=True,
            note="FRED DFF政策利率历史反向分位，按观测发布后 A 股可用日计",
        ),
        _percentile_metric_row(
            _fred_symbol_frame(frame, "WALCL"),
            "macro_fred_walcl_temperature",
            "_value",
            as_of_date,
            note="FRED WALCL美联储资产负债表规模历史分位，周频流动性背景观察",
        ),
        _percentile_metric_row(
            _fred_yoy_frame(frame, "CPIAUCSL", periods=12),
            "macro_fred_cpi_yoy_temperature",
            "_yoy",
            as_of_date,
            inverse=True,
            note="FRED CPIAUCSL同比小数历史反向分位，美国通胀压力月频背景观察",
        ),
        _percentile_metric_row(
            _fred_symbol_frame(frame, "UNRATE"),
            "macro_fred_unrate_temperature",
            "_value",
            as_of_date,
            inverse=True,
            note="FRED UNRATE失业率历史反向分位，美国就业压力月频背景观察",
        ),
        _percentile_metric_row(
            _fred_yoy_frame(frame, "PAYEMS", periods=12),
            "macro_fred_payems_yoy_temperature",
            "_yoy",
            as_of_date,
            note="FRED PAYEMS非农就业人数同比小数历史分位，美国就业周期月频背景观察",
        ),
        _percentile_metric_row(
            _fred_yoy_frame(frame, "GDP", periods=4),
            "macro_fred_gdp_yoy_temperature",
            "_yoy",
            as_of_date,
            note="FRED GDP同比小数历史分位，美国经济底座季频背景观察",
        ),
    ]


def _dff_available_frame(frame: pl.DataFrame) -> pl.DataFrame:
    """将 DFF 美国观测日转换为 A 股收盘后可用的日期，再用于历史分位。"""
    dff = _fred_symbol_frame(frame, "DFF")
    if dff.is_empty():
        return dff
    return (
        add_dff_availability_date(dff)
        .rename({"trade_date": "observation_date", "available_date": "trade_date"})
        .select(["trade_date", "_value"])
        .sort("trade_date")
    )
