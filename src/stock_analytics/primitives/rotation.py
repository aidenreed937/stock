"""ETF/行业轮动动量算子 (Rotation Primitives)。

本模块为纯函数、无状态向量化原语，零内部业务依赖，仅依赖 Polars。
包含多周期加权动量、动量加速度与截面相对强弱 RPS 三类轮动因子，
用于 ETF 与行业板块之间的轮动强弱度量与排序。

权威依据：
    - 多周期加权动量 (Weighted Momentum) 参考 Carhart (1997) 四因子模型中
      动量因子 (UMD) 的多周期收益加权思想，以多个回看窗口收益率的加权和
      度量标的趋势强度，权重自动归一化为 1；
    - 动量加速度 (Momentum Acceleration) 为动量的二阶衍生量，以短期收益
      斜率减长期收益斜率度量动量本身的边际变化（快慢动量差，类 MACD 柱）；
    - 相对强弱 RPS (Relative Price Strength) 参考 William O'Neil CANSLIM
      体系中的 Relative Strength 指标，以截面内 N 日收益率的最小名次分位
      (Rank_min / Count * 100) 度量标的在同类资产中的相对强弱排名。
"""

from __future__ import annotations

import polars as pl


def calculate_weighted_momentum(
    df: pl.DataFrame,
    windows: tuple[int, ...] = (20, 60, 120),
    weights: tuple[float, ...] = (0.5, 0.3, 0.2),
    price_col: str = "close",
) -> pl.DataFrame:
    """计算多周期加权动量因子 (Weighted Momentum)。

    公式: weighted_momentum = Sum(w_i * R_{w_i})
          R_w = (P_t / P_{t-w} - 1) * 100，为 N 日收益率百分数。

    weights 长度必须与 windows 一致，否则抛出 ValueError；权重自动归一化
    为 1（按权重之和缩放）。任一周期收益缺失时结果透传 null（fail-closed）；
    含 symbol 列时各标的独立计算。
    """
    if df.is_empty() or price_col not in df.columns:
        return df
    if len(windows) != len(weights):
        raise ValueError("windows 与 weights 长度必须一致")
    if not windows:
        return df
    total = sum(weights)
    if total <= 0:
        raise ValueError("weights 之和必须为正")
    norm_weights = [w / total for w in weights]

    has_symbol = "symbol" in df.columns
    terms: list[pl.Expr] = []
    for w, weight in zip(windows, norm_weights):
        if has_symbol:
            ret = (pl.col(price_col) / pl.col(price_col).shift(w).over("symbol") - 1.0) * 100.0
        else:
            ret = (pl.col(price_col) / pl.col(price_col).shift(w) - 1.0) * 100.0
        terms.append(weight * ret)

    expr = terms[0]
    for term in terms[1:]:
        expr = expr + term
    return df.with_columns(expr.alias("weighted_momentum"))


def calculate_momentum_acceleration(
    df: pl.DataFrame,
    fast: int = 20,
    slow: int = 60,
    price_col: str = "close",
) -> pl.DataFrame:
    """计算动量加速度因子 (Momentum Acceleration)。

    公式: momentum_acceleration = R_fast - R_slow
          R_w = (P_t / P_{t-w} - 1) * 100。

    以短期收益斜率减去长期收益斜率，度量动量本身的边际变化（动量二阶信息，
    正值表示短期动能强于长期、负值表示短期动能衰减）。任一周期收益缺失时
    结果透传 null（fail-closed）；含 symbol 列时各标的独立计算。
    """
    if df.is_empty() or price_col not in df.columns:
        return df
    has_symbol = "symbol" in df.columns
    col_name = f"momentum_acceleration_{fast}_{slow}"
    if has_symbol:
        fast_ret = (pl.col(price_col) / pl.col(price_col).shift(fast).over("symbol") - 1.0) * 100.0
        slow_ret = (pl.col(price_col) / pl.col(price_col).shift(slow).over("symbol") - 1.0) * 100.0
    else:
        fast_ret = (pl.col(price_col) / pl.col(price_col).shift(fast) - 1.0) * 100.0
        slow_ret = (pl.col(price_col) / pl.col(price_col).shift(slow) - 1.0) * 100.0
    return df.with_columns((fast_ret - slow_ret).alias(col_name))


def calculate_rps(
    df: pl.DataFrame,
    window: int = 60,
    price_col: str = "close",
    group_col: str = "trade_date",
) -> pl.DataFrame:
    """计算截面相对强弱 RPS 因子 (Relative Price Strength)。

    公式: RPS = Rank_min(R_w) / Count(R_w) * 100，区间 0~100
          R_w = (P_t / P_{t-w} - 1) * 100。

    在每个 group_col（默认交易日）截面内独立排名，最小名次制（并列共享名次），
    最高收益标的名次等于样本数、RPS=100；最低收益标的名次为 1、RPS 为最低
    分位。收益缺失或截面样本不足时透传 null。含 symbol 列时 N 日收益按标的
    独立计算；df 缺少 group_col 列时返回原帧（fail-closed）。
    """
    if df.is_empty() or price_col not in df.columns or group_col not in df.columns:
        return df
    has_symbol = "symbol" in df.columns
    ret_col = f"__rps_ret_{window}d"
    if has_symbol:
        ret_expr = (
            pl.col(price_col) / pl.col(price_col).shift(window).over("symbol") - 1.0
        ) * 100.0
    else:
        ret_expr = (pl.col(price_col) / pl.col(price_col).shift(window) - 1.0) * 100.0
    # 先物化收益列再截面排名，避免嵌套 window 表达式（over symbol × over group）语义失效
    group = pl.col(group_col)
    rank = pl.col(ret_col).rank("min").over(group)
    n_valid = pl.col(ret_col).count().over(group)
    rps_expr = (
        pl.when(pl.col(ret_col).is_not_null() & (n_valid >= 1))
        .then(rank / n_valid * 100.0)
        .otherwise(None)
    )
    return (
        df.with_columns(ret_expr.alias(ret_col))
        .with_columns(rps_expr.alias(f"rps_{window}d"))
        .drop(ret_col)
    )


__all__ = [
    "calculate_momentum_acceleration",
    "calculate_rps",
    "calculate_weighted_momentum",
]
