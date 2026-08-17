"""申万一级行业成交额拥挤度 (TCR) 分析器。

计算逻辑:
    TCR_i = Amount_i / Sum(Amount_31_Industries) * 100%
    当单一行业成交额占比突破 20% 警戒线时，触发结构性极端过热与流动性虹吸风控警报。
"""

from datetime import date

import polars as pl

from stock.analytics.domains.industry.classifier import IndustryClassifier
from stock.analytics.models import SingleIndustryTCR, TCRAnalysisResult
from stock.data.catalog import DataCatalog


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

        total_amount_yi = total_amount / 1e8

        industries: list[SingleIndustryTCR] = []
        crowded_names: list[str] = []

        sorted_df = df_l1.with_columns(
            ((pl.col("amount") / total_amount) * 100.0).alias("tcr")
        ).sort("tcr", descending=True)

        for row in sorted_df.iter_rows(named=True):
            code = str(row["symbol"])
            name = name_map.get(code, self.classifier.resolve_name(code))
            amt_yi = float(row["amount"]) / 1e8
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
