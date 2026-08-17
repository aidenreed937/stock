"""流动性与成交额过滤规则。"""

from typing import Any

import pandas as pd


class LiquidityRule:
    """流动性与成交额过滤规则 (单日成交额与 20 日均成交额)。"""

    rule_name: str = "4. 流动性与均成交额校验"

    def __init__(
        self,
        min_daily_amount_thousand: float = 30000.0,
        min_amount_20d_thousand: float = 30000.0,
    ) -> None:
        self.min_daily_amount_thousand = min_daily_amount_thousand
        self.min_amount_20d_thousand = min_amount_20d_thousand

    def apply(self, df: pd.DataFrame, context: dict[str, Any] | None = None) -> pd.DataFrame:
        filtered = df
        if "amount" in filtered.columns and self.min_daily_amount_thousand:
            filtered = filtered[filtered["amount"] >= self.min_daily_amount_thousand]
        if "amount_20d" in filtered.columns and self.min_amount_20d_thousand:
            filtered = filtered[filtered["amount_20d"] >= self.min_amount_20d_thousand]
        return filtered
