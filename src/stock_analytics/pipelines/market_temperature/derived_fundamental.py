"""市场温度计基本面派生事实。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import polars as pl

from stock_analytics.pipelines.market_temperature.cache import DatasetFrameCache
from stock_analytics.pipelines.market_temperature.derived_helpers import (
    _historical_median_temperature,
    _load_dataset,
    _metric_row,
    _parse_compact_date_expr,
    _positive_share,
)
from stock_core.contracts import MarketDataCatalog

if TYPE_CHECKING:
    from datetime import date


_FS_DATASETS = (
    "sw_2021_fs_non_financial",
    "sw_2021_fs_bank",
    "sw_2021_fs_security",
    "sw_2021_fs_insurance",
)
_POSITIVE_FORECAST_TYPES = {"预增", "略增", "续盈", "扭亏"}
_MIN_REVISION_SAMPLES = 5


def _fundamental_rows(
    as_of_date: date,
    trade_dates: tuple[date, ...],
    storage_dir: Path | str | None,
    dataset_cache: DatasetFrameCache | None = None,
) -> list[dict[str, Any]]:
    from stock_data.catalog import DataCatalog

    cat_lx = DataCatalog(data_source="lixinger", storage_dir=storage_dir)
    cat_ts = DataCatalog(data_source="tushare", storage_dir=storage_dir)
    rows = _financial_statement_rows(cat_lx, as_of_date, dataset_cache=dataset_cache)
    rows.extend(_forecast_rows(cat_ts, as_of_date, trade_dates, dataset_cache=dataset_cache))
    rows.extend(_report_revision_rows(cat_ts, as_of_date, trade_dates, dataset_cache=dataset_cache))
    return rows


def _financial_statement_rows(
    cat: MarketDataCatalog,
    as_of_date: date,
    *,
    dataset_cache: DatasetFrameCache | None = None,
) -> list[dict[str, Any]]:
    frame = _load_financial_statement_frame(cat, dataset_cache=dataset_cache)
    if frame.is_empty():
        return [
            _metric_row(
                "fundamental",
                "fs_profit_growth_temperature",
                as_of_date,
                None,
                status="insufficient",
                note="申万行业财报无可用记录",
            )
        ]
    latest = frame.filter(pl.col("trade_date") <= as_of_date)
    if latest.is_empty():
        return []
    latest_date = cast("date", latest["trade_date"].max())
    latest = latest.filter(pl.col("trade_date") == latest_date)
    stale_days = (as_of_date - latest_date).days
    stale_prefix = f"stale_days={stale_days}; " if stale_days > 0 else ""
    revenue_share = _positive_share(latest, "revenue_ttm_yoy")
    profit_share = _positive_share(latest, "profit_ttm_yoy")
    roe_temperature = _historical_median_temperature(frame, "roe_ttm", as_of_date)
    return [
        _metric_row(
            "fundamental",
            "fs_revenue_growth_temperature",
            as_of_date,
            revenue_share,
            sample_size=latest.height,
            note=f"{stale_prefix}report_date={latest_date}; revenue_positive_share",
        ),
        _metric_row(
            "fundamental",
            "fs_profit_growth_temperature",
            as_of_date,
            profit_share,
            sample_size=latest.height,
            note=f"{stale_prefix}report_date={latest_date}; profit_positive_share",
        ),
        _metric_row(
            "fundamental",
            "fs_roe_temperature",
            as_of_date,
            roe_temperature,
            sample_size=latest.select(pl.col("roe_ttm").drop_nulls()).height,
            note=f"{stale_prefix}report_date={latest_date}; latest_roe_median_history_percentile",
        ),
    ]


def _load_financial_statement_frame(
    cat: MarketDataCatalog,
    *,
    dataset_cache: DatasetFrameCache | None = None,
) -> pl.DataFrame:
    frames: list[pl.DataFrame] = []
    for dataset in _FS_DATASETS:
        frame = _load_dataset(
            cat,
            dataset,
            columns=["trade_date", "symbol", "q"],
            dataset_cache=dataset_cache,
        )
        if frame.is_empty() or "q" not in frame.columns:
            continue
        frames.append(
            frame.select(
                "trade_date",
                "symbol",
                pl.col("q")
                .struct.field("ps")
                .struct.field("toi")
                .struct.field("ttm_y2y")
                .cast(pl.Float64, strict=False)
                .alias("revenue_ttm_yoy"),
                pl.col("q")
                .struct.field("ps")
                .struct.field("np")
                .struct.field("ttm_y2y")
                .cast(pl.Float64, strict=False)
                .alias("profit_ttm_yoy"),
                pl.col("q")
                .struct.field("m")
                .struct.field("roe")
                .struct.field("ttm")
                .cast(pl.Float64, strict=False)
                .alias("roe_ttm"),
            )
        )
    return pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame()


def _forecast_rows(
    cat: MarketDataCatalog,
    as_of_date: date,
    trade_dates: tuple[date, ...],
    *,
    dataset_cache: DatasetFrameCache | None = None,
) -> list[dict[str, Any]]:
    start_date = trade_dates[0]
    frame = _load_dataset(
        cat,
        "forecast",
        columns=["symbol", "end_date", "ann_date", "p_change_min", "p_change_max", "type"],
        dataset_cache=dataset_cache,
    )
    if frame.is_empty():
        return [
            _metric_row(
                "fundamental",
                "forecast_positive_temperature",
                as_of_date,
                None,
                status="insufficient",
                note="forecast 无可用记录",
            )
        ]
    frame = (
        frame.with_columns(_parse_compact_date_expr("ann_date").alias("_ann_date"))
        .filter((pl.col("_ann_date") >= start_date) & (pl.col("_ann_date") <= as_of_date))
        .sort(["symbol", "end_date", "_ann_date"])
        .unique(subset=["symbol", "end_date"], keep="last")
        .with_columns(
            pl.mean_horizontal(
                pl.col("p_change_min").cast(pl.Float64, strict=False),
                pl.col("p_change_max").cast(pl.Float64, strict=False),
            ).alias("_p_change_mid")
        )
        .with_columns(
            (
                (pl.col("_p_change_mid") > 0)
                | pl.col("type").cast(pl.String).is_in(_POSITIVE_FORECAST_TYPES)
            ).alias("_positive")
        )
    )
    if frame.is_empty():
        return [
            _metric_row(
                "fundamental",
                "forecast_positive_temperature",
                as_of_date,
                None,
                status="insufficient",
                note="最近20个交易日无业绩预告样本",
            )
        ]
    positive_share = frame.select(pl.col("_positive").mean()).item()
    median_change = frame.select(pl.col("_p_change_mid").median()).item()
    note = f"ann_window={start_date}..{as_of_date}; p_change_mid_median={median_change}"
    return [
        _metric_row(
            "fundamental",
            "forecast_positive_temperature",
            as_of_date,
            float(positive_share) * 100.0 if positive_share is not None else None,
            sample_size=frame.height,
            note=note,
        )
    ]


def _report_revision_rows(
    cat: MarketDataCatalog,
    as_of_date: date,
    trade_dates: tuple[date, ...],
    *,
    dataset_cache: DatasetFrameCache | None = None,
) -> list[dict[str, Any]]:
    start_date = trade_dates[0]
    frame = _load_dataset(
        cat,
        "report_rc",
        columns=["symbol", "org_name", "quarter", "report_date", "np"],
        dataset_cache=dataset_cache,
    )
    required = {"symbol", "org_name", "quarter", "report_date", "np"}
    if frame.is_empty() or not required.issubset(frame.columns):
        return [
            _metric_row(
                "fundamental",
                "report_revision_temperature",
                as_of_date,
                None,
                status="insufficient",
                note="report_rc 缺少上修比例所需字段",
            )
        ]
    keys = ["symbol", "org_name", "quarter"]
    base = (
        frame.select(
            *keys,
            _parse_compact_date_expr("report_date").alias("_report_date"),
            pl.col("np").cast(pl.Float64, strict=False).alias("_np"),
        )
        .drop_nulls(subset=[*keys, "_report_date", "_np"])
        .filter(pl.col("_report_date") <= as_of_date)
        .sort([*keys, "_report_date"])
    )
    latest = base.filter(pl.col("_report_date") >= start_date).group_by(keys).tail(1)
    previous = (
        base.filter(pl.col("_report_date") < start_date)
        .group_by(keys)
        .tail(1)
        .rename({"_np": "_prev_np", "_report_date": "_prev_report_date"})
    )
    comparable = latest.join(previous, on=keys, how="inner")
    denominator = comparable.height
    up_count = comparable.filter(pl.col("_np") > pl.col("_prev_np")).height
    down_count = comparable.filter(pl.col("_np") < pl.col("_prev_np")).height
    unchanged_count = denominator - up_count - down_count
    note = (
        f"ann_window={start_date}..{as_of_date}; up={up_count}; down={down_count}; "
        f"unchanged={unchanged_count}; total={denominator}"
    )
    if denominator < _MIN_REVISION_SAMPLES:
        note = f"{note}; insufficient_samples"
        temperature = None
    else:
        temperature = 50.0 + (up_count - down_count) / denominator * 50.0
    return [
        _metric_row(
            "fundamental",
            "report_revision_temperature",
            as_of_date,
            temperature,
            sample_size=denominator,
            note=note,
        )
    ]
