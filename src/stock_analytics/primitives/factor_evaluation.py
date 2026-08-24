"""因子有效性检验原语：前向收益与 Rank IC 评估 (Factor IC Evaluation Primitives)。

本模块为纯函数、无状态向量化算子，零内部业务依赖，仅依赖 Polars 与标准库。
包含前向收益构造、Rank IC 序列、IC 汇总统计（ICIR/t 统计量/IC 衰减）与
累积 IC 序列等因子检验算子。

分层（Quantile）单调性与多空组合分析见同目录 `factor_quantile.py`。

权威依据：
    - Rank IC (Spearman 秩相关) 与 ICIR、t 统计量为业界标准因子检验框架
      （Alphalens、华泰金工《多因子选股系列之因子测试》等）；
    - ICIR 双口径：主口径不年化 (Mean(IC)/Std(IC))，与公开研报可横向比较；
      年化变体 (x sqrt(252)) 仅作量纲辅助，二者只差常数倍，不影响因子排名；
    - t 统计量 = Mean(IC) / (Std(IC) / sqrt(T))，不受年化选择影响。

口径说明：
    - 前向收益为名义收益（不含换仓/交易成本），以百分数输出 (2.5 表示 2.5%)；
    - 要求输入面板 (symbol, trade_date) 唯一且按交易日连续（无缺失行），
      否则前向收益以行距近似日距；
    - 缺失值 fail-closed：任一截面/分组样本不足时输出缺失，不推断、不填值。
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import polars as pl

# 日频年化交易日数（ICIR 年化辅助口径）
_ANNUALIZATION_TRADING_DAYS = 252


def add_forward_returns(
    df: pl.DataFrame,
    horizons: Sequence[int] = (1, 5, 20),
    price_col: str = "close",
) -> pl.DataFrame:
    """按标的计算未来 N 个交易日的前向收益率（百分数）。

    公式: fwd_ret_{h}d = (P_{t+h} / P_t - 1) * 100

    输入按 (symbol, trade_date) 排序后，组内 shift(-h) 取未来价格；
    无 symbol 列时按整表时序计算。末 h 行无未来数据时输出缺失（fail-closed）。

    Args:
        df: 日频面板，需含 trade_date（及可选 symbol）；要求 (symbol, trade_date) 唯一。
        horizons: 前向窗口列表（交易日数，如 1/5/20）。
        price_col: 价格基准列（建议传入复权后价格，如 close_adj）。

    Returns:
        排序后的输入帧并注入 fwd_ret_{h}d 列；缺 trade_date/价格列或空帧时原样返回。
    """
    if df.is_empty() or price_col not in df.columns or "trade_date" not in df.columns:
        return df

    has_symbol = "symbol" in df.columns
    sort_cols = ["symbol", "trade_date"] if has_symbol else ["trade_date"]
    ordered = df.sort(sort_cols)

    price = pl.col(price_col).cast(pl.Float64, strict=False)
    exprs = []
    for h in horizons:
        shifted = price.shift(-h).over("symbol") if has_symbol else price.shift(-h)
        exprs.append(
            pl.when(price > 0)
            .then((shifted / price - 1.0) * 100.0)
            .otherwise(None)
            .alias(f"fwd_ret_{h}d")
        )
    return ordered.with_columns(exprs)


def rank_ic_series(
    df: pl.DataFrame,
    factor_col: str,
    forward_cols: Sequence[str],
    group_col: str = "trade_date",
) -> pl.DataFrame:
    """按截面分组计算因子与前向收益的每日 Rank IC (Spearman) 长表。

    输出长表列: [group_col, horizon, ic]，horizon 为前向收益列名；
    组内有效样本不足 2 时 ic 为缺失（fail-closed）。

    Args:
        df: 含 factor_col 与各 forward_col 的面板。
        factor_col: 因子暴露列名。
        forward_cols: 前向收益列名列表（通常来自 add_forward_returns）。
        group_col: 截面分组列（通常为 trade_date）。

    Returns:
        [group_col, horizon, ic] 长表；缺失输入时返回同 Schema 空表。
    """
    valid_forward = [col for col in forward_cols if col in df.columns]
    if (
        df.is_empty()
        or factor_col not in df.columns
        or group_col not in df.columns
        or not valid_forward
    ):
        dtype: pl.DataType = df.schema[group_col] if group_col in df.columns else pl.String()
        return pl.DataFrame(schema={group_col: dtype, "horizon": pl.String, "ic": pl.Float64})

    wide = df.group_by(group_col).agg(
        pl.corr(factor_col, fwd, method="spearman").alias(fwd) for fwd in valid_forward
    )
    long = wide.unpivot(
        index=group_col, on=valid_forward, variable_name="horizon", value_name="ic"
    ).sort(group_col)
    # polars 对无法计算的截面（如全 null/零方差）返回 NaN 而非 null，统一归为缺失
    return long.with_columns(
        pl.when(pl.col("ic").is_nan()).then(None).otherwise(pl.col("ic")).alias("ic")
    )


def ic_summary(
    ic_df: pl.DataFrame, annualization: int = _ANNUALIZATION_TRADING_DAYS
) -> pl.DataFrame:
    """汇总 Rank IC 序列的统计量（每 horizon 一行）。

    输出列: horizon / n_days / ic_mean / ic_std / icir / icir_annualized /
    t_stat / ic_positive_ratio / cum_ic。

    口径:
        icir           = Mean(IC) / Std(IC)                      （主口径，不年化）
        icir_annualized = icir * sqrt(annualization)             （辅助口径）
        t_stat         = icir * sqrt(n_days)                     （显著性检验）
        ic_positive_ratio = Count(IC > 0) / n_days
        cum_ic         = Sum(IC)                                  （累积 IC 终点值）

    Args:
        ic_df: rank_ic_series 输出的长表（group_col, horizon, ic）。
        annualization: 年化交易日数（默认 252）。

    Returns:
        每 horizon 一行统计表，按 horizon 数值升序；空/缺列输入返回同 Schema 空表。
    """
    empty_schema = {
        "horizon": pl.String,
        "n_days": pl.Int64,
        "ic_mean": pl.Float64,
        "ic_std": pl.Float64,
        "icir": pl.Float64,
        "icir_annualized": pl.Float64,
        "t_stat": pl.Float64,
        "ic_positive_ratio": pl.Float64,
        "cum_ic": pl.Float64,
    }
    if ic_df.is_empty() or not {"horizon", "ic"}.issubset(ic_df.columns):
        return pl.DataFrame(schema=empty_schema)

    valid = ic_df.filter(pl.col("ic").is_not_null())
    if valid.is_empty():
        return pl.DataFrame(schema=empty_schema)

    stats = (
        valid.group_by("horizon")
        .agg(
            n_days=pl.col("ic").count(),
            ic_mean=pl.col("ic").mean(),
            ic_std=pl.col("ic").std(),
            ic_positive=(pl.col("ic") > 0).sum(),
            cum_ic=pl.col("ic").sum(),
        )
        .with_columns(
            icir=pl.when(pl.col("ic_std") > 0)
            .then(pl.col("ic_mean") / pl.col("ic_std"))
            .otherwise(None),
            icir_annualized=pl.when(pl.col("ic_std") > 0)
            .then(pl.col("ic_mean") / pl.col("ic_std") * math.sqrt(annualization))
            .otherwise(None),
            t_stat=pl.when(pl.col("ic_std") > 0)
            .then(pl.col("ic_mean") / (pl.col("ic_std") / pl.col("n_days").cast(pl.Float64).sqrt()))
            .otherwise(None),
            ic_positive_ratio=pl.col("ic_positive") / pl.col("n_days").cast(pl.Float64),
        )
        .drop("ic_positive")
    )
    stats = (
        stats.with_columns(
            pl.col("horizon").str.extract(r"(\d+)", 1).cast(pl.Float64).alias("_horizon_key")
        )
        .sort("_horizon_key")
        .drop("_horizon_key")
    )
    return stats.select(
        "horizon",
        "n_days",
        "ic_mean",
        "ic_std",
        "icir",
        "icir_annualized",
        "t_stat",
        "ic_positive_ratio",
        "cum_ic",
    )


def ic_decay(ic_df: pl.DataFrame) -> pl.DataFrame:
    """输出各 horizon 的平均 IC（信息衰减曲线数据）。

    即 ic_summary 的 horizon / ic_mean / n_days 子集，按 horizon 数值升序。

    Args:
        ic_df: rank_ic_series 输出的长表。

    Returns:
        [horizon, ic_mean, n_days] 表；空/缺列输入返回同 Schema 空表。
    """
    summary = ic_summary(ic_df)
    if summary.is_empty():
        return summary
    return summary.select("horizon", "ic_mean", "n_days")


def cumulative_ic(ic_df: pl.DataFrame, group_col: str = "trade_date") -> pl.DataFrame:
    """按 horizon 输出 IC 随时间累积序列（供累积 IC 图）。

    cum_ic = 自首个有效日期起 IC 的滚动累加；缺失 IC 行被跳过（不视为 0）。

    Args:
        ic_df: rank_ic_series 输出的长表。
        group_col: 时间列名。

    Returns:
        [group_col, horizon, cum_ic] 长表，按 group_col 升序；空输入返回同 Schema 空表。
    """
    empty_schema = {group_col: pl.String, "horizon": pl.String, "cum_ic": pl.Float64}
    if ic_df.is_empty() or not {group_col, "horizon", "ic"}.issubset(ic_df.columns):
        return pl.DataFrame(schema=empty_schema)

    valid = ic_df.filter(pl.col("ic").is_not_null())
    if valid.is_empty():
        return pl.DataFrame(schema=empty_schema)
    return (
        valid.sort(group_col)
        .with_columns(pl.col("ic").cum_sum().over("horizon").alias("cum_ic"))
        .select(group_col, "horizon", "cum_ic")
    )


__all__ = [
    "add_forward_returns",
    "cumulative_ic",
    "ic_decay",
    "ic_summary",
    "rank_ic_series",
]
