"""市场温度计情绪派生事实。"""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl

from stock_analytics.pipelines.market_temperature.amount_concentration import (
    amount_top_5pct_daily_frame as _amount_top_5pct_daily_frame,
)
from stock_analytics.pipelines.market_temperature.cache import DatasetFrameCache
from stock_analytics.pipelines.market_temperature.derived_helpers import (
    _load_dataset,
    _metric_row,
    _percentile_metric_row,
)
from stock_analytics.pipelines.market_temperature.derived_options import option_rows
from stock_analytics.pipelines.market_temperature.derived_settlement_iv import settlement_iv_rows
from stock_core.contracts import MarketDataCatalog

if TYPE_CHECKING:
    from datetime import date


_LIMIT_COMPONENT_IDS = (
    "limit_up_count_temperature",
    "limit_down_count_temperature",
    "limit_up_down_strength_temperature",
    "limit_seal_success_temperature",
)

_option_rows = partial(
    option_rows,
    metric_row_factory=_metric_row,
    percentile_factory=_percentile_metric_row,
)


def _sentiment_rows(
    as_of_date: date,
    storage_dir: Path | str | None,
    dataset_cache: DatasetFrameCache | None = None,
    *,
    market_daily: pl.DataFrame | None = None,
    market_daily_option_source_valid: bool | None = None,
    amount_top_5pct_row: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    from stock_data.catalog import DataCatalog

    cat_ts = DataCatalog(data_source="tushare", storage_dir=storage_dir)
    cat_lx = DataCatalog(data_source="lixinger", storage_dir=storage_dir)
    rows = _limit_event_rows(cat_ts, as_of_date, dataset_cache=dataset_cache)
    rows.extend(_investor_account_rows(cat_lx, as_of_date, dataset_cache=dataset_cache))
    rows.extend(
        _option_rows(
            cat_ts,
            as_of_date,
            dataset_cache=dataset_cache,
            market_daily=market_daily,
            market_daily_option_source_valid=market_daily_option_source_valid,
        )
    )
    rows.extend(settlement_iv_rows(as_of_date, storage_dir, _metric_row, _percentile_metric_row))
    if amount_top_5pct_row is not None:
        rows.append(amount_top_5pct_row)
    return rows


def collect_amount_top_5pct_share_rows(
    stock_daily_bar: pl.DataFrame,
    target_dates: tuple[date, ...],
) -> dict[date, dict[str, Any]]:
    """按目标日期批量计算全市场前 5% 个股成交额占比事实。

    该指标是单日横截面比例，不做历史温度化，也不参与六维主温度合成。
    """
    daily = _amount_top_5pct_daily_frame(stock_daily_bar)
    values = {row["trade_date"]: row for row in daily.to_dicts()}
    result: dict[date, dict[str, Any]] = {}
    for target_date in target_dates:
        aggregate = values.get(target_date)
        if aggregate is None:
            result[target_date] = _metric_row(
                "sentiment",
                "amount_top_5pct_share",
                target_date,
                None,
                unit="ratio",
                dataset="stock_daily_bar",
                source="stock_daily_bar.amount",
                sample_size=0,
                status="insufficient",
                note="stock_daily_bar 无该交易日有效成交额，无法计算 Top5% 成交占比",
            )
            continue
        result[target_date] = _metric_row(
            "sentiment",
            "amount_top_5pct_share",
            target_date,
            float(aggregate["_top_share"]),
            unit="ratio",
            dataset="stock_daily_bar",
            source="stock_daily_bar.amount",
            metric_date=target_date,
            sample_size=int(aggregate["_sample_size"]),
            note=(
                "按有效成交额降序取 ceil(有效股票数×5%)，前5%成交额/全市场有效成交额；"
                f"metric_date={target_date.isoformat()}; "
                f"top_count={int(aggregate['_top_count'])}; "
                f"sample_size={int(aggregate['_sample_size'])}"
            ),
        )
    return result


def _investor_account_rows(
    cat: MarketDataCatalog,
    as_of_date: date,
    *,
    dataset_cache: DatasetFrameCache | None = None,
) -> list[dict[str, Any]]:
    frame = _investor_account_frame(
        _load_dataset(
            cat,
            "investor_accounts",
            columns=["trade_date", "nni_m", "n_non_ni_m"],
            end_date=as_of_date,
            dataset_cache=dataset_cache,
        )
    )
    if frame.is_empty():
        return [
            _metric_row(
                "sentiment",
                "investor_account_temperature",
                as_of_date,
                None,
                status="insufficient",
                note="investor_accounts 无可用月度新增投资者记录",
            )
        ]
    return [
        _percentile_metric_row(
            frame,
            "investor_account_temperature",
            "_new_investor_accounts",
            as_of_date,
            dimension="sentiment",
            note="月度新增投资者数历史分位，月频慢情绪指标",
        )
    ]


def _investor_account_frame(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.is_empty() or "trade_date" not in frame.columns:
        return pl.DataFrame()
    columns = [column for column in ("nni_m", "n_non_ni_m") if column in frame.columns]
    if not columns:
        return pl.DataFrame()
    selected = frame.select(
        "trade_date",
        *(pl.col(column).cast(pl.Float64, strict=False).alias(column) for column in columns),
    )
    has_value = pl.any_horizontal([pl.col(column).is_not_null() for column in columns])
    total = sum((pl.col(column).fill_null(0.0) for column in columns), start=pl.lit(0.0))
    return (
        selected.with_columns(
            pl.when(has_value).then(total).otherwise(None).alias("_new_investor_accounts")
        )
        .select("trade_date", "_new_investor_accounts")
        .drop_nulls(subset=["trade_date", "_new_investor_accounts"])
        .sort("trade_date")
    )


def _limit_event_rows(
    cat: MarketDataCatalog,
    as_of_date: date,
    *,
    dataset_cache: DatasetFrameCache | None = None,
) -> list[dict[str, Any]]:
    frame = _limit_event_daily_frame(
        _load_dataset(
            cat,
            "limit_list_d",
            columns=["trade_date", "limit"],
            end_date=as_of_date,
            dataset_cache=dataset_cache,
        )
    )
    if frame.is_empty():
        return [
            _metric_row(
                "sentiment",
                "limit_event_temperature",
                as_of_date,
                None,
                status="insufficient",
                note="limit_list_d 无可用涨跌停事件记录",
            )
        ]
    rows = [
        _percentile_metric_row(
            frame,
            "limit_up_count_temperature",
            "_up_count",
            as_of_date,
            dimension="sentiment",
            note="涨停家数历史分位",
        ),
        _percentile_metric_row(
            frame,
            "limit_down_count_temperature",
            "_down_count",
            as_of_date,
            dimension="sentiment",
            inverse=True,
            note="跌停家数历史反向分位",
        ),
        _percentile_metric_row(
            frame,
            "limit_up_down_strength_temperature",
            "_up_down_ratio",
            as_of_date,
            dimension="sentiment",
            note="涨停/(涨停+跌停)强弱比历史分位",
        ),
        _percentile_metric_row(
            frame,
            "limit_seal_success_temperature",
            "_seal_success_ratio",
            as_of_date,
            dimension="sentiment",
            note="涨停/(涨停+炸板)封板成功率历史分位",
        ),
    ]
    rows.append(_limit_event_temperature_row(rows, frame, as_of_date))
    return rows


def _limit_event_daily_frame(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.is_empty() or not {"trade_date", "limit"}.issubset(frame.columns):
        return pl.DataFrame()
    return (
        frame.select("trade_date", pl.col("limit").cast(pl.String).alias("_limit"))
        .drop_nulls(subset=["trade_date", "_limit"])
        .group_by("trade_date")
        .agg(
            (pl.col("_limit") == "U").sum().cast(pl.Float64).alias("_up_count"),
            (pl.col("_limit") == "D").sum().cast(pl.Float64).alias("_down_count"),
            (pl.col("_limit") == "Z").sum().cast(pl.Float64).alias("_break_count"),
        )
        .with_columns(
            pl.when((pl.col("_up_count") + pl.col("_down_count")) > 0)
            .then(pl.col("_up_count") / (pl.col("_up_count") + pl.col("_down_count")))
            .otherwise(None)
            .alias("_up_down_ratio"),
            pl.when((pl.col("_up_count") + pl.col("_break_count")) > 0)
            .then(pl.col("_up_count") / (pl.col("_up_count") + pl.col("_break_count")))
            .otherwise(None)
            .alias("_seal_success_ratio"),
        )
        .sort("trade_date")
    )


def _limit_event_temperature_row(
    rows: list[dict[str, Any]],
    frame: pl.DataFrame,
    as_of_date: date,
) -> dict[str, Any]:
    component_rows = [row for row in rows if row["metric_id"] in _LIMIT_COMPONENT_IDS]
    values = [
        float(row["value_float"])
        for row in component_rows
        if row["status"] == "ok" and row["value_float"] is not None
    ]
    missing = [str(row["metric_id"]) for row in component_rows if row["status"] != "ok"]
    note = "涨跌停情绪温度=涨停家数/跌停反向/涨跌停强弱/封板成功率可用子项等权平均"
    latest = frame.filter(pl.col("trade_date") <= as_of_date).sort("trade_date").tail(1)
    if not latest.is_empty():
        item = latest.to_dicts()[0]
        note = (
            f"{note}; latest_date={item['trade_date']}; "
            f"up={item['_up_count']:.0f}; down={item['_down_count']:.0f}; "
            f"break={item['_break_count']:.0f}"
        )
    if missing:
        note = f"{note}; missing={','.join(missing)}"
    return _metric_row(
        "sentiment",
        "limit_event_temperature",
        as_of_date,
        sum(values) / len(values) if values else None,
        sample_size=len(values),
        note=note,
    )
