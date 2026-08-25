"""个股排雷规则纯函数门面。"""

from __future__ import annotations

from typing import Any

import polars as pl

from stock_analytics.pipelines.stock_screen.fundamental_rules import (
    evaluate_consecutive_losses,
    evaluate_consecutive_ocf_deficit,
    evaluate_dedt_profit_loss,
    evaluate_goodwill_observe,
    evaluate_goodwill_overhang,
    evaluate_high_leverage_insolvency,
    evaluate_negative_equity,
    evaluate_pledge_overhang,
    evaluate_receivables_revenue_distortion,
    evaluate_st_marked,
    evaluate_too_new_listing,
)
from stock_analytics.pipelines.stock_screen.margin_rules import evaluate_margin_stress
from stock_analytics.pipelines.stock_screen.rule_helpers import (
    RuleEvaluator,
)
from stock_analytics.pipelines.stock_screen.rule_helpers import (
    not_evaluated as _not_evaluated,
)
from stock_analytics.pipelines.stock_screen.trading_rules import (
    evaluate_block_trade_discount,
    evaluate_consecutive_limit_down,
    evaluate_forecast_plunge,
    evaluate_holder_selloff,
    evaluate_illiquid_float,
    evaluate_lockup_release,
    evaluate_northbound_drawdown,
    evaluate_penny_stock_face_value,
    evaluate_suspended,
)


def evaluate_rule(rule_id: str, rows: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    """按规则 ID 调用对应的纯函数。"""
    evaluator = RULE_EVALUATORS.get(rule_id)
    if evaluator is None:
        return _not_evaluated(rows, rule_id, f"未注册规则 {rule_id}")
    return evaluator(rows, params)


RULE_EVALUATORS: dict[str, RuleEvaluator] = {
    "st_marked": evaluate_st_marked,
    "too_new_listing": evaluate_too_new_listing,
    "penny_stock_face_value": evaluate_penny_stock_face_value,
    "illiquid_float": evaluate_illiquid_float,
    "consecutive_losses": evaluate_consecutive_losses,
    "negative_equity": evaluate_negative_equity,
    "goodwill_overhang": evaluate_goodwill_overhang,
    "suspended": evaluate_suspended,
    "forecast_plunge": evaluate_forecast_plunge,
    "holder_selloff": evaluate_holder_selloff,
    "goodwill_observe": evaluate_goodwill_observe,
    "northbound_drawdown": evaluate_northbound_drawdown,
    "consecutive_limit_down": evaluate_consecutive_limit_down,
    "margin_stress": evaluate_margin_stress,
    "dedt_profit_loss": evaluate_dedt_profit_loss,
    "lockup_release": evaluate_lockup_release,
    "pledge_overhang": evaluate_pledge_overhang,
    "high_leverage_insolvency": evaluate_high_leverage_insolvency,
    "receivables_revenue_distortion": evaluate_receivables_revenue_distortion,
    "block_trade_discount": evaluate_block_trade_discount,
    "consecutive_ocf_deficit": evaluate_consecutive_ocf_deficit,
}


__all__ = [
    "RULE_EVALUATORS",
    "evaluate_block_trade_discount",
    "evaluate_consecutive_limit_down",
    "evaluate_consecutive_losses",
    "evaluate_consecutive_ocf_deficit",
    "evaluate_dedt_profit_loss",
    "evaluate_forecast_plunge",
    "evaluate_goodwill_observe",
    "evaluate_goodwill_overhang",
    "evaluate_high_leverage_insolvency",
    "evaluate_holder_selloff",
    "evaluate_illiquid_float",
    "evaluate_lockup_release",
    "evaluate_margin_stress",
    "evaluate_negative_equity",
    "evaluate_northbound_drawdown",
    "evaluate_penny_stock_face_value",
    "evaluate_pledge_overhang",
    "evaluate_receivables_revenue_distortion",
    "evaluate_rule",
    "evaluate_st_marked",
    "evaluate_suspended",
    "evaluate_too_new_listing",
]
