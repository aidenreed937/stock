from abc import ABC, abstractmethod
from typing import Any
import polars as pl

class BaseValidationRule(ABC):
    """离线数据校验规则抽象基类。"""

    @abstractmethod
    def audit(self, df: pl.DataFrame) -> dict[str, Any]:
        """执行具体审计校验，并返回结果指标。
        
        返回的字典中应当包含 "passed" (bool) 指明该规则校验是否通过。
        """
        pass


class NullCheckRule(BaseValidationRule):
    """关键列空值校验规则。"""

    def __init__(self, columns: list[str] | None = None) -> None:
        self.columns = columns or ["symbol", "trade_date", "close", "open", "high", "low"]

    def audit(self, df: pl.DataFrame) -> dict[str, Any]:
        null_counts = {
            col: df[col].null_count()
            for col in self.columns
            if col in df.columns
        }
        total_nulls = sum(null_counts.values())
        return {
            "total_nulls": total_nulls,
            "null_details": null_counts,
            "passed": total_nulls == 0,
        }


class PrimaryKeyRule(BaseValidationRule):
    """主键唯一性校验规则。"""

    def __init__(self, keys: list[str] | None = None) -> None:
        self.keys = keys or ["symbol", "trade_date"]

    def audit(self, df: pl.DataFrame) -> dict[str, Any]:
        # 确保 keys 都在 df 中才进行校验
        missing_keys = [k for k in self.keys if k not in df.columns]
        if missing_keys:
            return {"duplicate_records": 0, "passed": True}

        total_records = len(df)
        dup_count = total_records - len(df.unique(subset=self.keys))
        return {
            "duplicate_records": dup_count,
            "passed": dup_count == 0,
        }


class OhlcLogicRule(BaseValidationRule):
    """OHLC 价格物理逻辑校验规则。"""

    def audit(self, df: pl.DataFrame) -> dict[str, Any]:
        # 检查是否包含必要的 OHLC 字段
        required = ["open", "high", "low", "close"]
        if not all(col in df.columns for col in required):
            return {"physical_errors": 0, "passed": True}

        physical_errors = df.filter(
            (pl.col("open") <= 0)
            | (pl.col("high") <= 0)
            | (pl.col("low") <= 0)
            | (pl.col("close") <= 0)
            | (pl.col("high") < pl.col("low"))
            | (pl.col("high") < pl.col("open"))
            | (pl.col("high") < pl.col("close"))
            | (pl.col("low") > pl.col("open"))
            | (pl.col("low") > pl.col("close"))
        )
        physical_error_count = len(physical_errors)
        return {
            "physical_errors": physical_error_count,
            "passed": physical_error_count == 0,
        }


class VolatilityRule(BaseValidationRule):
    """涨跌幅、波动率、极端值及换手率校验规则。"""

    def audit(self, df: pl.DataFrame) -> dict[str, Any]:
        calc_diff_count = 0
        if "pre_close" in df.columns and "pct_chg" in df.columns and "close" in df.columns:
            diff_df = df.filter(pl.col("pre_close") > 0).with_columns(
                (((pl.col("close") - pl.col("pre_close")) / pl.col("pre_close") * 100) - pl.col("pct_chg"))
                .abs()
                .alias("diff")
            )
            # 允许 0.1% 内的尾数舍入浮点误差
            calc_diff_count = len(diff_df.filter(pl.col("diff") > 0.1))

        spike_fault_count = 0
        if "pct_chg" in df.columns:
            # 标记单日涨幅绝对值超出 1000% 的飞线故障
            spike_fault_count = len(df.filter(pl.col("pct_chg").abs() > 1000.0))

        turnover_fault_count = 0
        if "turnover_rate" in df.columns:
            turnover_fault_count = len(df.filter(pl.col("turnover_rate") > 300.0))

        # 注意：依据原逻辑，calc_diff_errors 并不影响最终 passed 的布尔值，但 spike 和 turnover 会影响
        return {
            "calc_diff_errors": calc_diff_count,
            "spike_faults": spike_fault_count,
            "turnover_faults": turnover_fault_count,
            "passed": spike_fault_count == 0 and turnover_fault_count == 0,
        }


class CompletenessRule(BaseValidationRule):
    """时间轴完整性及数据截断/异常天数校验规则。"""

    def __init__(self, min_count: int = 3000, max_count: int = 6000) -> None:
        self.min_count = min_count
        self.max_count = max_count

    def audit(self, df: pl.DataFrame) -> dict[str, Any]:
        if "trade_date" not in df.columns or "symbol" not in df.columns:
            return {
                "truncated_dates_count": 0,
                "anomaly_dates_count": 0,
                "daily_distribution": pl.DataFrame(),
                "passed": True,
            }

        date_counts = df.group_by("trade_date").agg(pl.count("symbol").alias("count")).sort("trade_date")
        anomaly_dates = date_counts.filter((pl.col("count") < self.min_count) | (pl.col("count") >= self.max_count))
        truncated_dates = date_counts.filter(pl.col("count") >= self.max_count)

        # 依据原逻辑，passed 判断中仅要求无截断天数（即数据量过大异常），若有异常天数（量少）仅报警
        return {
            "truncated_dates_count": len(truncated_dates),
            "anomaly_dates_count": len(anomaly_dates),
            "daily_distribution": date_counts,
            "passed": len(truncated_dates) == 0,
        }
