"""市场温度计期权衍生事实提取与聚合。"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import polars as pl

from stock_analytics.catalog_compat import load_dataset_compat
from stock_analytics.pipelines.market_temperature.cache import DatasetFrameCache
from stock_core.contracts import MarketDataCatalog

if TYPE_CHECKING:
    from datetime import date

OPTION_RISK_COMPONENT_IDS = (
    "option_put_call_volume_ratio_temperature",
    "option_put_call_oi_ratio_temperature",
)
_OPTION_RISK_COMPONENT_IDS = OPTION_RISK_COMPONENT_IDS


def _load_dataset(
    cat: MarketDataCatalog,
    dataset: str,
    columns: list[str] | None = None,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    dataset_cache: DatasetFrameCache | None = None,
) -> pl.DataFrame:
    try:
        if dataset_cache is not None:
            return dataset_cache.load(
                cat,
                dataset,
                start_date=start_date,
                end_date=end_date,
                columns=columns,
            )
        return load_dataset_compat(
            cat,
            dataset,
            start_date=start_date,
            end_date=end_date,
            columns=columns,
        )
    except Exception:
        return pl.DataFrame()


def option_rows(
    cat: MarketDataCatalog,
    as_of_date: date,
    metric_row_factory: Any,
    percentile_factory: Any,
    dataset_cache: DatasetFrameCache | None = None,
) -> list[dict[str, Any]]:
    """提取期权成交与持仓衍生温度事实。"""
    storage_dir = getattr(cat, "storage_dir", None)
    if storage_dir is not None:
        with contextlib.suppress(Exception):
            from stock_analytics.features.store import FeatureStore

            mart_path = Path(storage_dir) / "mart"
            mart_df = FeatureStore(mart_dir=mart_path).get_market_daily(
                end_date=as_of_date,
                columns=[
                    "trade_date",
                    "option_put_call_volume_ratio",
                    "option_put_call_oi_ratio",
                    "option_amount",
                    "option_open_interest",
                    "option_near_month_amount_share",
                ],
            )
        source_date = _latest_dataset_date(cat, "opt_daily", as_of_date, dataset_cache)
        mart_date = _latest_non_null_date(mart_df, "option_amount")
        if (
            source_date is not None
            and mart_date == source_date
            and not mart_df.is_empty()
            and "option_amount" in mart_df.columns
        ):
            frame = (
                mart_df.rename(
                    {
                        "option_put_call_volume_ratio": "_put_call_volume_ratio",
                        "option_put_call_oi_ratio": "_put_call_oi_ratio",
                        "option_amount": "_amount",
                        "option_open_interest": "_oi",
                        "option_near_month_amount_share": "_near_month_amount_share",
                    }
                )
                .drop_nulls(subset=["trade_date"])
                .sort("trade_date")
            )
            return _build_option_metric_rows(
                frame,
                as_of_date,
                metric_row_factory,
                percentile_factory,
            )

    daily = _load_dataset(
        cat,
        "opt_daily",
        columns=["symbol", "trade_date", "vol", "amount", "oi"],
        end_date=as_of_date,
        dataset_cache=dataset_cache,
    )
    basic = _load_dataset(
        cat,
        "opt_basic",
        columns=["symbol", "call_put", "s_month"],
        dataset_cache=dataset_cache,
    )
    frame = _option_daily_frame(daily, basic)
    if frame.is_empty():
        return [
            metric_row_factory(
                "sentiment",
                "option_risk_temperature",
                as_of_date,
                None,
                status="insufficient",
                note="opt_daily/opt_basic 无法形成期权成交风险代理；未计算隐含波动率",
            )
        ]
    return _build_option_metric_rows(frame, as_of_date, metric_row_factory, percentile_factory)


def _latest_dataset_date(
    cat: MarketDataCatalog,
    dataset: str,
    as_of_date: date,
    dataset_cache: DatasetFrameCache | None = None,
) -> date | None:
    if hasattr(cat, "latest_trade_dates"):
        latest = cat.latest_trade_dates(dataset, n=1)
        if latest and latest[0] <= as_of_date:
            return latest[0]
    frame = _load_dataset(
        cat,
        dataset,
        columns=["trade_date"],
        end_date=as_of_date,
        dataset_cache=dataset_cache,
    )
    if frame.is_empty() or "trade_date" not in frame.columns:
        return None
    dates = frame.filter(pl.col("trade_date") <= as_of_date)["trade_date"].drop_nulls()
    return cast("date | None", dates.max()) if not dates.is_empty() else None


def _latest_non_null_date(frame: pl.DataFrame, column: str) -> date | None:
    if frame.is_empty() or column not in frame.columns:
        return None
    latest = frame.filter(pl.col(column).is_not_null()).select("trade_date").tail(1)
    return latest["trade_date"][0] if not latest.is_empty() else None


def _build_option_metric_rows(
    frame: pl.DataFrame,
    as_of_date: date,
    metric_row_factory: Any,
    percentile_factory: Any,
) -> list[dict[str, Any]]:
    rows = [
        percentile_factory(
            frame,
            "option_put_call_volume_ratio_temperature",
            "_put_call_volume_ratio",
            as_of_date,
            dimension="sentiment",
            note="认沽/认购成交量比历史分位，高位代表保护性需求或风险偏好下降",
        ),
        percentile_factory(
            frame,
            "option_put_call_oi_ratio_temperature",
            "_put_call_oi_ratio",
            as_of_date,
            dimension="sentiment",
            note="认沽/认购持仓量比历史分位，高位代表保护性持仓需求较强",
        ),
        percentile_factory(
            frame,
            "option_amount_temperature",
            "_amount",
            as_of_date,
            dimension="sentiment",
            note="期权成交额历史分位，只衡量期权市场活跃度",
        ),
        percentile_factory(
            frame,
            "option_open_interest_temperature",
            "_oi",
            as_of_date,
            dimension="sentiment",
            note="期权持仓量历史分位，只衡量期权市场存量活跃度",
        ),
        percentile_factory(
            frame,
            "option_near_month_amount_share_temperature",
            "_near_month_amount_share",
            as_of_date,
            dimension="sentiment",
            note="近月合约成交额占比历史分位，高位代表短期限交易更集中",
        ),
    ]
    rows.append(_option_risk_temperature_row(rows, frame, as_of_date, metric_row_factory))
    return rows


def build_option_daily_frame(daily: pl.DataFrame, basic: pl.DataFrame) -> pl.DataFrame:
    """根据期权日频行情与基础信息构建日度期权聚合宽表。"""
    required_daily = {"symbol", "trade_date", "vol", "amount", "oi"}
    required_basic = {"symbol", "call_put", "s_month"}
    if daily.is_empty() or basic.is_empty():
        return pl.DataFrame()
    if not required_daily.issubset(daily.columns) or not required_basic.issubset(basic.columns):
        return pl.DataFrame()
    basic_frame = basic.select(
        pl.col("symbol").cast(pl.String).alias("symbol"),
        pl.col("call_put").cast(pl.String).alias("_call_put"),
        pl.col("s_month").cast(pl.String).alias("_s_month"),
    ).drop_nulls(subset=["symbol", "_call_put", "_s_month"])
    option_frame = (
        daily.select(
            pl.col("symbol").cast(pl.String).alias("symbol"),
            "trade_date",
            pl.col("vol").cast(pl.Float64, strict=False).alias("_vol"),
            pl.col("amount").cast(pl.Float64, strict=False).alias("_amount"),
            pl.col("oi").cast(pl.Float64, strict=False).alias("_oi"),
        )
        .drop_nulls(subset=["symbol", "trade_date"])
        .join(basic_frame, on="symbol", how="inner")
        .with_columns(pl.col("trade_date").dt.strftime("%Y%m").alias("_trade_month"))
    )
    if option_frame.is_empty():
        return pl.DataFrame()
    near_month = (
        option_frame.filter(pl.col("_s_month") >= pl.col("_trade_month"))
        .group_by("trade_date")
        .agg(pl.col("_s_month").min().alias("_near_month"))
    )
    option_frame = option_frame.join(near_month, on="trade_date", how="left")
    return (
        option_frame.group_by("trade_date")
        .agg(
            pl.when(pl.col("_call_put") == "P")
            .then(pl.col("_vol"))
            .otherwise(0.0)
            .sum()
            .alias("_put_vol"),
            pl.when(pl.col("_call_put") == "C")
            .then(pl.col("_vol"))
            .otherwise(0.0)
            .sum()
            .alias("_call_vol"),
            pl.when(pl.col("_call_put") == "P")
            .then(pl.col("_oi"))
            .otherwise(0.0)
            .sum()
            .alias("_put_oi"),
            pl.when(pl.col("_call_put") == "C")
            .then(pl.col("_oi"))
            .otherwise(0.0)
            .sum()
            .alias("_call_oi"),
            pl.col("_amount").sum().alias("_amount"),
            pl.col("_oi").sum().alias("_oi"),
            pl.when(pl.col("_s_month") == pl.col("_near_month"))
            .then(pl.col("_amount"))
            .otherwise(0.0)
            .sum()
            .alias("_near_month_amount"),
        )
        .with_columns(
            pl.when(pl.col("_call_vol") > 0)
            .then(pl.col("_put_vol") / pl.col("_call_vol"))
            .otherwise(None)
            .alias("_put_call_volume_ratio"),
            pl.when(pl.col("_call_oi") > 0)
            .then(pl.col("_put_oi") / pl.col("_call_oi"))
            .otherwise(None)
            .alias("_put_call_oi_ratio"),
            pl.when(pl.col("_amount") > 0)
            .then(pl.col("_near_month_amount") / pl.col("_amount") * 100.0)
            .otherwise(None)
            .alias("_near_month_amount_share"),
        )
        .sort("trade_date")
    )


def _numeric_note_text(value: object) -> str:
    if not isinstance(value, int | float | str):
        return "NA"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "NA"
    return f"{numeric:.6g}"


def _option_risk_temperature_row(
    rows: list[dict[str, Any]],
    frame: pl.DataFrame,
    as_of_date: date,
    metric_row_factory: Any,
) -> dict[str, Any]:
    component_rows = [row for row in rows if row["metric_id"] in _OPTION_RISK_COMPONENT_IDS]
    values = [
        float(row["value_float"])
        for row in component_rows
        if row["status"] == "ok" and row["value_float"] is not None
    ]
    missing = [str(row["metric_id"]) for row in component_rows if row["status"] != "ok"]
    note = "期权风险温度=认沽/认购成交量比与持仓量比可用子项等权平均；不是隐含波动率"
    latest = frame.filter(pl.col("trade_date") <= as_of_date).sort("trade_date").tail(1)
    if not latest.is_empty():
        item = latest.to_dicts()[0]
        v_pcr = item.get("_put_call_volume_ratio")
        o_pcr = item.get("_put_call_oi_ratio")
        note = (
            f"{note}; latest_date={item['trade_date']}; "
            f"volume_pcr={_numeric_note_text(v_pcr)}; "
            f"oi_pcr={_numeric_note_text(o_pcr)}"
        )
    if missing:
        note = f"{note}; missing={','.join(missing)}"
    return cast(
        "dict[str, Any]",
        metric_row_factory(
            "sentiment",
            "option_risk_temperature",
            as_of_date,
            sum(values) / len(values) if values else None,
            sample_size=len(values),
            note=note,
        ),
    )


_option_daily_frame = build_option_daily_frame

__all__ = [
    "OPTION_RISK_COMPONENT_IDS",
    "_option_daily_frame",
    "build_option_daily_frame",
    "option_rows",
]
