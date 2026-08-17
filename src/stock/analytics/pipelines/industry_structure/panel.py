"""行业结构分析面板构建。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from math import isfinite
from typing import TYPE_CHECKING, Any, cast

import polars as pl

from stock.analytics.industry.classifier import IndustryClassifier
from stock.analytics.industry.pb_roe import IndustryPBROEAnalyzer
from stock.data.catalog import DataCatalog

if TYPE_CHECKING:
    from pathlib import Path

    from stock.analytics.pipelines.industry_structure.config import IndustryStructureConfig

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

_FS_DATASETS = (
    "sw_2021_fs_non_financial",
    "sw_2021_fs_bank",
    "sw_2021_fs_security",
    "sw_2021_fs_insurance",
)


@dataclass(frozen=True, slots=True)
class _FastFundamentalContext:
    config: IndustryStructureConfig
    as_of_date: date
    trade_dates: tuple[date, ...]
    industry_codes: list[object]


@dataclass(frozen=True, slots=True)
class _IndustryMoneyflowContext:
    config: IndustryStructureConfig
    as_of_date: date
    trade_dates: tuple[date, ...]
    industry_codes: list[object]


def empty_industry_panel() -> pl.DataFrame:
    """返回稳定 schema 的空行业面板。"""
    return pl.DataFrame(schema=BASE_PANEL_SCHEMA)


def build_industry_panel(
    config: IndustryStructureConfig,
    *,
    as_of_date: date,
    trade_dates: tuple[date, ...],
    storage_dir: Path | str | None = None,
) -> pl.DataFrame:
    """构建每个申万一级行业一行的结构分析基础面板。"""
    cat_ts = DataCatalog(data_source="tushare", storage_dir=storage_dir)
    cat_lx = DataCatalog(data_source="lixinger", storage_dir=storage_dir)
    start_date = _panel_start_date(config, as_of_date, trade_dates)
    raw_sw = _load_dataset(
        cat_ts,
        "sw_daily",
        start_date=start_date,
        end_date=as_of_date,
    )
    daily = _industry_daily_frame(raw_sw, config, cat_ts)
    market_panel = _market_panel(daily, config, as_of_date, cat_ts)
    if market_panel.is_empty():
        return empty_industry_panel()

    _, industry_to_l1 = _industry_l1_maps(cat_ts, config)
    valuation = _valuation_panel(cat_lx, as_of_date, industry_to_l1)
    fundamentals = _fundamental_panel(cat_lx, as_of_date, industry_to_l1)
    fast_fundamentals = _fast_fundamental_panel(
        cat_ts,
        cat_lx,
        _FastFundamentalContext(
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
    moneyflow = _industry_moneyflow_panel(
        cat_ts,
        cat_lx,
        _IndustryMoneyflowContext(
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
    catalog: DataCatalog,
) -> pl.DataFrame:
    required = {"symbol", "trade_date", "close"}
    if frame.is_empty() or not required.issubset(frame.columns):
        return pl.DataFrame()
    amount_expr = (
        pl.col("amount").cast(pl.Float64, strict=False)
        if "amount" in frame.columns
        else pl.lit(None, dtype=pl.Float64)
    )
    base = frame.select(
        pl.col("symbol").cast(pl.String).alias("industry_code"),
        "trade_date",
        _optional_text_expr(frame, ("name", "industry_name", "index_name"), "_sw_industry_name"),
        pl.col("close").cast(pl.Float64, strict=False).alias("close"),
        amount_expr.alias("amount"),
    ).drop_nulls(subset=["industry_code", "trade_date", "close"])
    base = base.filter(pl.col("close") > 0).sort(["industry_code", "trade_date"])
    classifier = IndustryClassifier(catalog)
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


def _market_panel(
    daily: pl.DataFrame,
    config: IndustryStructureConfig,
    as_of_date: date,
    catalog: DataCatalog,
) -> pl.DataFrame:
    if daily.is_empty():
        return pl.DataFrame()
    windows = tuple(sorted({5, 10, 20, 60, 120, *config.windows}))
    daily = _with_return_columns(daily, windows)
    daily = _with_market_columns(daily, config.main_window)
    latest_date = cast(
        "date | None",
        daily.filter(pl.col("trade_date") <= as_of_date)["trade_date"].max(),
    )
    if latest_date is None:
        return pl.DataFrame()
    latest = daily.filter(pl.col("trade_date") == latest_date)
    benchmark_return = _benchmark_return_20d(catalog, config.benchmark, as_of_date)
    if benchmark_return is None:
        benchmark_return = _median_value(latest, "return_20d")
    rows = []
    for row in latest.to_dicts():
        code = str(row["industry_code"])
        tcr_history = daily.filter(pl.col("industry_code") == code)["tcr"].to_list()
        current_tcr = _as_float(row.get("tcr"))
        return_20d = _as_float(row.get("return_20d"))
        row["as_of_date"] = as_of_date
        row["market_data_date"] = latest_date
        row["amount_yi"] = _divide(row.get("amount"), 1e8)
        row["tcr_percentile"] = _historical_percentile(tcr_history, current_tcr)
        row["relative_return_20d"] = (
            return_20d - benchmark_return
            if return_20d is not None and benchmark_return is not None
            else None
        )
        rows.append(row)
    return pl.DataFrame(rows) if rows else pl.DataFrame()


def _with_return_columns(daily: pl.DataFrame, windows: tuple[int, ...]) -> pl.DataFrame:
    expressions = [
        (
            (pl.col("close") / pl.col("close").shift(window).over("industry_code") - 1.0) * 100.0
        ).alias(f"return_{window}d")
        for window in windows
    ]
    return daily.with_columns(expressions)


def _with_market_columns(daily: pl.DataFrame, main_window: int) -> pl.DataFrame:
    daily = daily.with_columns(
        pl.col("close").rolling_mean(main_window).over("industry_code").alias("_ma_main")
    )
    daily = daily.with_columns(
        pl.when(pl.col("_ma_main") > 0)
        .then((pl.col("close") / pl.col("_ma_main") - 1.0) * 100.0)
        .otherwise(None)
        .alias("ma_bias_20d"),
        pl.when(pl.col("amount").sum().over("trade_date") > 0)
        .then(pl.col("amount") / pl.col("amount").sum().over("trade_date") * 100.0)
        .otherwise(None)
        .alias("_amount_share"),
    )
    return daily.with_columns(
        pl.col("_amount_share").rolling_mean(main_window).over("industry_code").alias("tcr")
    ).drop("_ma_main", "_amount_share")


def _valuation_panel(
    cat: DataCatalog,
    as_of_date: date,
    industry_to_l1: dict[str, str],
) -> pl.DataFrame:
    start_date = as_of_date - timedelta(days=365 * 5)
    raw = _load_dataset(
        cat,
        "sw_2021_fundamental",
        start_date=start_date,
        end_date=as_of_date,
    )
    if raw.is_empty() or not {"symbol", "trade_date"}.issubset(raw.columns):
        return pl.DataFrame()
    base = raw.select(
        pl.col("symbol")
        .cast(pl.String)
        .map_elements(lambda value: _map_l1_code(value, industry_to_l1), return_dtype=pl.Utf8)
        .alias("industry_code"),
        "trade_date",
        _optional_text_expr(raw, ("name", "industry_name"), "industry_name_from_valuation"),
        _optional_numeric_expr(
            raw,
            ("pe_ttm.ew", "pe_ttm.mcw", "pe_ttm", "pe", "pe_ew"),
            "pe_ttm",
        ),
        _optional_numeric_expr(raw, ("pb.ew", "pb.mcw", "pb", "pb_ew"), "pb"),
        _optional_numeric_expr(
            raw,
            ("dyr.ew", "dyr.mcw", "dividend_yield", "dv_ttm"),
            "dividend_yield",
        ),
    ).drop_nulls(subset=["industry_code", "trade_date"])
    base = _collapse_industry_daily_values(
        base,
        ("pe_ttm", "pb", "dividend_yield"),
    )
    history = base.filter(pl.col("trade_date") <= as_of_date).sort(["industry_code", "trade_date"])
    if history.is_empty():
        return pl.DataFrame()
    latest = history.group_by("industry_code").tail(1)
    pbroe_by_symbol = _pb_roe_by_l1_symbol(raw, as_of_date, cat, industry_to_l1)
    rows = []
    for row in latest.to_dicts():
        code = str(row["industry_code"])
        industry_history = history.filter(pl.col("industry_code") == code)
        row["valuation_date"] = row["trade_date"]
        row["pe_percentile_5y"] = _historical_percentile(
            industry_history["pe_ttm"].to_list(), _as_float(row.get("pe_ttm"))
        )
        row["pb_percentile_5y"] = _historical_percentile(
            industry_history["pb"].to_list(), _as_float(row.get("pb"))
        )
        pbroe = pbroe_by_symbol.get(code, {})
        row["pbroe_residual"] = _as_float(pbroe.get("residual"))
        row["pbroe_undervalued"] = bool(pbroe.get("is_undervalued", False))
        rows.append(row)
    return pl.DataFrame(rows).select(
        "industry_code",
        "industry_name_from_valuation",
        "valuation_date",
        "pe_ttm",
        "pb",
        "dividend_yield",
        "pe_percentile_5y",
        "pb_percentile_5y",
        "pbroe_residual",
        "pbroe_undervalued",
    )


def _pb_roe_by_symbol(
    raw: pl.DataFrame,
    as_of_date: date,
    catalog: DataCatalog,
) -> dict[str, dict[str, Any]]:
    try:
        result = IndustryPBROEAnalyzer(catalog=catalog).analyze_cross_section(
            target_date=as_of_date,
            val_df=raw,
        )
    except Exception:
        return {}
    if result is None:
        return {}
    return {str(row["symbol"]): row for row in result.industries}


def _pb_roe_by_l1_symbol(
    raw: pl.DataFrame,
    as_of_date: date,
    catalog: DataCatalog,
    industry_to_l1: dict[str, str],
) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    for symbol, data in _pb_roe_by_symbol(raw, as_of_date, catalog).items():
        l1_code = _map_l1_code(symbol, industry_to_l1)
        if l1_code:
            mapped[l1_code] = data
    return mapped


def _fundamental_panel(
    cat: DataCatalog,
    as_of_date: date,
    industry_to_l1: dict[str, str],
) -> pl.DataFrame:
    frame = _financial_statement_history(cat, as_of_date)
    if frame.is_empty():
        return pl.DataFrame()
    frame = frame.with_columns(
        pl.col("industry_code")
        .map_elements(lambda value: _map_l1_code(value, industry_to_l1), return_dtype=pl.Utf8)
        .alias("industry_code")
    ).drop_nulls(subset=["industry_code"])
    frame = _collapse_industry_daily_values(
        frame,
        ("revenue_growth_ttm", "profit_growth_ttm", "roe_ttm"),
    )
    history = frame.filter(pl.col("trade_date") <= as_of_date).sort(["industry_code", "trade_date"])
    if history.is_empty():
        return pl.DataFrame()
    latest = history.group_by("industry_code").tail(1)
    rows = []
    for row in latest.to_dicts():
        code = str(row["industry_code"])
        industry_history = history.filter(pl.col("industry_code") == code)
        row["fundamental_date"] = row["trade_date"]
        row["revenue_growth_percentile"] = _historical_percentile(
            industry_history["revenue_growth_ttm"].to_list(),
            _as_float(row.get("revenue_growth_ttm")),
        )
        row["profit_growth_percentile"] = _historical_percentile(
            industry_history["profit_growth_ttm"].to_list(),
            _as_float(row.get("profit_growth_ttm")),
        )
        row["roe_percentile"] = _historical_percentile(
            industry_history["roe_ttm"].to_list(), _as_float(row.get("roe_ttm"))
        )
        rows.append(row)
    return pl.DataFrame(rows).select(
        "industry_code",
        "fundamental_date",
        "revenue_growth_ttm",
        "profit_growth_ttm",
        "roe_ttm",
        "revenue_growth_percentile",
        "profit_growth_percentile",
        "roe_percentile",
    )


def _financial_statement_history(cat: DataCatalog, as_of_date: date) -> pl.DataFrame:
    frames: list[pl.DataFrame] = []
    for dataset in _FS_DATASETS:
        raw = _load_dataset(
            cat,
            dataset,
            start_date=as_of_date - timedelta(days=365 * 6),
            end_date=as_of_date,
        )
        extracted = _extract_fs_frame(raw)
        if not extracted.is_empty():
            frames.append(extracted)
    return pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame()


def _extract_fs_frame(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.is_empty() or not {"symbol", "trade_date"}.issubset(frame.columns):
        return pl.DataFrame()
    if "q" in frame.columns:
        try:
            return frame.select(
                pl.col("symbol").cast(pl.String).alias("industry_code"),
                "trade_date",
                pl.col("q")
                .struct.field("ps")
                .struct.field("toi")
                .struct.field("ttm_y2y")
                .cast(pl.Float64, strict=False)
                .alias("revenue_growth_ttm"),
                pl.col("q")
                .struct.field("ps")
                .struct.field("np")
                .struct.field("ttm_y2y")
                .cast(pl.Float64, strict=False)
                .alias("profit_growth_ttm"),
                pl.col("q")
                .struct.field("m")
                .struct.field("roe")
                .struct.field("ttm")
                .cast(pl.Float64, strict=False)
                .alias("roe_ttm"),
            ).drop_nulls(subset=["industry_code", "trade_date"])
        except Exception:
            return _extract_fs_frame_from_columns(frame)
    return _extract_fs_frame_from_columns(frame)


def _extract_fs_frame_from_columns(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.select(
        pl.col("symbol").cast(pl.String).alias("industry_code"),
        "trade_date",
        _optional_numeric_expr(
            frame,
            (
                "revenue_growth_ttm",
                "revenue_ttm_yoy",
                "ps.toi.ttm_y2y",
                "ps.toi.c_y2y",
                "toi_ttm_yoy",
            ),
            "revenue_growth_ttm",
        ),
        _optional_numeric_expr(
            frame,
            (
                "profit_growth_ttm",
                "profit_ttm_yoy",
                "ps.np.ttm_y2y",
                "ps.np.c_y2y",
                "np_ttm_yoy",
            ),
            "profit_growth_ttm",
        ),
        _optional_numeric_expr(frame, ("roe_ttm", "m.roe.ttm", "roe.ttm", "roe"), "roe_ttm"),
    ).drop_nulls(subset=["industry_code", "trade_date"])


def _fast_fundamental_panel(
    cat_ts: DataCatalog,
    cat_lx: DataCatalog,
    context: _FastFundamentalContext,
) -> pl.DataFrame:
    codes = [str(value) for value in context.industry_codes if value is not None]
    if not codes:
        return pl.DataFrame()
    stock_map = _stock_industry_map(cat_ts, cat_lx, context.config, context.as_of_date)
    if stock_map.is_empty():
        return pl.DataFrame({"industry_code": codes})
    if len(context.trade_dates) >= context.config.main_window:
        window_start = context.trade_dates[-context.config.main_window]
    else:
        window_start = context.trade_dates[0]
    target_period = _latest_completed_report_period(context.as_of_date)
    panel = pl.DataFrame({"industry_code": codes})
    for frame in (
        _forecast_panel(cat_ts, stock_map, window_start, context.as_of_date, target_period),
        _express_panel(cat_ts, stock_map, window_start, context.as_of_date, target_period),
        _report_revision_panel(cat_ts, stock_map, window_start, context.as_of_date),
    ):
        if not frame.is_empty():
            panel = panel.join(frame, on="industry_code", how="left")
    return panel


def _forecast_panel(
    catalog: DataCatalog,
    stock_map: pl.DataFrame,
    window_start: date,
    as_of_date: date,
    target_period: date,
) -> pl.DataFrame:
    raw = _load_dataset(catalog, "forecast")
    if raw.is_empty() or not {"symbol", "ann_date"}.issubset(raw.columns):
        return pl.DataFrame()
    positive_labels = ("预增", "略增", "续盈", "扭亏")
    base = raw.select(
        pl.col("symbol").cast(pl.String).str.slice(0, 6).alias("stock_key"),
        _date_column_expr(raw, "ann_date", "ann_date"),
        _date_column_expr(raw, "end_date", "end_date"),
        _optional_text_expr(raw, ("type",), "type"),
        _optional_numeric_expr(raw, ("p_change_min",), "p_change_min"),
        _optional_numeric_expr(raw, ("p_change_max",), "p_change_max"),
    ).drop_nulls(subset=["stock_key", "ann_date"])
    base = base.filter((pl.col("ann_date") >= window_start) & (pl.col("ann_date") <= as_of_date))
    base = _filter_target_period_if_available(base, "end_date", target_period)
    if base.is_empty():
        return pl.DataFrame()
    base = base.with_columns(_midpoint_expr("p_change_min", "p_change_max").alias("_p_change_mid"))
    base = base.with_columns(
        pl.when(pl.col("_p_change_mid").is_not_null())
        .then((pl.col("_p_change_mid") > 0).cast(pl.Int64))
        .otherwise(pl.col("type").is_in(positive_labels).cast(pl.Int64))
        .alias("_positive")
    )
    base = (
        base.sort(["stock_key", "end_date", "ann_date"]).group_by(["stock_key", "end_date"]).tail(1)
    )
    joined = base.join(stock_map, on="stock_key", how="inner")
    if joined.is_empty():
        return pl.DataFrame()
    return joined.group_by("industry_code").agg(
        pl.col("ann_date").max().alias("forecast_date"),
        pl.col("stock_key").n_unique().alias("forecast_sample_size"),
        (pl.col("_positive").mean() * 100.0).alias("forecast_positive_share"),
        pl.col("_p_change_mid").median().alias("forecast_p_change_mid_median"),
    )


def _express_panel(
    catalog: DataCatalog,
    stock_map: pl.DataFrame,
    window_start: date,
    as_of_date: date,
    target_period: date,
) -> pl.DataFrame:
    raw = _load_dataset(catalog, "express")
    if raw.is_empty() or not {"symbol", "ann_date"}.issubset(raw.columns):
        return pl.DataFrame()
    base = raw.select(
        pl.col("symbol").cast(pl.String).str.slice(0, 6).alias("stock_key"),
        _date_column_expr(raw, "ann_date", "ann_date"),
        _date_column_expr(raw, "end_date", "end_date"),
        _optional_numeric_expr(raw, ("n_income",), "n_income"),
        _optional_numeric_expr(raw, ("yoy_net_profit",), "_prior_net_profit"),
        _optional_numeric_expr(raw, ("diluted_roe",), "diluted_roe"),
    ).drop_nulls(subset=["stock_key", "ann_date"])
    base = base.filter((pl.col("ann_date") >= window_start) & (pl.col("ann_date") <= as_of_date))
    base = _filter_target_period_if_available(base, "end_date", target_period)
    if base.is_empty():
        return pl.DataFrame()
    base = base.with_columns(
        pl.when(pl.col("n_income").is_not_null() & (pl.col("_prior_net_profit") > 0))
        .then((pl.col("n_income") / pl.col("_prior_net_profit") - 1.0) * 100.0)
        .otherwise(None)
        .alias("_profit_growth")
    )
    base = (
        base.sort(["stock_key", "end_date", "ann_date"]).group_by(["stock_key", "end_date"]).tail(1)
    )
    joined = base.join(stock_map, on="stock_key", how="inner")
    if joined.is_empty():
        return pl.DataFrame()
    return joined.group_by("industry_code").agg(
        pl.col("ann_date").max().alias("express_date"),
        pl.col("stock_key").n_unique().alias("express_sample_size"),
        pl.col("_profit_growth").median().alias("express_profit_growth_median"),
        pl.col("diluted_roe").median().alias("express_roe_median"),
    )


def _report_revision_panel(
    catalog: DataCatalog,
    stock_map: pl.DataFrame,
    window_start: date,
    as_of_date: date,
) -> pl.DataFrame:
    raw = _load_dataset(catalog, "report_rc")
    required = {"symbol", "report_date", "org_name", "quarter", "np"}
    if raw.is_empty() or not required.issubset(raw.columns):
        return pl.DataFrame()
    base = raw.select(
        pl.col("symbol").cast(pl.String).str.slice(0, 6).alias("stock_key"),
        _date_column_expr(raw, "report_date", "report_date"),
        pl.col("org_name").cast(pl.String).alias("org_name"),
        pl.col("quarter").cast(pl.String).alias("quarter"),
        pl.col("np").cast(pl.Float64, strict=False).alias("np"),
    ).drop_nulls(subset=["stock_key", "report_date", "org_name", "quarter", "np"])
    base = base.filter(pl.col("report_date") <= as_of_date).sort(
        ["stock_key", "org_name", "quarter", "report_date"]
    )
    if base.is_empty():
        return pl.DataFrame()
    base = base.with_columns(
        pl.col("np").shift(1).over(["stock_key", "org_name", "quarter"]).alias("_prev_np")
    )
    window = base.filter(pl.col("report_date") >= window_start).drop_nulls(subset=["_prev_np"])
    if window.is_empty():
        return pl.DataFrame()
    window = window.with_columns(
        (pl.col("np") > pl.col("_prev_np")).cast(pl.Int64).alias("_up"),
        (pl.col("np") < pl.col("_prev_np")).cast(pl.Int64).alias("_down"),
    )
    revisions = window.filter((pl.col("_up") + pl.col("_down")) > 0)
    joined = revisions.join(stock_map, on="stock_key", how="inner")
    if joined.is_empty():
        return pl.DataFrame()
    grouped = joined.group_by("industry_code").agg(
        pl.col("report_date").max().alias("report_rc_date"),
        pl.len().alias("report_rc_sample_size"),
        pl.col("_up").sum().alias("report_rc_up_count"),
        pl.col("_down").sum().alias("report_rc_down_count"),
    )
    return grouped.with_columns(
        pl.when((pl.col("report_rc_up_count") + pl.col("report_rc_down_count")) > 0)
        .then(
            pl.col("report_rc_up_count")
            / (pl.col("report_rc_up_count") + pl.col("report_rc_down_count"))
            * 100.0
        )
        .otherwise(None)
        .alias("report_rc_revision_ratio")
    )


def _industry_moneyflow_panel(
    cat_ts: DataCatalog,
    cat_lx: DataCatalog,
    context: _IndustryMoneyflowContext,
) -> pl.DataFrame:
    config = context.config
    as_of_date = context.as_of_date
    trade_dates = context.trade_dates
    industry_codes = context.industry_codes
    codes = [str(value) for value in industry_codes if value is not None]
    if not codes or not trade_dates:
        return pl.DataFrame()
    stock_map = _stock_industry_map(cat_ts, cat_lx, config, as_of_date)
    if stock_map.is_empty():
        return pl.DataFrame({"industry_code": codes})
    window_dates = trade_dates[-config.main_window :]
    window_start = window_dates[0]
    flow = _moneyflow_base_frame(cat_ts, window_start, as_of_date)
    if flow.is_empty():
        return pl.DataFrame({"industry_code": codes})
    bars = _stock_amount_frame(cat_ts, window_start, as_of_date)
    joined = flow.join(stock_map, on="stock_key", how="inner").filter(
        pl.col("industry_code").is_in(codes)
    )
    if joined.is_empty():
        return pl.DataFrame({"industry_code": codes})
    if not bars.is_empty():
        joined = joined.join(bars, on=["stock_key", "trade_date"], how="left")
    if "_amount" not in joined.columns:
        joined = joined.with_columns(pl.lit(None, dtype=pl.Float64).alias("_amount"))
    latest_flow_date = cast("date", joined["trade_date"].max())
    valid_dates = sorted(
        {value for value in joined["trade_date"].to_list() if value <= latest_flow_date}
    )
    recent5 = set(valid_dates[-5:])
    grouped = (
        joined.with_columns(pl.col("trade_date").is_in(recent5).alias("_is_recent5"))
        .group_by("industry_code")
        .agg(
            pl.col("trade_date").max().alias("moneyflow_date"),
            pl.len().alias("moneyflow_sample_size"),
            pl.col("stock_key").n_unique().alias("moneyflow_stock_count"),
            pl.col("_net_amount").sum().alias("_net_20d"),
            pl.col("_large_net_amount").sum().alias("_large_net_20d"),
            pl.col("_amount").sum().alias("_amount_20d"),
            pl.col("_net_amount").drop_nulls().len().alias("_net_count_20d"),
            pl.col("_amount").drop_nulls().len().alias("_amount_count_20d"),
            pl.when(pl.col("_is_recent5"))
            .then(pl.col("_net_amount"))
            .otherwise(0.0)
            .sum()
            .alias("_net_5d"),
            pl.when(pl.col("_is_recent5"))
            .then(pl.col("_amount"))
            .otherwise(0.0)
            .sum()
            .alias("_amount_5d"),
            pl.when(pl.col("_is_recent5"))
            .then(pl.col("_net_amount"))
            .otherwise(None)
            .drop_nulls()
            .len()
            .alias("_net_count_5d"),
            pl.when(pl.col("_is_recent5"))
            .then(pl.col("_amount"))
            .otherwise(None)
            .drop_nulls()
            .len()
            .alias("_amount_count_5d"),
        )
        .with_columns(
            pl.when(pl.col("_net_count_20d") > 0)
            .then(pl.col("_net_20d") / 1e8)
            .otherwise(None)
            .alias("money_net_inflow_yi_20d"),
            pl.when(
                (pl.col("_net_count_20d") > 0)
                & (pl.col("_amount_count_20d") > 0)
                & (pl.col("_amount_20d") > 0)
            )
            .then(pl.col("_net_20d") / pl.col("_amount_20d") * 100.0)
            .otherwise(None)
            .alias("money_net_inflow_share_20d"),
            pl.when((pl.col("_amount_count_20d") > 0) & (pl.col("_amount_20d") > 0))
            .then(pl.col("_large_net_20d") / pl.col("_amount_20d") * 100.0)
            .otherwise(None)
            .alias("large_money_net_inflow_share_20d"),
            pl.when(
                (pl.col("_net_count_5d") > 0)
                & (pl.col("_amount_count_5d") > 0)
                & (pl.col("_amount_5d") > 0)
            )
            .then(pl.col("_net_5d") / pl.col("_amount_5d") * 100.0)
            .otherwise(None)
            .alias("money_net_inflow_share_5d"),
        )
    )
    return grouped.select(
        "industry_code",
        "moneyflow_date",
        "moneyflow_sample_size",
        "moneyflow_stock_count",
        "money_net_inflow_yi_20d",
        "money_net_inflow_share_20d",
        "large_money_net_inflow_share_20d",
        "money_net_inflow_share_5d",
    )


def _moneyflow_base_frame(
    catalog: DataCatalog,
    start_date: date,
    as_of_date: date,
) -> pl.DataFrame:
    raw = _load_dataset(catalog, "moneyflow", start_date=start_date, end_date=as_of_date)
    required = {"symbol", "trade_date"}
    if raw.is_empty() or not required.issubset(raw.columns):
        return pl.DataFrame()
    buy_large = _sum_optional_columns(raw, ("buy_lg_amount", "buy_elg_amount"))
    sell_large = _sum_optional_columns(raw, ("sell_lg_amount", "sell_elg_amount"))
    return raw.select(
        pl.col("symbol").cast(pl.String).str.slice(0, 6).alias("stock_key"),
        "trade_date",
        _optional_numeric_expr(raw, ("net_mf_amount",), "_net_amount"),
        (buy_large - sell_large).alias("_large_net_amount"),
    ).drop_nulls(subset=["stock_key", "trade_date"])


def _stock_amount_frame(
    catalog: DataCatalog,
    start_date: date,
    as_of_date: date,
) -> pl.DataFrame:
    raw = _load_dataset(catalog, "stock_daily_bar", start_date=start_date, end_date=as_of_date)
    if raw.is_empty() or not {"symbol", "trade_date", "amount"}.issubset(raw.columns):
        return pl.DataFrame()
    return raw.select(
        pl.col("symbol").cast(pl.String).str.slice(0, 6).alias("stock_key"),
        "trade_date",
        pl.col("amount").cast(pl.Float64, strict=False).alias("_amount"),
    ).drop_nulls(subset=["stock_key", "trade_date"])


def _sum_optional_columns(frame: pl.DataFrame, columns: tuple[str, ...]) -> pl.Expr:
    expressions = [
        pl.col(column).cast(pl.Float64, strict=False).fill_null(0.0)
        for column in columns
        if column in frame.columns
    ]
    if not expressions:
        return pl.lit(0.0)
    return sum(expressions, start=pl.lit(0.0))


def _stock_industry_map(
    cat_ts: DataCatalog,
    cat_lx: DataCatalog,
    config: IndustryStructureConfig,
    as_of_date: date,
) -> pl.DataFrame:
    index_to_l1, industry_to_l1 = _industry_l1_maps(cat_ts, config)
    frames: list[pl.DataFrame] = []
    ts_map = _stock_industry_map_from_index_member(cat_ts, as_of_date, index_to_l1)
    if not ts_map.is_empty():
        frames.append(ts_map.with_columns(pl.lit(0).alias("_source_priority")))
    lx_map = _stock_industry_map_from_lixinger_constituents(cat_lx, industry_to_l1)
    if not lx_map.is_empty():
        frames.append(lx_map.with_columns(pl.lit(1).alias("_source_priority")))
    if not frames:
        return pl.DataFrame(schema={"stock_key": pl.Utf8, "industry_code": pl.Utf8})
    return (
        pl.concat(frames, how="vertical_relaxed")
        .drop_nulls(subset=["stock_key", "industry_code"])
        .sort(["stock_key", "_source_priority", "industry_code"])
        .unique(subset=["stock_key"], keep="first", maintain_order=True)
        .select("stock_key", "industry_code")
    )


def _industry_l1_maps(
    catalog: DataCatalog,
    config: IndustryStructureConfig,
) -> tuple[dict[str, str], dict[str, str]]:
    raw = _load_dataset(catalog, "index_classify")
    if raw.is_empty() or not {"index_code", "industry_code", "level"}.issubset(raw.columns):
        return {}, {}
    frame = _classify_frame(raw, config.classification)
    if frame.is_empty():
        return {}, {}
    l1_by_industry_code = _l1_by_industry_code(frame)
    index_to_l1: dict[str, str] = {}
    industry_to_l1: dict[str, str] = {}
    for row in frame.to_dicts():
        index_code = str(row.get("index_code") or "")
        industry_code = str(row.get("industry_code") or "")
        if not industry_code:
            continue
        l1_key = f"{industry_code[:2]}0000" if len(industry_code) >= 2 else industry_code
        l1_code = l1_by_industry_code.get(industry_code) or l1_by_industry_code.get(l1_key)
        if not l1_code:
            continue
        industry_to_l1[industry_code] = l1_code
        if index_code:
            index_to_l1[index_code] = l1_code
            if "." in index_code:
                index_to_l1[index_code.split(".")[0]] = l1_code
    return index_to_l1, industry_to_l1


def _classify_frame(raw: pl.DataFrame, classification: str) -> pl.DataFrame:
    if "src" not in raw.columns:
        return raw
    return raw.filter(pl.col("src") == classification)


def _l1_by_industry_code(frame: pl.DataFrame) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in frame.filter(pl.col("level") == "L1").to_dicts():
        industry_code = str(row.get("industry_code") or "")
        index_code = str(row.get("index_code") or "")
        if industry_code and index_code:
            mapping[industry_code] = index_code
    return mapping


def _stock_industry_map_from_index_member(
    catalog: DataCatalog,
    as_of_date: date,
    index_to_l1: dict[str, str],
) -> pl.DataFrame:
    raw = _load_dataset(catalog, "index_member")
    if raw.is_empty() or not {"index_code", "con_code"}.issubset(raw.columns) or not index_to_l1:
        return pl.DataFrame()
    as_of_text = as_of_date.strftime("%Y%m%d")
    base = raw.select(
        pl.col("con_code").cast(pl.String).str.slice(0, 6).alias("stock_key"),
        pl.col("index_code").cast(pl.String).alias("index_code"),
        _optional_text_expr(raw, ("in_date",), "in_date"),
        _optional_text_expr(raw, ("out_date",), "out_date"),
    )
    base = base.filter(
        ((pl.col("in_date").is_null()) | (pl.col("in_date") <= as_of_text))
        & (
            (pl.col("out_date").is_null())
            | (pl.col("out_date") == "")
            | (pl.col("out_date") > as_of_text)
        )
    )
    return base.with_columns(
        pl.col("index_code")
        .map_elements(lambda value: _map_l1_code(value, index_to_l1), return_dtype=pl.Utf8)
        .alias("industry_code")
    ).select("stock_key", "industry_code")


def _stock_industry_map_from_lixinger_constituents(
    catalog: DataCatalog,
    industry_to_l1: dict[str, str],
) -> pl.DataFrame:
    raw = _load_dataset(catalog, "sw_2021_constituents")
    if raw.is_empty() or not {"symbol", "industryCode"}.issubset(raw.columns) or not industry_to_l1:
        return pl.DataFrame()
    return raw.select(
        pl.col("symbol").cast(pl.String).str.slice(0, 6).alias("stock_key"),
        pl.col("industryCode")
        .cast(pl.String)
        .map_elements(lambda value: _map_l1_code(value, industry_to_l1), return_dtype=pl.Utf8)
        .alias("industry_code"),
    )


def _filter_target_period_if_available(
    frame: pl.DataFrame,
    period_column: str,
    target_period: date,
) -> pl.DataFrame:
    if frame.is_empty() or period_column not in frame.columns:
        return frame
    target_rows = frame.filter(pl.col(period_column) == target_period)
    return target_rows if not target_rows.is_empty() else frame


def _latest_completed_report_period(as_of_date: date) -> date:
    year = as_of_date.year
    if as_of_date.month >= 10:
        return date(year, 9, 30)
    if as_of_date.month >= 7:
        return date(year, 6, 30)
    if as_of_date.month >= 4:
        return date(year, 3, 31)
    return date(year - 1, 12, 31)


def _midpoint_expr(left: str, right: str) -> pl.Expr:
    return (
        pl.when(pl.col(left).is_not_null() & pl.col(right).is_not_null())
        .then((pl.col(left) + pl.col(right)) / 2.0)
        .otherwise(pl.coalesce(pl.col(left), pl.col(right)))
    )


def _date_column_expr(frame: pl.DataFrame, column: str, alias: str) -> pl.Expr:
    if column not in frame.columns:
        return pl.lit(None, dtype=pl.Date).alias(alias)
    return pl.col(column).map_elements(_parse_date_value, return_dtype=pl.Date).alias(alias)


def _map_l1_code(value: object, mapping: dict[str, str]) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return mapping.get(text) or mapping.get(text.split(".")[0])


def _benchmark_return_20d(
    catalog: DataCatalog,
    benchmark: str,
    as_of_date: date,
) -> float | None:
    if not benchmark:
        return None
    frame = _load_dataset(
        catalog,
        "index_daily",
        start_date=as_of_date - timedelta(days=120),
        end_date=as_of_date,
        symbols=[benchmark],
    )
    if frame.is_empty() or not {"trade_date", "close"}.issubset(frame.columns):
        return None
    frame = frame.sort("trade_date").drop_nulls(subset=["close"])
    if frame.height <= 20:
        return None
    latest = _as_float(frame["close"][-1])
    previous = _as_float(frame["close"][-21])
    if latest is None or previous is None or previous <= 0:
        return None
    return (latest / previous - 1.0) * 100.0


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


def _collapse_industry_daily_values(
    frame: pl.DataFrame,
    numeric_columns: tuple[str, ...],
) -> pl.DataFrame:
    if frame.is_empty():
        return frame
    group_columns = {"industry_code", "trade_date"}
    expressions = [
        pl.col(column).median().alias(column)
        for column in numeric_columns
        if column in frame.columns
    ]
    expressions.extend(
        pl.col(column).drop_nulls().first().alias(column)
        for column in frame.columns
        if column not in group_columns and column not in numeric_columns
    )
    return frame.group_by(["industry_code", "trade_date"]).agg(expressions)


def _optional_numeric_expr(
    frame: pl.DataFrame,
    candidates: tuple[str, ...],
    alias: str,
) -> pl.Expr:
    column = _first_existing_column(frame, candidates)
    if column is None:
        return pl.lit(None, dtype=pl.Float64).alias(alias)
    return pl.col(column).cast(pl.Float64, strict=False).alias(alias)


def _optional_text_expr(
    frame: pl.DataFrame,
    candidates: tuple[str, ...],
    alias: str,
) -> pl.Expr:
    column = _first_existing_column(frame, candidates)
    if column is None:
        return pl.lit(None, dtype=pl.Utf8).alias(alias)
    return pl.col(column).cast(pl.String).alias(alias)


def _first_existing_column(frame: pl.DataFrame, candidates: tuple[str, ...]) -> str | None:
    return next((column for column in candidates if column in frame.columns), None)


def _load_dataset(
    catalog: DataCatalog,
    dataset: str,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    symbols: list[str] | None = None,
) -> pl.DataFrame:
    try:
        return catalog.load_dataset(
            dataset,
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
        )
    except Exception:
        return pl.DataFrame()


def _resolve_industry_name(code: str, name_map: dict[str, str], *, fallback: object = None) -> str:
    if code in name_map:
        return name_map[code]
    prefix = code.split(".")[0]
    name = name_map.get(prefix)
    if name:
        return name
    fallback_text = str(fallback).strip() if fallback is not None else ""
    return fallback_text if fallback_text and fallback_text != "None" else code


def _historical_percentile(values: list[object], current: float | None) -> float | None:
    if current is None:
        return None
    clean: list[float] = []
    for value in values:
        numeric = _as_float(value)
        if numeric is not None and isfinite(numeric):
            clean.append(numeric)
    if len(clean) < 3:
        return None
    return round(sum(value <= current for value in clean) / len(clean) * 100.0, 2)


def _median_value(frame: pl.DataFrame, column: str) -> float | None:
    if frame.is_empty() or column not in frame.columns:
        return None
    value = frame.select(pl.col(column).median()).item()
    return _as_float(value)


def _divide(value: object, denominator: float) -> float | None:
    numeric = _as_float(value)
    if numeric is None:
        return None
    return numeric / denominator


def _parse_date_value(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    compact = text.replace("-", "")[:8]
    if len(compact) == 8 and compact.isdigit():
        return date(int(compact[:4]), int(compact[4:6]), int(compact[6:8]))
    return None


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, int | float | str):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) else None
