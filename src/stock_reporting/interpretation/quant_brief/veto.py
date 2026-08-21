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

MARGIN_GROWTH_WINDOW = 20
MARGIN_GROWTH_LONG_WINDOW = 60
_MARGIN_BALANCE_CANDIDATES = ("margin_balance", "rzrqye", "total_balance", "balance")


def evaluate_veto(
    config: QuantBriefConfig,
    market_scores: dict[str, Any],
    industry_scores: dict[str, Any],
    industry_panel: pl.DataFrame,
    market_facts: pl.DataFrame | None,
    margin_series: pl.DataFrame | None = None,
) -> dict[str, Any]:
    """执行拥挤度、两融和 Top5% 成交集中度排雷。

    ``margin_series`` 为可选的本地两融日频序列（``trade_date`` + 余额列），
    用于把两融拐点判定从硬编码 ``insufficient_history`` 升级为基于连续状态的判断。
    """
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
                "两融20日余额增速当前为负，且连续状态未确认回升，不据此宣称去杠杆拐点已出现。",
            )
        )
        margin_note = "两融20日余额增速当前为负；连续状态判定详见 turning_point。"
    else:
        margin_note = "两融20日余额增速当前未转负；连续状态判定详见 turning_point。"

    margin_state = _margin_state(config, margin_series, growth_20d)
    margin["note"] = margin_note
    margin["turning_point"] = margin_state
    margin["turning_point_status"] = margin_state["status"]

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
        "margin": margin,
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


def _margin_state(
    config: QuantBriefConfig,
    margin_series: pl.DataFrame | None,
    growth_20d: float | None,
) -> dict[str, Any]:
    """基于两融日频序列计算拐点连续状态。

    输出 ``status`` 取值：
    - ``confirmed_turning``：20 日增速由负转正（或由正转负）且近期方向连续；
    - ``persistent_negative``：20 日增速为负且日频方向连续向下；
    - ``persistent_positive``：20 日增速为正且日频方向连续向上；
    - ``mixed``：序列可用但方向不连续；
    - ``insufficient_history``：无序列或样本不足。
    """
    if margin_series is None or margin_series.is_empty():
        return {"status": "insufficient_history", "reason": "未提供两融日频序列"}
    frame = _margin_series_frame(margin_series)
    if frame.is_empty():
        return {"status": "insufficient_history", "reason": "两融日频序列无有效余额列"}
    balance_col = frame.columns[1]
    if frame.height < MARGIN_GROWTH_WINDOW + 2:
        return {"status": "insufficient_history", "reason": "两融日频序列样本不足"}
    daily_delta = frame.select(
        (pl.col(balance_col) / pl.col(balance_col).shift(1) - 1.0).alias("_delta")
    )["_delta"]
    signs = daily_delta.drop_nulls()
    recent_signs = signs.tail(5)
    if recent_signs.is_empty():
        return {"status": "insufficient_history", "reason": "两融日频序列无有效日变化"}
    negative_days = int((recent_signs < 0).sum())
    positive_days = int((recent_signs > 0).sum())
    consecutive_negative = _consecutive_run(recent_signs, negative=True)
    consecutive_positive = _consecutive_run(recent_signs, negative=False)
    below_threshold = growth_20d is not None and growth_20d < config.margin_negative_threshold
    if below_threshold and negative_days >= 4:
        status = "persistent_negative"
        reason = f"两融20日增速为负，且最近5个交易日 {negative_days} 日为负，杠杆去化仍在延续。"
    elif below_threshold and consecutive_positive >= 3:
        status = "confirmed_turning"
        reason = f"两融20日增速仍为负，但最近 {consecutive_positive} 个交易日连续回升，去杠杆拐点正在确认。"
    elif not below_threshold and positive_days >= 4:
        status = "persistent_positive"
        reason = f"两融20日增速未转负，最近5个交易日 {positive_days} 日为正，杠杆仍在累积。"
    elif not below_threshold and consecutive_negative >= 3:
        status = "confirmed_turning"
        reason = f"两融20日增速仍为正，但最近 {consecutive_negative} 个交易日连续回落，杠杆累积拐点正在确认。"
    else:
        status = "mixed"
        reason = "两融日频方向不连续，杠杆资金方向尚不清晰。"
    return {
        "status": status,
        "reason": reason,
        "sample_size": frame.height,
        "negative_days_5d": negative_days,
        "positive_days_5d": positive_days,
        "consecutive_negative_days": consecutive_negative,
        "consecutive_positive_days": consecutive_positive,
    }


def _margin_series_frame(margin_series: pl.DataFrame) -> pl.DataFrame:
    """从通用两融序列中挑选余额列并重命名。"""
    if "trade_date" not in margin_series.columns:
        return pl.DataFrame()
    balance_col = next(
        (column for column in _MARGIN_BALANCE_CANDIDATES if column in margin_series.columns),
        None,
    )
    if balance_col is None:
        return pl.DataFrame()
    return (
        margin_series.select("trade_date", balance_col)
        .rename({balance_col: "margin_balance"})
        .drop_nulls()
        .sort("trade_date")
    )


def _consecutive_run(signs: pl.Series, *, negative: bool) -> int:
    """返回最近连续为负（或为正）的天数。"""
    count = 0
    for value in reversed(signs.to_list()):
        matches = (value < 0) if negative else (value > 0)
        if not matches:
            break
        count += 1
    return count


__all__ = ["evaluate_veto"]
