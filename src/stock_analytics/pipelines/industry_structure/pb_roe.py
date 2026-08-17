"""行业 PB-ROE 横截面残差分析与性价比排序器。

计算逻辑:
    对 31 个申万行业在同一截面上拟合线性模型: PB_i = alpha + beta * ROE_i + residual_i
    residual_i = PB_i - (alpha + beta * ROE_i)
    残差显著为负 (实际 PB 显著低于该 ROE 对应的拟合 PB) 说明该行业被显著低估，具备更高配置性价比。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import polars as pl

from stock_analytics.models import IndustryPBROEResult
from stock_analytics.pipelines.industry_structure.classifier import IndustryClassifier
from stock_data.catalog import DataCatalog


def _extract_pb_roe_cols(sub: pl.DataFrame) -> pl.DataFrame:
    """提取行业 PB 与 ROE 清洗数据帧。"""
    pb_col = next((col for col in ["pb.ew", "pb.mcw", "pb"] if col in sub.columns), None)
    roe_col = next((col for col in ["roe.ttm", "roe", "m.roe.ttm"] if col in sub.columns), None)

    pb_expr = pl.col(pb_col).cast(pl.Float64).alias("pb") if pb_col else pl.lit(1.0).alias("pb")

    if roe_col:
        roe_expr = pl.col(roe_col).cast(pl.Float64).alias("roe")
    elif "pb.ew" in sub.columns and "pe_ttm.ew" in sub.columns:
        roe_expr = (pl.col("pb.ew") / pl.col("pe_ttm.ew") * 100.0).alias("roe")
    else:
        roe_expr = pl.lit(8.0).alias("roe")

    name_expr = pl.col("name") if "name" in sub.columns else pl.col("symbol").alias("name")

    return (
        sub.select([pl.col("symbol"), name_expr, pb_expr, roe_expr])
        .filter((pl.col("pb") > 0) & (pl.col("roe").is_not_null()))
        .drop_nulls()
    )


def _fit_linear_regression(
    pb_arr: np.ndarray, roe_arr: np.ndarray
) -> tuple[float, float, float, np.ndarray]:
    """执行 PB-ROE 线性回归拟合并返回参数与残差。"""
    try:
        poly = np.polyfit(roe_arr, pb_arr, deg=1)
        beta, alpha = float(poly[0]), float(poly[1])
        fit_pb = beta * roe_arr + alpha
        residuals = pb_arr - fit_pb
        ss_tot = float(np.sum((pb_arr - np.mean(pb_arr)) ** 2))
        ss_res = float(np.sum(residuals**2))
        r_squared = float(1.0 - (ss_res / ss_tot)) if ss_tot > 0 else 0.0
        return alpha, beta, r_squared, residuals
    except Exception:
        return 0.0, 0.0, 0.0, np.zeros(len(pb_arr))


class IndustryPBROEAnalyzer:
    """行业 PB-ROE 横截面残差分析器。"""

    def __init__(self, catalog: DataCatalog | None = None) -> None:
        """初始化分析器。"""
        self.catalog = catalog or DataCatalog(data_source="lixinger")
        self.classifier = IndustryClassifier()

    def analyze_cross_section(
        self,
        target_date: date | None = None,
        val_df: pl.DataFrame | None = None,
    ) -> IndustryPBROEResult | None:
        """分析指定日期的申万行业 PB-ROE 横截面拟合残差。"""
        raw_val = self.catalog.load_dataset("sw_2021_fundamental") if val_df is None else val_df
        if raw_val.is_empty():
            return None

        filtered = (
            raw_val.filter(pl.col("trade_date") <= target_date)
            if target_date is not None
            else raw_val
        )
        if filtered.is_empty():
            return None

        max_d = filtered["trade_date"].max()
        if max_d is None:
            return None
        sub = filtered.filter(pl.col("trade_date") == max_d)
        eval_date = max_d if isinstance(max_d, date) else date.fromisoformat(str(max_d))

        clean_df = _extract_pb_roe_cols(sub)
        if len(clean_df) < 5:
            return None

        alpha, beta, r_squared, residuals = _fit_linear_regression(
            clean_df["pb"].to_numpy(), clean_df["roe"].to_numpy()
        )

        results: list[dict[str, Any]] = []
        for idx, row in enumerate(clean_df.to_dicts()):
            res_val = float(residuals[idx])
            pb_val, roe_val = float(row["pb"]), float(row["roe"])
            sym_str = str(row["symbol"])
            name_val = self.classifier.resolve_name(sym_str)
            if not name_val or name_val == sym_str:
                name_val = str(row.get("name") or sym_str)

            results.append(
                {
                    "symbol": sym_str,
                    "name": name_val,
                    "pb": round(pb_val, 2),
                    "roe": round(roe_val, 2),
                    "fitted_pb": round(float(pb_val - res_val), 2),
                    "residual": round(res_val, 3),
                    "is_undervalued": bool(res_val < -0.1 and roe_val > 5.0),
                }
            )

        results.sort(key=lambda x: x["residual"])
        undervalued = [r["name"] for r in results if r["is_undervalued"]]

        return IndustryPBROEResult(
            trade_date=eval_date,
            regression_alpha=round(alpha, 3),
            regression_beta=round(beta, 4),
            r_squared=round(r_squared, 3),
            industries=results,
            undervalued_industries=undervalued,
        )
