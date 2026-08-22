"""融资融券排雷规则。"""

from __future__ import annotations

from typing import Any

import polars as pl

from stock_analytics.pipelines.stock_screen.rule_helpers import as_float as _as_float
from stock_analytics.pipelines.stock_screen.rule_helpers import not_evaluated as _not_evaluated
from stock_analytics.pipelines.stock_screen.rule_helpers import outcome as _outcome
from stock_analytics.pipelines.stock_screen.rule_helpers import result_frame as _result


def evaluate_margin_stress(rows: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    """识别融资融券余额短期骤降（去杠杆压力）。

    计算每个标的在 window_days 交易日内 rzrqye 的变动幅度，
    若降幅超过 drop_threshold 则触发黄牌预警。
    """
    if "trade_date" not in rows.columns or "rzrqye" not in rows.columns:
        return _not_evaluated(rows, "margin_stress", "缺少 margin_detail.trade_date/rzrqye")
    window = int(params.get("window_days", 20))
    threshold = float(params.get("drop_threshold", -0.30))

    sorted_rows = rows.sort("trade_date", descending=True)
    latest = sorted_rows.group_by("symbol", maintain_order=True).agg(
        pl.col("rzrqye").first().alias("current")
    )
    prev = sorted_rows.group_by("symbol", maintain_order=True).agg(
        pl.col("rzrqye").slice(window, 1).first().alias("previous")
    )

    joined = latest.join(prev, on="symbol", how="inner")
    outcomes = []
    for row in joined.to_dicts():
        symbol = str(row.get("symbol", ""))
        current = _as_float(row.get("current"))
        previous = _as_float(row.get("previous"))
        if current is None or previous is None or previous <= 0:
            continue
        change = current / previous - 1.0
        status = "warn" if change < threshold else "pass"
        outcomes.append(
            _outcome({"symbol": symbol}, "margin_stress", status, f"融资融券余额变动 {change:.2%}")
        )
    return (
        _result(outcomes) if outcomes else _not_evaluated(rows, "margin_stress", "无足够数据评估")
    )


__all__ = ["evaluate_margin_stress"]
