"""行业结构评分。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import polars as pl

from stock_analytics.pipelines.industry_structure.panel import BASE_PANEL_SCHEMA
from stock_analytics.pipelines.industry_structure.scoring_diagnostics import (
    _bottom_rows,
    _count_by_text,
    _structure_health,
    _tagged_rows,
    _top_rows,
    _trend_diagnostics,
)
from stock_analytics.pipelines.industry_structure.scoring_utils import (
    _apply_cross_percentile,
    _apply_fund_flow_percentiles,
    _as_float,
    _clip,
    _inverse,
    _mean_available,
    _parse_date_value,
)

if TYPE_CHECKING:
    from stock_reporting.interpretation.industry_structure.config import IndustryStructureConfig

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
        empty = pl.DataFrame(schema=SCORED_PANEL_SCHEMA)
        return empty, _empty_scores(config)

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
        official_score = _mean_available(
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
        fundamental = _blend_fundamental_score(config, row, official_score, fast_score)
        row["official_fundamental_score"] = official_score
        row["fast_fundamental_score"] = fast_score
        row["fundamental_score"] = fundamental["score"]
        row["fundamental_official_weight"] = fundamental["official_weight"]
        row["fundamental_fast_weight"] = fundamental["fast_weight"]
        row["fundamental_status"] = fundamental["status"]
        crowding_temperature = _as_float(row.get("tcr_percentile"))
        if crowding_temperature is None:
            crowding_temperature = _as_float(row.get("tcr"))
        row["crowding_temperature"] = _clip(crowding_temperature)
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


def _methodology(config: IndustryStructureConfig) -> dict[str, Any]:
    return {
        "score_type": "行业结构分是申万一级行业横截面排序分，不并入六维市场温度。",
        "missing_policy": "缺失子项不填补，对可用子项按有效权重重归一。",
        "field_definitions": {
            "tcr": (
                f"TCR=最近{config.main_window}个行业交易日的行业成交额占全部申万一级行业成交额比例均值，"
                "单位为百分点。"
            ),
            "tcr_percentile": "该行业自身历史 TCR 分位，越高代表成交越集中。",
            "crowding_temperature": "等于 TCR 历史分位，越高越拥挤。",
            "crowding_score": "100-crowding_temperature，越高代表越不拥挤。",
            "fund_flow_score": (
                "由行业20日主力净流入成交占比、大单/超大单净流入成交占比、"
                "5日主力净流入成交占比的横截面分位等权合成；仅作资金确认观察，"
                "不并入结构总分。"
            ),
        },
        "subscores": {
            "momentum_score": {
                "components": [
                    "return_20d 横截面分位",
                    "relative_return_20d 横截面分位",
                    "return_60d 横截面分位",
                    "ma_bias_20d 横截面分位",
                ],
                "direction": "越强越高",
                "normalization": "基准日申万一级行业横截面分位，0-100。",
            },
            "valuation_score": {
                "components": [
                    "100-PE五年历史分位",
                    "100-PB五年历史分位",
                    "PB-ROE残差横截面反向分位",
                ],
                "direction": "越便宜、PB-ROE越低估越高",
                "normalization": "历史分位和横截面反向分位混合，0-100。",
            },
            "fundamental_score": {
                "components": [
                    "official_fundamental_score",
                    "fast_fundamental_score",
                ],
                "direction": "越强越高",
                "normalization": (
                    "正式财报使用行业自身历史分位；快速项使用当前窗口行业横截面分位。"
                ),
                "cadence": ("正式财报是季频底座；预告、快报和研报用于中报窗口过渡确认。"),
                "blend": (
                    f"财报距基准日超过 {config.fundamental_blend.stale_after_days} 天视为 stale；"
                    f"fresh 使用正式/快速 {config.fundamental_blend.official_weight:.0%}/"
                    f"{config.fundamental_blend.fast_weight:.0%}，stale 使用 "
                    f"{config.fundamental_blend.stale_official_weight:.0%}/"
                    f"{config.fundamental_blend.stale_fast_weight:.0%}。"
                ),
            },
            "crowding_score": {
                "components": ["100-TCR历史分位"],
                "direction": "越不拥挤越高",
                "normalization": "行业自身历史反向分位，0-100。",
            },
            "fund_flow_score": {
                "components": [
                    "money_net_inflow_share_20d 横截面分位",
                    "large_money_net_inflow_share_20d 横截面分位",
                    "money_net_inflow_share_5d 横截面分位",
                ],
                "direction": "越流入越高",
                "normalization": "基准日申万一级行业横截面分位，0-100；观察项不入结构总分。",
            },
        },
        "tag_rules": {
            "强势主线": "momentum_score>=75 且 return_20d>0。",
            "低估改善": "valuation_score>=70 且 fundamental_score>=55。",
            "拥挤风险": "crowding_temperature>=80。",
            "超跌修复": "return_20d<0 且 return_5d>0。",
            "景气承压": "fundamental_score<40。",
            "相对占优": "relative_return_20d>0。",
            "资金确认": "fund_flow_score>=70 且 money_net_inflow_share_20d>0。",
            "资金流出压力": "fund_flow_score<=30 且 money_net_inflow_share_20d<0。",
            "中性观察": "不满足以上标签时使用。",
        },
        "group_rules": {
            "结构分Top": "structure_score 降序前10。",
            "动量主线": "momentum_score 降序前5。",
            "低估线索": "valuation_score 降序前5。",
            "强势主线": "带有强势主线标签，按 structure_score 降序。",
            "低估改善": "带有低估改善标签，按 structure_score 降序。",
            "拥挤风险": "带有拥挤风险标签，按 structure_score 降序；标签可与其他标签重叠。",
            "资金确认": "带有资金确认标签，按 structure_score 降序；只作验证方向。",
            "资金流出压力": "带有资金流出压力标签，按 structure_score 降序；用于风险排查。",
            "落后方向": "structure_score 升序后5；不是互斥标签。",
        },
        "data_mapping": (
            "行业代码优先由 tushare.index_classify 识别申万2021一级行业；"
            "分类字典不可用时回退为 sw_daily 可用行业代码，名称优先用分类字典，"
            "再用 sw_daily 名称或理杏仁估值表名称回填。"
        ),
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
        official_weight = config.fundamental_blend.stale_official_weight
        fast_weight = config.fundamental_blend.stale_fast_weight
    else:
        official_weight = config.fundamental_blend.official_weight
        fast_weight = config.fundamental_blend.fast_weight
    if official_score is None:
        official_weight = 0.0
    if fast_score is None:
        fast_weight = 0.0
    weight_sum = official_weight + fast_weight
    if weight_sum <= 0:
        return {
            "score": None,
            "official_weight": None,
            "fast_weight": None,
            "status": "insufficient",
        }
    score = 0.0
    if official_score is not None:
        score += official_score * official_weight
    if fast_score is not None:
        score += fast_score * fast_weight
    return {
        "score": round(score / weight_sum, 2),
        "official_weight": round(official_weight / weight_sum, 4),
        "fast_weight": round(fast_weight / weight_sum, 4),
        "status": _fundamental_status(official_score, fast_score, stale=stale),
    }


def _is_official_fundamental_stale(
    config: IndustryStructureConfig,
    row: dict[str, Any],
) -> bool:
    as_of_date = _parse_date_value(row.get("as_of_date"))
    fundamental_date = _parse_date_value(row.get("fundamental_date"))
    if as_of_date is None or fundamental_date is None:
        return True
    return (as_of_date - fundamental_date).days > config.fundamental_blend.stale_after_days


def _fundamental_status(
    official_score: float | None,
    fast_score: float | None,
    *,
    stale: bool,
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
    weighted_sum = 0.0
    weight_sum = 0.0
    for value, weight in items:
        numeric = _as_float(value)
        if numeric is None or weight <= 0:
            continue
        weighted_sum += numeric * weight
        weight_sum += weight
    if weight_sum == 0:
        return None
    return round(weighted_sum / weight_sum, 2)


def _tags(row: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    momentum = _as_float(row.get("momentum_score"))
    valuation = _as_float(row.get("valuation_score"))
    fundamental = _as_float(row.get("fundamental_score"))
    crowding = _as_float(row.get("crowding_temperature"))
    fund_flow = _as_float(row.get("fund_flow_score"))
    money_inflow = _as_float(row.get("money_net_inflow_share_20d"))
    return_20d = _as_float(row.get("return_20d"))
    return_5d = _as_float(row.get("return_5d"))
    relative_return = _as_float(row.get("relative_return_20d"))
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
    if relative_return is not None and relative_return > 0:
        tags.append("相对占优")
    if fund_flow is not None and money_inflow is not None and fund_flow >= 70 and money_inflow > 0:
        tags.append("资金确认")
    if fund_flow is not None and money_inflow is not None and fund_flow <= 30 and money_inflow < 0:
        tags.append("资金流出压力")
    return tags or ["中性观察"]


def _score_note(row: dict[str, Any]) -> str:
    available = [
        key
        for key in (
            "momentum_score",
            "valuation_score",
            "fundamental_score",
            "crowding_score",
        )
        if _as_float(row.get(key)) is not None
    ]
    observations = []
    if _as_float(row.get("fund_flow_score")) is not None:
        observations.append("fund_flow_score")
    note = f"available_subscores={','.join(available)}"
    if observations:
        note = f"{note}; available_observations={','.join(observations)}"
    return note


def _select_scored_columns(panel: pl.DataFrame) -> pl.DataFrame:
    columns = []
    for column, dtype in SCORED_PANEL_SCHEMA.items():
        if column in panel.columns:
            columns.append(pl.col(column).cast(dtype, strict=False).alias(column))
        else:
            columns.append(pl.lit(None, dtype=dtype).alias(column))
    return panel.select(columns)
