"""申万一级行业成交额拥挤度 (TCR) 分析器。

计算逻辑:
    TCR_i = Amount_i / Sum(Amount_31_Industries) * 100%
    当单一行业成交额占比突破 20% 警戒线时，触发结构性极端过热与流动性虹吸风控警报。
"""

from datetime import date

import polars as pl
from pydantic import BaseModel, Field

from stock.analytics.industry.classifier import IndustryClassifier
from stock.data.catalog import DataCatalog


class SingleIndustryTCR(BaseModel):
    """单个行业的成交额与拥挤度数据。"""

    industry_code: str = Field(..., description="申万一级行业代码 (如 801080.SI)")
    industry_name: str = Field(..., description="申万一级行业中文名称 (如 电子)")
    amount_yi: float = Field(..., description="单日成交额 (亿元)")
    tcr: float = Field(..., description="行业成交额占 31 一级行业总成交额的比例 (%)")
    is_crowded: bool = Field(default=False, description="是否突破拥挤度警戒线 (>20%)")
    crowding_penalty: float = Field(default=0.0, description="拥挤度风控惩罚系数 [0.0, 1.0]")


class TCRAnalysisResult(BaseModel):
    """行业成交额拥挤度全景分析结果。"""

    trade_date: date = Field(..., description="计算日期")
    total_amount_yi: float = Field(..., description="31 申万一级行业合计成交额 (亿元)")
    industries: list[SingleIndustryTCR] = Field(
        default_factory=list, description="31 行业拥挤度明细 (按 TCR 降序排列)"
    )
    crowded_industries: list[str] = Field(default_factory=list, description="极端拥挤行业名称列表")
    top1_industry: str = Field(default="", description="当日成交占比最高的一级行业")
    top1_tcr: float = Field(default=0.0, description="Top1 行业的成交额占比 (%)")


class TCRCalculator:
    """行业成交额拥挤度 (TCR) 分析器。"""

    def __init__(self, catalog: DataCatalog | None = None) -> None:
        """初始化分析器。"""
        self.catalog = catalog or DataCatalog(data_source="tushare")
        self.classifier = IndustryClassifier(self.catalog)

    def calculate_daily_tcr(
        self,
        target_date: date | None = None,
        sw_daily_df: pl.DataFrame | None = None,
        crowded_threshold: float = 20.0,
    ) -> TCRAnalysisResult | None:
        """计算指定日期的申万 31 一级行业成交额拥挤度。"""
        raw_sw = self.catalog.load_dataset("sw_daily") if sw_daily_df is None else sw_daily_df
        if raw_sw.is_empty():
            return None

        if target_date is not None:
            filtered = raw_sw.filter(pl.col("trade_date") <= target_date)
        else:
            filtered = raw_sw

        if filtered.is_empty():
            return None

        max_date = filtered["trade_date"].max()
        if max_date is None:
            return None
        sub_df = filtered.filter(pl.col("trade_date") == max_date)
        eval_date = max_date if isinstance(max_date, date) else date.fromisoformat(str(max_date))

        name_map = self.classifier.get_name_map()
        l1_codes = list(self.classifier.get_l1_codes())
        filtered_l1 = (
            sub_df.select(["symbol", "amount"])
            .filter(pl.col("symbol").is_in(l1_codes))
            .drop_nulls()
        )
        df_l1 = (
            filtered_l1
            if not filtered_l1.is_empty()
            else sub_df.select(["symbol", "amount"]).drop_nulls()
        )

        total_amount = float(df_l1["amount"].sum())
        if total_amount <= 0:
            return None

        divisor = 1e8 if total_amount >= 1e10 else 10000.0
        total_amount_yi = total_amount / divisor

        industries: list[SingleIndustryTCR] = []
        crowded_names: list[str] = []

        sorted_df = df_l1.with_columns(
            ((pl.col("amount") / total_amount) * 100.0).alias("tcr")
        ).sort("tcr", descending=True)

        for row in sorted_df.iter_rows(named=True):
            code = str(row["symbol"])
            name = name_map.get(code, self.classifier.resolve_name(code))
            amt_yi = float(row["amount"]) / divisor
            tcr = float(row["tcr"])
            is_crowded = tcr >= crowded_threshold
            penalty = min(1.0, max(0.0, (tcr - 15.0) / 10.0))

            if is_crowded:
                crowded_names.append(name)

            industries.append(
                SingleIndustryTCR(
                    industry_code=code,
                    industry_name=name,
                    amount_yi=round(amt_yi, 2),
                    tcr=round(tcr, 2),
                    is_crowded=is_crowded,
                    crowding_penalty=round(penalty, 2),
                )
            )

        top1 = industries[0] if industries else None

        return TCRAnalysisResult(
            trade_date=eval_date,
            total_amount_yi=round(total_amount_yi, 2),
            industries=industries,
            crowded_industries=crowded_names,
            top1_industry=top1.industry_name if top1 else "",
            top1_tcr=top1.tcr if top1 else 0.0,
        )
