"""行业估值与财报面板的批次计算。"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import polars as pl

from stock_analytics.marts.shared.industry_structure.panel_metrics import (
    _clean_valuation_metrics,
    as_float,
    collapse_industry_daily_values,
    historical_percentile,
)
from stock_analytics.marts.shared.industry_structure.panel_sources import (
    load_dataset,
    load_financial_statement_history,
    map_l1_code,
    optional_numeric_expr,
    optional_text_expr,
)
from stock_analytics.marts.shared.industry_structure.pb_roe import IndustryPBROEAnalyzer

if TYPE_CHECKING:
    from stock_core.contracts import MarketDataCatalog


def valuation_panel_batch(
    cat: MarketDataCatalog,
    as_of_dates: tuple[date, ...],
    industry_to_l1: dict[str, str],
    *,
    classification_catalog: MarketDataCatalog | None = None,
) -> dict[date, pl.DataFrame]:
    """批量构建估值面板，避免每个基准日重复读取和归一整张估值表。"""
    if not as_of_dates:
        return {}
    raw = load_dataset(
        cat,
        "sw_2021_fundamental",
        start_date=min(as_of_dates) - timedelta(days=365 * 5),
        end_date=max(as_of_dates),
        columns=[
            "symbol",
            "trade_date",
            "name",
            "industry_name",
            "pe_ttm.ew",
            "pe_ttm.mcw",
            "pe_ttm",
            "pe",
            "pe_ew",
            "pb.ew",
            "pb.mcw",
            "pb",
            "pb_ew",
            "dyr.ew",
            "dyr.mcw",
            "dividend_yield",
            "dv_ttm",
        ],
    )
    if raw.is_empty() or not {"symbol", "trade_date"}.issubset(raw.columns):
        return {}
    base = _valuation_base_frame(raw, industry_to_l1)
    if base.is_empty():
        return {}
    raw_by_date = _partition_by_date(raw, "trade_date")
    analyzer = IndustryPBROEAnalyzer(
        catalog=cat,
        classifier_catalog=classification_catalog,
    )

    # 预先按行业分组并按日期升序提取各列时序，避免在 3000 个基准日中做 9 万次 DataFrame filter
    industry_records: dict[str, list[dict[str, Any]]] = {}
    industry_dates: dict[str, list[date]] = {}
    for raw_code, part in (
        base.sort("trade_date").partition_by("industry_code", as_dict=True).items()
    ):
        code = raw_code[0] if isinstance(raw_code, tuple) else str(raw_code)
        dicts = part.to_dicts()
        industry_records[code] = dicts
        industry_dates[code] = [r["trade_date"] for r in dicts if isinstance(r["trade_date"], date)]

    results: dict[date, pl.DataFrame] = {}
    for as_of_date in as_of_dates:
        rows: list[dict[str, Any]] = []
        eval_dates: list[date] = []
        start_cutoff = as_of_date - timedelta(days=365 * 5)

        for code, d_list in industry_dates.items():
            idx = bisect_right(d_list, as_of_date)
            if idx == 0:
                continue
            latest_row = industry_records[code][idx - 1]
            t_date = latest_row["trade_date"]
            if not isinstance(t_date, date) or t_date < start_cutoff:
                continue
            eval_dates.append(t_date)

            start_idx = bisect_left(d_list, start_cutoff)
            sub_records = industry_records[code][start_idx:idx]

            pe_hist = [r.get("pe_ttm") for r in sub_records]
            pb_hist = [r.get("pb") for r in sub_records]

            rows.append(
                {
                    "industry_code": code,
                    "industry_name_from_valuation": latest_row.get("industry_name_from_valuation"),
                    "valuation_date": t_date,
                    "pe_ttm": latest_row.get("pe_ttm"),
                    "pb": latest_row.get("pb"),
                    "dividend_yield": latest_row.get("dividend_yield"),
                    "pe_percentile_5y": historical_percentile(
                        pe_hist, as_float(latest_row.get("pe_ttm"))
                    ),
                    "pb_percentile_5y": historical_percentile(
                        pb_hist, as_float(latest_row.get("pb"))
                    ),
                }
            )

        if not rows:
            continue

        eval_date = max(eval_dates) if eval_dates else None
        pbroe_by_l1 = (
            _pb_roe_by_l1_frame(
                raw_by_date.get(eval_date, pl.DataFrame()),
                analyzer,
                industry_to_l1,
            )
            if eval_date
            else {}
        )
        for r in rows:
            pbroe = pbroe_by_l1.get(r["industry_code"], {})
            r["pbroe_residual"] = as_float(pbroe.get("residual"))
            r["pbroe_undervalued"] = bool(pbroe.get("is_undervalued", False))

        results[as_of_date] = pl.DataFrame(rows).select(
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
    return results


def fundamental_panel_batch(
    cat: MarketDataCatalog,
    as_of_dates: tuple[date, ...],
    industry_to_l1: dict[str, str],
) -> dict[date, pl.DataFrame]:
    """批量构建财报面板，按基准日切片已归一的历史序列。"""
    if not as_of_dates:
        return {}
    frame = load_financial_statement_history(
        cat,
        max(as_of_dates),
        start_date=min(as_of_dates) - timedelta(days=365 * 6),
    )
    if frame.is_empty():
        return {}
    frame = frame.with_columns(
        pl.col("industry_code")
        .map_elements(lambda value: map_l1_code(value, industry_to_l1), return_dtype=pl.Utf8)
        .alias("industry_code")
    ).drop_nulls(subset=["industry_code"])
    frame = collapse_industry_daily_values(
        frame,
        ("revenue_growth_ttm", "profit_growth_ttm", "roe_ttm"),
    )

    # 预先按行业分组并按日期升序提取各列时序
    industry_records: dict[str, list[dict[str, Any]]] = {}
    industry_dates: dict[str, list[date]] = {}
    for raw_code, part in (
        frame.sort("trade_date").partition_by("industry_code", as_dict=True).items()
    ):
        code = raw_code[0] if isinstance(raw_code, tuple) else str(raw_code)
        dicts = part.to_dicts()
        industry_records[code] = dicts
        industry_dates[code] = [r["trade_date"] for r in dicts if isinstance(r["trade_date"], date)]

    results: dict[date, pl.DataFrame] = {}
    for as_of_date in as_of_dates:
        rows: list[dict[str, Any]] = []
        start_cutoff = as_of_date - timedelta(days=365 * 6)

        for code, d_list in industry_dates.items():
            idx = bisect_right(d_list, as_of_date)
            if idx == 0:
                continue
            latest_row = industry_records[code][idx - 1]
            t_date = latest_row["trade_date"]
            if not isinstance(t_date, date) or t_date < start_cutoff:
                continue

            start_idx = bisect_left(d_list, start_cutoff)
            sub_records = industry_records[code][start_idx:idx]

            rev_hist = [r.get("revenue_growth_ttm") for r in sub_records]
            prof_hist = [r.get("profit_growth_ttm") for r in sub_records]
            roe_hist = [r.get("roe_ttm") for r in sub_records]

            rows.append(
                {
                    "industry_code": code,
                    "fundamental_date": t_date,
                    "revenue_growth_ttm": latest_row.get("revenue_growth_ttm"),
                    "profit_growth_ttm": latest_row.get("profit_growth_ttm"),
                    "roe_ttm": latest_row.get("roe_ttm"),
                    "revenue_growth_percentile": historical_percentile(
                        rev_hist, as_float(latest_row.get("revenue_growth_ttm"))
                    ),
                    "profit_growth_percentile": historical_percentile(
                        prof_hist, as_float(latest_row.get("profit_growth_ttm"))
                    ),
                    "roe_percentile": historical_percentile(
                        roe_hist, as_float(latest_row.get("roe_ttm"))
                    ),
                }
            )

        if not rows:
            continue

        results[as_of_date] = pl.DataFrame(rows).select(
            "industry_code",
            "fundamental_date",
            "revenue_growth_ttm",
            "profit_growth_ttm",
            "roe_ttm",
            "revenue_growth_percentile",
            "profit_growth_percentile",
            "roe_percentile",
        )
    return results


def _valuation_base_frame(
    raw: pl.DataFrame,
    industry_to_l1: dict[str, str],
) -> pl.DataFrame:
    base = raw.select(
        pl.col("symbol")
        .cast(pl.String)
        .map_elements(lambda value: map_l1_code(value, industry_to_l1), return_dtype=pl.Utf8)
        .alias("industry_code"),
        "trade_date",
        optional_text_expr(raw, ("name", "industry_name"), "industry_name_from_valuation"),
        optional_numeric_expr(
            raw,
            ("pe_ttm.ew", "pe_ttm.mcw", "pe_ttm", "pe", "pe_ew"),
            "pe_ttm",
        ),
        optional_numeric_expr(raw, ("pb.ew", "pb.mcw", "pb", "pb_ew"), "pb"),
        optional_numeric_expr(
            raw,
            ("dyr.ew", "dyr.mcw", "dividend_yield", "dv_ttm"),
            "dividend_yield",
        ),
    ).drop_nulls(subset=["industry_code", "trade_date"])
    base = _clean_valuation_metrics(base)
    return collapse_industry_daily_values(base, ("pe_ttm", "pb", "dividend_yield"))


def _partition_by_date(frame: pl.DataFrame, date_column: str) -> dict[date, pl.DataFrame]:
    if frame.is_empty() or date_column not in frame.columns:
        return {}
    result: dict[date, pl.DataFrame] = {}
    for raw_key, partition in frame.partition_by(date_column, as_dict=True).items():
        key = raw_key[0] if isinstance(raw_key, tuple) else raw_key
        if isinstance(key, date):
            result[key] = partition
    return result


def _pb_roe_by_l1_frame(
    frame: pl.DataFrame,
    analyzer: IndustryPBROEAnalyzer,
    industry_to_l1: dict[str, str],
) -> dict[str, dict[str, Any]]:
    if frame.is_empty():
        return {}
    try:
        result = analyzer.analyze_cross_section(val_df=frame)
    except Exception:
        return {}
    if result is None:
        return {}
    mapped: dict[str, dict[str, Any]] = {}
    for row in result.industries:
        l1_code = map_l1_code(row.get("symbol"), industry_to_l1)
        if l1_code:
            mapped[l1_code] = row
    return mapped
