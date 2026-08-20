"""量化投研简报的微观排雷与一票否决。"""

from __future__ import annotations

from typing import Any

import polars as pl

from stock_reporting.interpretation.quant_brief.config import QuantBriefConfig
from stock_reporting.interpretation.quant_brief.helpers import (
    _as_float,
    _crowded_rows,
    _date_text,
    _fact_observation,
    _flag,
    _mapping,
    _margin_observation,
    _value_text,
)
from stock_reporting.interpretation.quant_brief.risk_gates import (
    evaluate_funding_health,
    evaluate_industry_gate,
)


def evaluate_veto(
    config: QuantBriefConfig,
    market_scores: dict[str, Any],
    industry_scores: dict[str, Any],
    industry_panel: pl.DataFrame,
    market_facts: pl.DataFrame | None,
) -> dict[str, Any]:
    """执行拥挤度、两融和 Top5% 成交集中度排雷。"""
    health = _mapping(industry_scores.get("structure_health"))
    crowded_share = _as_float(health.get("crowded_industry_share"))
    crowded_rows = _crowded_rows(industry_panel, config)
    top5 = _fact_observation(market_facts, "amount_top_5pct_share")
    top5_value = _as_float(top5.get("value_float")) if top5 else None
    margin = _margin_observation(market_facts)
    funding_health = evaluate_funding_health(config, market_facts)
    industry_gate = evaluate_industry_gate(config, industry_panel)
    flags: list[dict[str, str]] = []
    missing: list[str] = []

    if top5_value is None:
        missing.append("amount_top_5pct_share")
    elif top5_value > config.top5pct_share:
        flags.append(
            _flag(
                "market_top5_concentration",
                "hard",
                f"大盘 Top5% 成交占比 {_value_text(top5_value * 100)}% 超过 {config.top5pct_share * 100:.0f}% 警戒线。",
            )
        )

    if crowded_share is None:
        missing.append("crowded_industry_share")
    elif crowded_share >= config.crowded_industry_share:
        flags.append(
            _flag(
                "industry_crowding_breadth",
                "watch",
                f"拥挤行业占比 {_value_text(crowded_share)}% 达到 {config.crowded_industry_share:.0f}% 观察线。",
            )
        )

    growth_20d = _as_float(margin.get("margin_balance_growth_20d"))
    if growth_20d is None:
        missing.append("margin_balance_growth_20d")
        margin_note = "两融20日增速缺失，无法判断杠杆资金方向。"
    elif growth_20d < config.margin_negative_threshold:
        flags.append(
            _flag(
                "margin_growth_negative",
                "watch",
                "两融20日余额增速当前为负，但上游没有连续状态序列，不能据此宣称完成高位拐点确认。",
            )
        )
        margin_note = "两融20日余额增速当前为负；缺少历史连续状态，拐点判定为资金确认不足。"
    else:
        margin_note = "两融20日余额增速当前未转负；上游没有连续状态序列，仍不能完成严格拐点判定。"
    if margin.get("margin_balance_growth_60d") is None:
        missing.append("margin_balance_growth_60d")
    if margin.get("margin_buy_share") is None:
        missing.append("margin_buy_share")

    missing.extend(funding_health["missing"])
    if industry_gate["severity"] == "local":
        flags.append(_flag("industry_crowding_hard", "watch", industry_gate["message"]))
    elif industry_gate["status"] == "watch":
        flags.append(_flag("industry_crowding_watch", "watch", industry_gate["message"]))
    if not crowded_rows and crowded_share is None:
        missing.append("industry_crowding_panel")
    status = (
        "triggered"
        if any(item["severity"] == "hard" for item in flags)
        else ("watch" if flags else ("partial" if missing else "clear"))
    )
    return {
        "status": status,
        "flags": flags,
        "crowded_industry_share": crowded_share,
        "crowded_industries": crowded_rows[: config.max_crowded_industries],
        "margin": {
            **margin,
            "note": margin_note,
            "turning_point_status": "insufficient_history",
        },
        "top5pct": {
            "value": top5_value,
            "unit": "ratio",
            "metric_date": _date_text(top5.get("metric_date")) if top5 else None,
            "sample_size": top5.get("sample_size") if top5 else None,
            "threshold": config.top5pct_share,
            "triggered": top5_value is not None and top5_value > config.top5pct_share,
            "note": "单日横截面事实，只用于当前拥挤排查，不解释为趋势。",
        },
        "tcr_note": "行业原始 TCR 是成交额占比/百分点；拥挤排查使用 crowding_temperature（TCR 历史分位），不直接判断 tcr≥80。",
        "industry_gate": industry_gate,
        "missing": sorted(set(missing)),
    }


__all__ = ["evaluate_veto"]
