"""行业结构横截面评分计算。"""

from __future__ import annotations

from datetime import date
from math import isfinite
from typing import TYPE_CHECKING, Any

import polars as pl

from stock_analytics.marts.shared.industry_structure.panel import BASE_PANEL_SCHEMA
from stock_analytics.pipelines.industry_structure.scoring_diagnostics import (
    _bottom_rows,
    _count_by_text,
    _methodology,
    _structure_health,
    _tagged_rows,
    _top_rows,
    _trend_diagnostics,
)
from stock_analytics.primitives.rules import percentile_rank

if TYPE_CHECKING:
    from stock_core.config.analytics_industry_structure import IndustryStructureConfig

SCORED_PANEL_SCHEMA: dict[str, Any] = {
    **BASE_PANEL_SCHEMA,
    "momentum_score": pl.Float64,
    "valuation_score": pl.Float64,
    "official_fundamental_score": pl.Float64,
    "fast_fundamental_score": pl.Float64,
    "fundamental_score": pl.Float64,
    "fundamental_official_weight": pl.Float64,
    "fundamental_fast_weight": pl.Float64,
    "fundamental_status": pl.Utf8,
    "crowding_temperature": pl.Float64,
    "crowding_score": pl.Float64,
    "fund_flow_score": pl.Float64,
    "structure_score": pl.Float64,
    "structure_rank": pl.Int64,
    "tags": pl.Utf8,
    "status": pl.Utf8,
    "note": pl.Utf8,
}


def score_industry_panel(
    config: IndustryStructureConfig,
    panel: pl.DataFrame,
) -> tuple[pl.DataFrame, dict[str, Any]]:
    """给行业面板增加四类子分、总分、标签和摘要。"""
    if panel.is_empty():
        return pl.DataFrame(schema=SCORED_PANEL_SCHEMA), _empty_scores(config)

    rows = panel.to_dicts()
    _apply_cross_percentile(rows, "return_20d", "_return_20d_pct")
    _apply_cross_percentile(rows, "relative_return_20d", "_relative_return_20d_pct")
    _apply_cross_percentile(rows, "return_60d", "_return_60d_pct")
    _apply_cross_percentile(rows, "ma_bias_20d", "_ma_bias_20d_pct")
    _apply_cross_percentile(rows, "pbroe_residual", "_pbroe_score", inverse=True)
    _apply_cross_percentile(rows, "forecast_positive_share", "_forecast_positive_pct")
    _apply_cross_percentile(rows, "forecast_p_change_mid_median", "_forecast_p_change_pct")
    _apply_cross_percentile(rows, "express_profit_growth_median", "_express_profit_pct")
    _apply_cross_percentile(rows, "express_roe_median", "_express_roe_pct")
    _apply_cross_percentile(rows, "report_rc_revision_ratio", "_report_revision_pct")
    _apply_fund_flow_percentiles(rows)

    for row in rows:
        row["momentum_score"] = _mean_available(
            row.get("_return_20d_pct"),
            row.get("_relative_return_20d_pct"),
            row.get("_return_60d_pct"),
            row.get("_ma_bias_20d_pct"),
        )
        row["valuation_score"] = _mean_available(
            _inverse(row.get("pe_percentile_5y")),
            _inverse(row.get("pb_percentile_5y")),
            row.get("_pbroe_score"),
        )
        off_score = _mean_available(
            row.get("revenue_growth_percentile"),
            row.get("profit_growth_percentile"),
            row.get("roe_percentile"),
        )
        fast_score = _mean_available(
            row.get("_forecast_positive_pct"),
            row.get("_forecast_p_change_pct"),
            row.get("_express_profit_pct"),
            row.get("_express_roe_pct"),
            row.get("_report_revision_pct"),
        )
        f_blend = _blend_fundamental_score(config, row, off_score, fast_score)
        row["official_fundamental_score"] = off_score
        row["fast_fundamental_score"] = fast_score
        row["fundamental_score"] = f_blend["score"]
        row["fundamental_official_weight"] = f_blend["official_weight"]
        row["fundamental_fast_weight"] = f_blend["fast_weight"]
        row["fundamental_status"] = f_blend["status"]
        crowd_temp = _as_float(row.get("tcr_percentile"))
        if crowd_temp is None:
            crowd_temp = _as_float(row.get("tcr"))
        row["crowding_temperature"] = _clip(crowd_temp)
        row["crowding_score"] = _inverse(row.get("crowding_temperature"))
        row["fund_flow_score"] = _mean_available(
            row.get("_money_inflow_pct"),
            row.get("_large_money_inflow_pct"),
            row.get("_short_money_inflow_pct"),
        )
        row["structure_score"] = _weighted_score(config, row)
        row["tags"] = "、".join(_tags(row))
        row["status"] = "ok" if row["structure_score"] is not None else "insufficient"
        row["note"] = _score_note(row)

    ranked = sorted(
        rows,
        key=lambda item: _as_float(item.get("structure_score")) or -1.0,
        reverse=True,
    )
    for rank, row in enumerate(ranked, start=1):
        row["structure_rank"] = rank if row["structure_score"] is not None else None

    scored = _select_scored_columns(pl.DataFrame(ranked))
    return scored, _build_scores(config, scored)


def _build_scores(config: IndustryStructureConfig, panel: pl.DataFrame) -> dict[str, Any]:
    rows = panel.to_dicts()
    ok_rows = [row for row in rows if row.get("status") == "ok"]
    return {
        "schema_version": config.schema_version,
        "score_weights": config.score_weights.as_dict(),
        "fundamental_blend": config.fundamental_blend.as_dict(),
        "methodology": _methodology(config),
        "industry_count": len(rows),
        "scored_industry_count": len(ok_rows),
        "top_structure": _top_rows(rows, "structure_score"),
        "top_momentum": _top_rows(rows, "momentum_score"),
        "low_valuation": _top_rows(rows, "valuation_score"),
        "fundamental_leaders": _top_rows(rows, "fundamental_score"),
        "fast_fundamental_leaders": _top_rows(rows, "fast_fundamental_score"),
        "fundamental_status_counts": _count_by_text(rows, "fundamental_status"),
        "top_fund_flow": _top_rows(rows, "fund_flow_score"),
        "fund_flow_confirmed": _tagged_rows(rows, "资金确认"),
        "fund_flow_pressure": _tagged_rows(rows, "资金流出压力"),
        "top_crowding": _top_rows(rows, "crowding_temperature"),
        "crowded_risk": _tagged_rows(rows, "拥挤风险"),
        "undervalued_improving": _tagged_rows(rows, "低估改善"),
        "strong_trends": _tagged_rows(rows, "强势主线"),
        "lagging_or_weak": _bottom_rows(rows, "structure_score"),
        "trend_diagnostics": _trend_diagnostics(rows),
        "structure_health": _structure_health(rows),
    }


def _empty_scores(config: IndustryStructureConfig) -> dict[str, Any]:
    return {
        "schema_version": config.schema_version,
        "score_weights": config.score_weights.as_dict(),
        "fundamental_blend": config.fundamental_blend.as_dict(),
        "methodology": _methodology(config),
        "industry_count": 0,
        "scored_industry_count": 0,
        "top_structure": [],
        "top_momentum": [],
        "low_valuation": [],
        "fundamental_leaders": [],
        "fast_fundamental_leaders": [],
        "fundamental_status_counts": {},
        "top_fund_flow": [],
        "fund_flow_confirmed": [],
        "fund_flow_pressure": [],
        "top_crowding": [],
        "crowded_risk": [],
        "undervalued_improving": [],
        "strong_trends": [],
        "lagging_or_weak": [],
        "trend_diagnostics": _trend_diagnostics([]),
        "structure_health": _structure_health([]),
    }


def _blend_fundamental_score(
    config: IndustryStructureConfig,
    row: dict[str, Any],
    official_score: float | None,
    fast_score: float | None,
) -> dict[str, Any]:
    stale = _is_official_fundamental_stale(config, row)
    if official_score is None and fast_score is None:
        return {
            "score": None,
            "official_weight": None,
            "fast_weight": None,
            "status": "insufficient",
        }
    if stale:
        w_off = config.fundamental_blend.stale_official_weight
        w_fast = config.fundamental_blend.stale_fast_weight
    else:
        w_off = config.fundamental_blend.official_weight
        w_fast = config.fundamental_blend.fast_weight
    if official_score is None:
        w_off = 0.0
    if fast_score is None:
        w_fast = 0.0
    w_sum = w_off + w_fast
    if w_sum <= 0:
        return {
            "score": None,
            "official_weight": None,
            "fast_weight": None,
            "status": "insufficient",
        }
    score = (official_score or 0.0) * w_off + (fast_score or 0.0) * w_fast
    return {
        "score": round(score / w_sum, 2),
        "official_weight": round(w_off / w_sum, 4),
        "fast_weight": round(w_fast / w_sum, 4),
        "status": _fundamental_status(official_score, fast_score, stale=stale),
    }


def _is_official_fundamental_stale(config: IndustryStructureConfig, row: dict[str, Any]) -> bool:
    as_of = _parse_date(row.get("as_of_date"))
    f_date = _parse_date(row.get("fundamental_date"))
    if as_of is None or f_date is None:
        return True
    return (as_of - f_date).days > config.fundamental_blend.stale_after_days


def _fundamental_status(
    official_score: float | None, fast_score: float | None, *, stale: bool
) -> str:
    if official_score is None and fast_score is not None:
        return "provisional_fast_only"
    if official_score is not None and fast_score is None:
        return "official_stale" if stale else "official_only"
    if official_score is not None and fast_score is not None:
        return "stale_blended" if stale else "fresh_blended"
    return "insufficient"


def _weighted_score(config: IndustryStructureConfig, row: dict[str, Any]) -> float | None:
    items = (
        (row.get("momentum_score"), config.score_weights.momentum),
        (row.get("valuation_score"), config.score_weights.valuation),
        (row.get("fundamental_score"), config.score_weights.fundamental),
        (row.get("crowding_score"), config.score_weights.crowding),
    )
    weighted_sum = sum(num * w for val, w in items if (num := _as_float(val)) is not None and w > 0)
    weight_sum = sum(w for val, w in items if _as_float(val) is not None and w > 0)
    return round(weighted_sum / weight_sum, 2) if weight_sum > 0 else None


def _tags(row: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    momentum, valuation, fundamental = (
        _as_float(row.get("momentum_score")),
        _as_float(row.get("valuation_score")),
        _as_float(row.get("fundamental_score")),
    )
    crowding, fund_flow, money_inflow = (
        _as_float(row.get("crowding_temperature")),
        _as_float(row.get("fund_flow_score")),
        _as_float(row.get("money_net_inflow_share_20d")),
    )
    return_20d, return_5d, rel_return = (
        _as_float(row.get("return_20d")),
        _as_float(row.get("return_5d")),
        _as_float(row.get("relative_return_20d")),
    )

    if momentum is not None and momentum >= 75 and (return_20d or 0.0) > 0:
        tags.append("强势主线")
    if valuation is not None and valuation >= 70 and (fundamental or 0.0) >= 55:
        tags.append("低估改善")
    if crowding is not None and crowding >= 80:
        tags.append("拥挤风险")
    if return_20d is not None and return_5d is not None and return_20d < 0 < return_5d:
        tags.append("超跌修复")
    if fundamental is not None and fundamental < 40:
        tags.append("景气承压")
    if rel_return is not None and rel_return > 0:
        tags.append("相对占优")
    if fund_flow is not None and money_inflow is not None and fund_flow >= 70 and money_inflow > 0:
        tags.append("资金确认")
    if fund_flow is not None and money_inflow is not None and fund_flow <= 30 and money_inflow < 0:
        tags.append("资金流出压力")
    return tags or ["中性观察"]


def _score_note(row: dict[str, Any]) -> str:
    available = [
        k
        for k in ("momentum_score", "valuation_score", "fundamental_score", "crowding_score")
        if _as_float(row.get(k)) is not None
    ]
    obs = ["fund_flow_score"] if _as_float(row.get("fund_flow_score")) is not None else []
    note = f"available_subscores={','.join(available)}"
    return f"{note}; available_observations={','.join(obs)}" if obs else note


def _select_scored_columns(panel: pl.DataFrame) -> pl.DataFrame:
    columns = [
        pl.col(c).cast(dtype, strict=False).alias(c)
        if c in panel.columns
        else pl.lit(None, dtype=dtype).alias(c)
        for c, dtype in SCORED_PANEL_SCHEMA.items()
    ]
    return panel.select(columns)


def _apply_cross_percentile(
    rows: list[dict[str, Any]],
    source: str,
    target: str,
    *,
    inverse: bool = False,
) -> None:
    values = [
        (idx, val)
        for idx, row in enumerate(rows)
        if (val := _as_float(row.get(source))) is not None
    ]
    if len(values) < 2:
        return
    v_series = pl.Series([v for _, v in values])
    for idx, val in values:
        pct = percentile_rank(v_series, len(values), current=val)
        rows[idx][target] = round(100.0 - pct if inverse else pct, 2) if pct is not None else None


def _apply_fund_flow_percentiles(rows: list[dict[str, Any]]) -> None:
    _apply_cross_percentile(rows, "money_net_inflow_share_20d", "_money_inflow_pct")
    _apply_cross_percentile(rows, "large_money_net_inflow_share_20d", "_large_money_inflow_pct")
    _apply_cross_percentile(rows, "money_net_inflow_share_5d", "_short_money_inflow_pct")


def _mean_available(*values: object) -> float | None:
    clean = [num for v in values if (num := _as_float(v)) is not None]
    return round(sum(clean) / len(clean), 2) if clean else None


def _parse_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    compact = str(value).strip().replace("-", "")[:8]
    if len(compact) == 8 and compact.isdigit():
        return date(int(compact[:4]), int(compact[4:6]), int(compact[6:8]))
    return None


def _inverse(value: object) -> float | None:
    return _clip(100.0 - num) if (num := _as_float(value)) is not None else None


def _clip(value: object) -> float | None:
    return round(min(100.0, max(0.0, num)), 2) if (num := _as_float(value)) is not None else None


def _as_float(value: object) -> float | None:
    if value is None or not isinstance(value, int | float | str):
        return None
    try:
        num = float(value)
        return num if isfinite(num) else None
    except (TypeError, ValueError):
        return None
