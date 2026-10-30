"""基金持仓明细的取值域清洗。

`fund_portfolio` 的 `stk_float_ratio`（占流通股比）与 `stk_mkv_ratio`（占股票投资
市值比）都以百分数表述，理论上限为 100。实测上游存在个别记录超过 100（例如
`stk_float_ratio = 130`），属源端个体异常；若直接进入下游，会让「基金持股占流通股
比例」「重仓股集中度」这类指标被单点异常值放大。

处理方式：只把越界的该字段置为 null 并计数告警，不丢弃整条持仓记录——被持有股票与
持仓市值仍然有效，丢弃记录会连带损失其他可用字段。
"""

from __future__ import annotations

import polars as pl

from stock_core.utils.logger import logger

# 百分数上限与容差：年度全持仓的占比加总在源端存在四舍五入（实测 P90 ≈ 100.02），
# 因此给 0.5 个百分点的容差，避免把正常舍入误判为异常。
RATIO_UPPER_BOUND = 100.0
RATIO_TOLERANCE = 0.5

_FUND_RATIO_COLUMNS: tuple[str, ...] = ("stk_float_ratio", "stk_mkv_ratio")


def sanitize_fund_portfolio_ratios(
    df: pl.DataFrame, endpoint: str = "fund_portfolio"
) -> pl.DataFrame:
    """把持仓占比中越界（>100.5 或 <0）的值置空，并记录异常条数。"""
    if df.is_empty():
        return df

    out = df
    for column in _FUND_RATIO_COLUMNS:
        if column not in out.columns:
            continue
        invalid = (pl.col(column) > RATIO_UPPER_BOUND + RATIO_TOLERANCE) | (pl.col(column) < 0)
        invalid_count = int(out.select(invalid.sum()).item() or 0)
        if invalid_count == 0:
            continue
        logger.warning(
            "基金持仓占比越界已置空 [%s.%s]: %d 条（上限 %.1f%%，容差 %.1f）",
            endpoint,
            column,
            invalid_count,
            RATIO_UPPER_BOUND,
            RATIO_TOLERANCE,
        )
        out = out.with_columns(pl.when(invalid).then(None).otherwise(pl.col(column)).alias(column))
    return out


__all__ = ["RATIO_TOLERANCE", "RATIO_UPPER_BOUND", "sanitize_fund_portfolio_ratios"]
