"""市值与估值指标过滤规则。"""

from typing import Any

import pandas as pd


class ValuationRule:
    """市值与估值指标过滤规则 (流通市值下限、PB 市净率区间)。"""

    rule_name: str = "5. 市值与估值区间校验"

    def __init__(
        self,
        min_float_mv_yi: float = 15.0,
        min_pb: float | None = 0.4,
        max_pb: float | None = 8.0,
    ) -> None:
        self.min_float_mv_yi = min_float_mv_yi
        self.min_pb = min_pb
        self.max_pb = max_pb

    def apply(self, df: pd.DataFrame, context: dict[str, Any] | None = None) -> pd.DataFrame:
        filtered = df
        if "circ_mv" in filtered.columns and self.min_float_mv_yi:
            min_circ_mv_yuan = self.min_float_mv_yi * 1e8
            filtered = filtered[
                filtered["circ_mv"].isna() | (filtered["circ_mv"] >= min_circ_mv_yuan)
            ]
        if "pb" in filtered.columns:
            if self.min_pb is not None:
                filtered = filtered[filtered["pb"].isna() | (filtered["pb"] >= self.min_pb)]
            if self.max_pb is not None:
                filtered = filtered[filtered["pb"].isna() | (filtered["pb"] <= self.max_pb)]
        return filtered
