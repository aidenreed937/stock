"""市场温度计 DataCatalog 派生指标。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import polars as pl

from stock_analytics.catalog_compat import load_dataset_compat
from stock_analytics.pipelines.market_temperature.derived_options import (
    OPTION_RISK_COMPONENT_IDS,
    option_rows,
)
from stock_core.contracts import MarketDataCatalog

if TYPE_CHECKING:
    from datetime import date
    from pathlib import Path

_FS_DATASETS = (
    "sw_2021_fs_non_financial",
    "sw_2021_fs_bank",
    "sw_2021_fs_security",
    "sw_2021_fs_insurance",
)
_POSITIVE_FORECAST_TYPES = {"预增", "略增", "续盈", "扭亏"}
_LIMIT_COMPONENT_IDS = (
    "limit_up_count_temperature",
    "limit_down_count_temperature",
    "limit_up_down_strength_temperature",
    "limit_seal_success_temperature",
)
_OPTION_RISK_COMPONENT_IDS = OPTION_RISK_COMPONENT_IDS
_EXTERNAL_RETURN_WINDOW = 20
_EXTERNAL_COMPONENT_IDS = (
    "macro_sp500_20d_return_temperature",
    "macro_nasdaq_20d_return_temperature",
    "macro_vix_temperature",
    "macro_usd_index_20d_change_temperature",
    "macro_us_10y_temperature",
    "macro_copper_20d_return_temperature",
)
_EXTERNAL_PRESSURE_COMPONENTS = {
    "macro_safe_haven_pressure_temperature": (
        ("macro_gold_20d_return_pressure", False),
        ("macro_vix_temperature", True),
        ("macro_sp500_20d_return_temperature", True),
        ("macro_nasdaq_20d_return_temperature", True),
    ),
    "macro_inflation_pressure_temperature": (
        ("macro_oil_20d_return_pressure", False),
        ("macro_us_10y_temperature", True),
        ("macro_fred_cpi_yoy_temperature", True),
    ),
    "macro_demand_pressure_temperature": (
        ("macro_copper_20d_return_temperature", True),
        ("macro_oil_20d_return_pressure", True),
        ("macro_sp500_20d_return_temperature", True),
        ("macro_nasdaq_20d_return_temperature", True),
    ),
}
_EXTERNAL_PRESSURE_NOTES = {
    "macro_safe_haven_pressure_temperature": (
        "避险压力=黄金上涨、VIX升温、美股下跌压力可用子项等权平均"
    ),
    "macro_inflation_pressure_temperature": (
        "通胀压力=原油上涨、美债收益率上行、美国CPI压力可用子项等权平均"
    ),
    "macro_demand_pressure_temperature": "需求压力=铜、原油、美股走弱压力可用子项等权平均",
}


def collect_derived_metric_rows(
    *,
    as_of_date: date,
    trade_dates: tuple[date, ...],
    storage_dir: Path | str | None = None,
) -> list[dict[str, Any]]:
    """采集不在 MetricEngine 内的基本面与宏观温度事实。"""
    rows: list[dict[str, Any]] = []
    rows.extend(_fundamental_rows(as_of_date, trade_dates, storage_dir))
    rows.extend(_sentiment_rows(as_of_date, storage_dir))
    rows.extend(_macro_liquidity_rows(as_of_date, storage_dir))
    return rows


def _fundamental_rows(
    as_of_date: date,
    trade_dates: tuple[date, ...],
    storage_dir: Path | str | None,
) -> list[dict[str, Any]]:
    from stock_data.catalog import DataCatalog

    cat_lx = DataCatalog(data_source="lixinger", storage_dir=storage_dir)
    cat_ts = DataCatalog(data_source="tushare", storage_dir=storage_dir)
    rows = _financial_statement_rows(cat_lx, as_of_date)
    rows.extend(_forecast_rows(cat_ts, as_of_date, trade_dates))
    rows.extend(_report_revision_rows(cat_ts, as_of_date, trade_dates))
    return rows


def _financial_statement_rows(cat: MarketDataCatalog, as_of_date: date) -> list[dict[str, Any]]:
    frame = _load_financial_statement_frame(cat)
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


def _load_financial_statement_frame(cat: MarketDataCatalog) -> pl.DataFrame:
    frames: list[pl.DataFrame] = []
    for dataset in _FS_DATASETS:
        frame = _load_dataset(cat, dataset)
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
) -> list[dict[str, Any]]:
    start_date = trade_dates[0]
    frame = _load_dataset(
        cat,
        "forecast",
        columns=["symbol", "end_date", "ann_date", "p_change_min", "p_change_max", "type"],
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
) -> list[dict[str, Any]]:
    start_date = trade_dates[0]
    frame = _load_dataset(
        cat,
        "report_rc",
        columns=["symbol", "org_name", "quarter", "report_date", "np"],
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
    revised = latest.join(previous, on=keys, how="inner").filter(
        pl.col("_np") != pl.col("_prev_np")
    )
    if revised.is_empty():
        return [
            _metric_row(
                "fundamental",
                "report_revision_temperature",
                as_of_date,
                None,
                status="insufficient",
                note="最近20个交易日无可比研报上修/下修样本",
            )
        ]
    up_count = revised.filter(pl.col("_np") > pl.col("_prev_np")).height
    down_count = revised.filter(pl.col("_np") < pl.col("_prev_np")).height
    denominator = up_count + down_count
    temperature = up_count / denominator * 100.0 if denominator else None
    return [
        _metric_row(
            "fundamental",
            "report_revision_temperature",
            as_of_date,
            temperature,
            sample_size=denominator,
            note=f"ann_window={start_date}..{as_of_date}; up={up_count}; down={down_count}",
        )
    ]


def _sentiment_rows(as_of_date: date, storage_dir: Path | str | None) -> list[dict[str, Any]]:
    from stock_data.catalog import DataCatalog

    cat_ts = DataCatalog(data_source="tushare", storage_dir=storage_dir)
    cat_lx = DataCatalog(data_source="lixinger", storage_dir=storage_dir)
    rows = _limit_event_rows(cat_ts, as_of_date)
    rows.extend(_investor_account_rows(cat_lx, as_of_date))
    rows.extend(_option_rows(cat_ts, as_of_date))
    return rows


def _investor_account_rows(cat: MarketDataCatalog, as_of_date: date) -> list[dict[str, Any]]:
    frame = _investor_account_frame(_load_dataset(cat, "investor_accounts"))
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


def _limit_event_rows(cat: MarketDataCatalog, as_of_date: date) -> list[dict[str, Any]]:
    frame = _limit_event_daily_frame(_load_dataset(cat, "limit_list_d"))
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


def _option_rows(cat: MarketDataCatalog, as_of_date: date) -> list[dict[str, Any]]:
    return option_rows(cat, as_of_date, _metric_row, _percentile_metric_row)


def _macro_liquidity_rows(
    as_of_date: date,
    storage_dir: Path | str | None,
) -> list[dict[str, Any]]:
    from stock_data.catalog import DataCatalog

    cat_ts = DataCatalog(data_source="tushare", storage_dir=storage_dir)
    cat_lx = DataCatalog(data_source="lixinger", storage_dir=storage_dir)
    cat_yf = DataCatalog(data_source="yfinance", storage_dir=storage_dir)
    cat_av = DataCatalog(data_source="alphavantage", storage_dir=storage_dir)
    cat_fred = DataCatalog(data_source="fred", storage_dir=storage_dir)
    rows: list[dict[str, Any]] = []
    rows.append(
        _percentile_metric_row(
            _load_dataset(cat_lx, "national_debt"),
            "macro_bond_yield_10y_temperature",
            "tcm_y10",
            as_of_date,
            inverse=True,
            note="10年国债收益率历史反向分位",
        )
    )
    rows.append(
        _percentile_metric_row(
            _load_dataset(cat_ts, "shibor"),
            "macro_shibor_on_temperature",
            "on",
            as_of_date,
            inverse=True,
            note="Shibor O/N 历史反向分位",
        )
    )
    rows.extend(_money_credit_rows(cat_ts, cat_lx, as_of_date))
    rows.extend(_external_macro_rows(cat_yf, cat_av, as_of_date))
    rows.extend(_us_macro_background_rows(cat_fred, as_of_date))
    rows.extend(_external_pressure_rows(rows, as_of_date))
    return rows


def _money_credit_rows(
    cat_ts: MarketDataCatalog,
    cat_lx: MarketDataCatalog,
    as_of_date: date,
) -> list[dict[str, Any]]:
    cn_m = _with_month_date(_load_dataset(cat_lx, "cn_m"))
    sf_month = _with_month_date(_load_dataset(cat_lx, "sf_month"))
    cn_cpi = _with_month_date(_load_dataset(cat_ts, "cn_cpi"))
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
    real_rate = _real_rate_frame(_load_dataset(cat_lx, "national_debt"), cn_cpi)
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
) -> list[dict[str, Any]]:
    macro_frame = _load_dataset(cat, "macro_indicators")
    fx_frame = _load_dataset(fx_cat, "macro_indicators")
    index_frame = _load_dataset(cat, "index_daily_bar")
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
            note="铜价20日收益历史分位",
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
    rows.append(_external_environment_row(rows, as_of_date))
    return rows


def _us_macro_background_rows(cat: MarketDataCatalog, as_of_date: date) -> list[dict[str, Any]]:
    frame = _load_dataset(cat, "macro_indicators")
    return [
        _percentile_metric_row(
            _fred_symbol_frame(frame, "T10Y2Y"),
            "macro_fred_t10y2y_temperature",
            "_value",
            as_of_date,
            note="FRED T10Y2Y期限利差历史分位，美国期限结构压力日频背景观察",
        ),
        _percentile_metric_row(
            _fred_symbol_frame(frame, "FEDFUNDS"),
            "macro_fred_fedfunds_temperature",
            "_value",
            as_of_date,
            inverse=True,
            note="FRED FEDFUNDS政策利率历史反向分位，美国政策利率月频背景观察",
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


def _return_percentile_metric_row(
    frame: pl.DataFrame,
    symbol: str,
    metric_id: str,
    as_of_date: date,
    *,
    inverse: bool = False,
    note: str,
) -> dict[str, Any]:
    return_frame = _return_frame(frame, symbol, _EXTERNAL_RETURN_WINDOW)
    row = _percentile_metric_row(
        return_frame,
        metric_id,
        "_return",
        as_of_date,
        inverse=inverse,
        note=note,
    )
    if row["status"] != "ok":
        row["note"] = f"{note}; symbol={symbol}; 本地数据不足或缺失"
    return row


def _return_frame(frame: pl.DataFrame, symbol: str, window: int) -> pl.DataFrame:
    if frame.is_empty() or not {"symbol", "trade_date", "close"}.issubset(frame.columns):
        return pl.DataFrame()
    return (
        frame.filter(pl.col("symbol") == symbol)
        .select(
            "trade_date",
            pl.col("close").cast(pl.Float64, strict=False).alias("_close"),
        )
        .drop_nulls()
        .filter(pl.col("_close") > 0)
        .sort("trade_date")
        .with_columns((pl.col("_close") / pl.col("_close").shift(window) - 1.0).alias("_return"))
        .select("trade_date", "_return")
    )


def _fred_symbol_frame(frame: pl.DataFrame, symbol: str) -> pl.DataFrame:
    if frame.is_empty() or not {"symbol", "trade_date"}.issubset(frame.columns):
        return pl.DataFrame()
    if "value" in frame.columns:
        source_col = "value"
    elif "close" in frame.columns:
        source_col = "close"
    else:
        source_col = ""
    if not source_col:
        return pl.DataFrame()
    return (
        frame.filter(pl.col("symbol") == symbol)
        .select(
            "trade_date",
            pl.col(source_col).cast(pl.Float64, strict=False).alias("_value"),
        )
        .drop_nulls()
        .sort("trade_date")
    )


def _fred_yoy_frame(frame: pl.DataFrame, symbol: str, periods: int) -> pl.DataFrame:
    data = _fred_symbol_frame(frame, symbol)
    if data.is_empty():
        return pl.DataFrame()
    return (
        data.with_columns(pl.col("_value").shift(periods).alias("_prev_value"))
        .with_columns(
            pl.when(pl.col("_prev_value") > 0)
            .then(pl.col("_value") / pl.col("_prev_value") - 1.0)
            .otherwise(None)
            .alias("_yoy")
        )
        .select("trade_date", "_yoy")
    )


def _external_environment_row(rows: list[dict[str, Any]], as_of_date: date) -> dict[str, Any]:
    component_rows = [row for row in rows if row["metric_id"] in _EXTERNAL_COMPONENT_IDS]
    values = [
        float(row["value_float"])
        for row in component_rows
        if row["status"] == "ok" and row["value_float"] is not None
    ]
    missing = [str(row["metric_id"]) for row in component_rows if row["status"] != "ok"]
    note = "外部环境子温度=美股/VIX/美元/美债/铜可用子项等权平均"
    if missing:
        note = f"{note}; missing={','.join(missing)}"
    return _metric_row(
        "macro_liquidity",
        "macro_external_environment_temperature",
        as_of_date,
        sum(values) / len(values) if values else None,
        sample_size=len(values),
        note=note,
    )


def _external_pressure_rows(rows: list[dict[str, Any]], as_of_date: date) -> list[dict[str, Any]]:
    pressure_rows = [
        _external_pressure_component_row(metric_id, rows, as_of_date)
        for metric_id in _EXTERNAL_PRESSURE_COMPONENTS
    ]
    pressure_rows.append(_external_pressure_total_row(pressure_rows, as_of_date))
    return pressure_rows


def _external_pressure_component_row(
    metric_id: str,
    rows: list[dict[str, Any]],
    as_of_date: date,
) -> dict[str, Any]:
    rows_by_metric = {str(row["metric_id"]): row for row in rows}
    values: list[float] = []
    missing: list[str] = []
    for component_id, invert in _EXTERNAL_PRESSURE_COMPONENTS[metric_id]:
        value = _pressure_component_value(rows_by_metric.get(component_id), invert=invert)
        if value is None:
            missing.append(component_id)
        else:
            values.append(value)
    note = _EXTERNAL_PRESSURE_NOTES[metric_id]
    if missing:
        note = f"{note}; missing={','.join(missing)}"
    return _metric_row(
        "macro_liquidity",
        metric_id,
        as_of_date,
        sum(values) / len(values) if values else None,
        sample_size=len(values),
        note=note,
    )


def _external_pressure_total_row(
    pressure_rows: list[dict[str, Any]],
    as_of_date: date,
) -> dict[str, Any]:
    values = [
        float(row["value_float"])
        for row in pressure_rows
        if row["status"] == "ok" and row["value_float"] is not None
    ]
    missing = [str(row["metric_id"]) for row in pressure_rows if row["status"] != "ok"]
    note = "总体外部压力=避险、通胀、需求三类压力可用子项最大值；仅作风险提示，不进入综合温度"
    if missing:
        note = f"{note}; missing={','.join(missing)}"
    return _metric_row(
        "macro_liquidity",
        "macro_external_pressure_temperature",
        as_of_date,
        max(values) if values else None,
        sample_size=len(values),
        note=note,
    )


def _pressure_component_value(row: dict[str, Any] | None, *, invert: bool) -> float | None:
    if row is None or row.get("status") != "ok" or row.get("value_float") is None:
        return None
    value = float(row["value_float"])
    return 100.0 - value if invert else value


def _percentile_metric_row(
    frame: pl.DataFrame,
    metric_id: str,
    value_col: str,
    as_of_date: date,
    *,
    dimension: str = "macro_liquidity",
    date_col: str = "trade_date",
    inverse: bool = False,
    note: str,
) -> dict[str, Any]:
    temp, latest_value, latest_date, sample_size = _percentile_temperature(
        frame,
        value_col,
        as_of_date,
        date_col=date_col,
        inverse=inverse,
    )
    status = "ok" if temp is not None else "insufficient"
    detail = note
    if latest_value is not None and latest_date is not None:
        detail = f"{note}; latest_date={latest_date}; latest_value={latest_value:.6g}"
    return _metric_row(
        dimension,
        metric_id,
        as_of_date,
        temp,
        sample_size=sample_size,
        status=status,
        note=detail,
    )


def _percentile_temperature(
    frame: pl.DataFrame,
    value_col: str,
    as_of_date: date,
    *,
    date_col: str,
    inverse: bool,
) -> tuple[float | None, float | None, date | None, int]:
    if frame.is_empty() or date_col not in frame.columns or value_col not in frame.columns:
        return None, None, None, 0
    data = (
        frame.select(date_col, pl.col(value_col).cast(pl.Float64, strict=False).alias("_value"))
        .drop_nulls()
        .filter(pl.col(date_col) <= as_of_date)
        .sort(date_col)
    )
    if data.is_empty():
        return None, None, None, 0
    latest_value = float(data["_value"][-1])
    values = data["_value"].to_list()
    percentile = sum(1 for value in values if value <= latest_value) / len(values) * 100.0
    temperature = 100.0 - percentile if inverse else percentile
    return _clip_temperature(temperature), latest_value, data[date_col][-1], data.height


def _positive_share(frame: pl.DataFrame, column: str) -> float | None:
    values = frame.select(pl.col(column).cast(pl.Float64, strict=False)).drop_nulls()
    if values.is_empty():
        return None
    return float(values.select((pl.col(column) > 0).mean()).item()) * 100.0


def _historical_median_temperature(
    frame: pl.DataFrame,
    column: str,
    as_of_date: date,
) -> float | None:
    series = (
        frame.filter(pl.col("trade_date") <= as_of_date)
        .group_by("trade_date")
        .agg(pl.col(column).median().alias("_value"))
        .sort("trade_date")
    )
    temp, _, _, _ = _percentile_temperature(
        series,
        "_value",
        as_of_date,
        date_col="trade_date",
        inverse=False,
    )
    return temp


def _with_month_date(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.is_empty() or "month" not in frame.columns:
        return frame
    return frame.with_columns(
        pl.col("month")
        .cast(pl.String)
        .str.strptime(pl.Date, "%Y%m", strict=False)
        .alias("_month_date")
    )


def _with_social_finance_yoy(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.is_empty() or "stk_endval" not in frame.columns:
        return frame
    return (
        frame.sort("_month_date")
        .with_columns(pl.col("stk_endval").shift(12).alias("_sf_stock_prev_year"))
        .with_columns(
            pl.when(pl.col("_sf_stock_prev_year") > 0)
            .then(pl.col("stk_endval") / pl.col("_sf_stock_prev_year") - 1.0)
            .otherwise(None)
            .alias("_sf_stock_yoy")
        )
    )


def _real_rate_frame(debt: pl.DataFrame, cpi: pl.DataFrame) -> pl.DataFrame:
    if debt.is_empty() or cpi.is_empty():
        return pl.DataFrame()
    bond = (
        debt.with_columns(pl.col("trade_date").dt.strftime("%Y%m").alias("month"))
        .sort("trade_date")
        .group_by("month")
        .tail(1)
        .select(
            pl.col("month"),
            pl.col("trade_date").alias("_month_date"),
            pl.col("tcm_y10").cast(pl.Float64, strict=False).alias("_bond_yield_10y"),
        )
    )
    cpi_frame = cpi.select(
        "month",
        pl.col("nt_yoy").cast(pl.Float64, strict=False).alias("_cpi_yoy"),
    )
    return bond.join(cpi_frame, on="month", how="inner").with_columns(
        (pl.col("_bond_yield_10y") - pl.col("_cpi_yoy") / 100.0).alias("_real_rate")
    )


def _parse_compact_date_expr(column: str) -> pl.Expr:
    return pl.col(column).cast(pl.String).str.strptime(pl.Date, "%Y%m%d", strict=False)


def _load_dataset(
    cat: MarketDataCatalog,
    dataset: str,
    columns: list[str] | None = None,
) -> pl.DataFrame:
    try:
        return load_dataset_compat(cat, dataset, columns=columns)
    except Exception:
        return pl.DataFrame()


def _metric_row(
    dimension: str,
    metric_id: str,
    as_of_date: date,
    value: float | None,
    *,
    sample_size: int | None = None,
    status: str = "ok",
    note: str = "",
) -> dict[str, Any]:
    actual_status = status if value is not None else "insufficient"
    return {
        "fact_id": f"metric.{dimension}.{metric_id}",
        "category": "metric_value",
        "dimension": dimension,
        "data_source": "derived",
        "dataset": "",
        "as_of_date": as_of_date,
        "window": 0,
        "metric_id": metric_id,
        "value_float": _clip_temperature(value) if value is not None else None,
        "value_text": "",
        "unit": "temperature",
        "sample_size": sample_size,
        "source": "market_temperature.derived",
        "status": actual_status,
        "note": note,
    }


def _numeric_note_text(value: object) -> str:
    if not isinstance(value, int | float | str):
        return "NA"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "NA"
    return f"{numeric:.6g}"


def _clip_temperature(value: float | None) -> float | None:
    if value is None:
        return None
    return min(100.0, max(0.0, float(value)))
