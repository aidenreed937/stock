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
        null_counts = {col: df[col].null_count() for col in self.columns if col in df.columns}
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
            return {"duplicate_records": 0, "missing_keys": missing_keys, "passed": False}

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
            missing = [col for col in required if col not in df.columns]
            return {"physical_errors": 0, "missing_ohlc_columns": missing, "passed": False}

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
                (
                    ((pl.col("close") - pl.col("pre_close")) / pl.col("pre_close") * 100)
                    - pl.col("pct_chg")
                )
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

        return {
            "calc_diff_errors": calc_diff_count,
            "spike_faults": spike_fault_count,
            "turnover_faults": turnover_fault_count,
            "passed": calc_diff_count == 0 and spike_fault_count == 0 and turnover_fault_count == 0,
        }


class CompletenessRule(BaseValidationRule):
    """时间轴完整性及数据截断/异常天数校验规则。"""

    def __init__(
        self,
        min_count: int = 3000,
        max_count: int = 6000,
        expected_counts: dict[Any, int] | None = None,
        min_coverage: float = 0.9,
    ) -> None:
        self.min_count = min_count
        self.max_count = max_count
        self.expected_counts = expected_counts or {}
        self.min_coverage = min_coverage

    def audit(self, df: pl.DataFrame) -> dict[str, Any]:
        if "trade_date" not in df.columns or "symbol" not in df.columns:
            return {
                "truncated_dates_count": 0,
                "anomaly_dates_count": 0,
                "daily_distribution": pl.DataFrame(),
                "passed": False,
            }

        date_counts = (
            df.group_by("trade_date").agg(pl.count("symbol").alias("count")).sort("trade_date")
        )
        if self.expected_counts:
            expected_df = pl.DataFrame(
                {
                    "trade_date": list(self.expected_counts),
                    "expected_count": list(self.expected_counts.values()),
                }
            )
            date_counts = date_counts.join(expected_df, on="trade_date", how="left").with_columns(
                pl.col("expected_count").fill_null(self.min_count)
            )
            min_allowed = (pl.col("expected_count") * self.min_coverage).ceil()
        else:
            min_allowed = pl.lit(self.min_count)
        anomaly_dates = date_counts.filter(
            (pl.col("count") < min_allowed) | (pl.col("count") >= self.max_count)
        )
        truncated_dates = date_counts.filter(pl.col("count") >= self.max_count)

        return {
            "truncated_dates_count": len(truncated_dates),
            "anomaly_dates_count": len(anomaly_dates),
            "daily_distribution": date_counts,
            "passed": len(truncated_dates) == 0 and len(anomaly_dates) == 0,
        }


class DistributionAuditRule(BaseValidationRule):
    """数值分布与相邻交易日数量级跳跃 (Step Ratio) 校验规则。

    校验项:
    1. 相邻交易日截面均值跳跃比率是否在 [min_step_ratio, max_step_ratio] 安全区间内 (专抓万元/元等单位裂痕);
    2. 非负数值列 (成交额、成交量、市值等) 是否存在非物理负值.
    """

    def __init__(
        self,
        value_cols: list[str] | None = None,
        max_step_ratio: float = 10.0,
        min_step_ratio: float = 0.1,
        non_negative_cols: list[str] | None = None,
    ) -> None:
        self.value_cols = value_cols or [
            "amount",
            "volume",
            "vol",
            "total_mv",
            "circ_mv",
            "float_mv",
            "close",
            "turnover_rate",
        ]
        self.max_step_ratio = max_step_ratio
        self.min_step_ratio = min_step_ratio
        self.non_negative_cols = non_negative_cols or [
            "amount",
            "volume",
            "vol",
            "total_mv",
            "circ_mv",
            "float_mv",
            "turnover_rate",
            "open",
            "high",
            "low",
            "close",
        ]

    def audit(self, df: pl.DataFrame) -> dict[str, Any]:
        if df.is_empty():
            return {
                "step_jump_faults": 0,
                "negative_faults": 0,
                "anomalies": [],
                "passed": True,
            }

        target_cols = [c for c in self.value_cols if c in df.columns]
        anomalies: list[dict[str, Any]] = []
        step_jump_faults = 0
        negative_faults = 0

        for col in target_cols:
            # 1. 负值校验
            if col in self.non_negative_cols:
                neg_count = len(df.filter(pl.col(col) < 0.0))
                if neg_count > 0:
                    negative_faults += neg_count
                    anomalies.append(
                        {
                            "column": col,
                            "type": "NEGATIVE_VALUE",
                            "count": neg_count,
                            "detail": f"字段 [{col}] 存在 {neg_count} 条非物理负值记录",
                        }
                    )

            # 2. 阶跃跳跃校验 (按日聚合均值)
            if "trade_date" in df.columns:
                daily_means = (
                    df.group_by("trade_date")
                    .agg(pl.col(col).mean().alias("mean_val"))
                    .drop_nulls(subset=["mean_val"])
                    .sort("trade_date")
                )
                if len(daily_means) > 1:
                    jumps = daily_means.with_columns(
                        (pl.col("mean_val") / pl.col("mean_val").shift(1)).alias("step_ratio")
                    ).filter(
                        (pl.col("step_ratio") > self.max_step_ratio)
                        | (pl.col("step_ratio") < self.min_step_ratio)
                    )
                    jump_count = len(jumps)
                    if jump_count > 0:
                        step_jump_faults += jump_count
                        for r in jumps.iter_rows(named=True):
                            anomalies.append(
                                {
                                    "date": str(r["trade_date"]),
                                    "column": col,
                                    "type": "STEP_JUMP",
                                    "ratio": float(r["step_ratio"]),
                                    "detail": f"{r['trade_date']} 字段 [{col}] 均值跳跃比率为 {r['step_ratio']:.2f}x",
                                }
                            )

        passed = step_jump_faults == 0 and negative_faults == 0
        return {
            "step_jump_faults": step_jump_faults,
            "negative_faults": negative_faults,
            "anomalies": anomalies,
            "passed": passed,
        }
