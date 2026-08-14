"""基础排除规则 (ST、北交所与上市年限过滤)。"""

from datetime import datetime, timedelta
from typing import Any
import pandas as pd


class BasicExclusionRule:
    """基础股票池排除规则。"""

    rule_name: str = "1-3. 基础排除规则"

    def __init__(
        self,
        exclude_st: bool = True,
        exclude_bj: bool = True,
        min_age_days: int = 730,
    ) -> None:
        self.exclude_st = exclude_st
        self.exclude_bj = exclude_bj
        self.min_age_days = min_age_days

    def apply(self, df: pd.DataFrame, context: dict[str, Any] | None = None) -> pd.DataFrame:
        filtered = df
        if self.exclude_st and "name" in filtered.columns:
            filtered = filtered[~filtered["name"].str.contains("ST|退", case=False, na=False)]
        if self.exclude_bj and "ts_code" in filtered.columns:
            filtered = filtered[~filtered["ts_code"].str.endswith(".BJ", na=False)]
        if "list_date" in filtered.columns:
            cutoff_date = (datetime.now() - timedelta(days=self.min_age_days)).strftime("%Y%m%d")
            filtered = filtered[filtered["list_date"] <= cutoff_date]
        return filtered
