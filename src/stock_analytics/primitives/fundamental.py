"""杜邦拆解与财报质量原语 (Fundamental Primitives)。

本模块为纯函数、无状态财报分析原语，零内部业务依赖，仅依赖 Polars。
输入为标准化财报长表（列名由调用方保证，本模块只消费列名），
空帧或缺列一律原样返回（fail-closed），不做隐式推断或补缺。

权威依据：
- 杜邦分解 (DuPont Analysis)：ROE = 净利率 × 总资产周转率 × 权益乘数，
  经典财务分析框架（1912 年杜邦公司提出，见主流财务分析教材与
  《证券分析》相关章节）。
- 盈利现金含量 (OCF / 净利润)：度量应计利润与经营现金流的偏离程度，
  背景见 Sloan (1996) "Do Stock Prices Fully Reflect Information in
  Accruals and Cash Flows about Future Earnings?"（应计质量文献）。
- 增长加速度 (ΔYoY)：同比增速的一阶差分，刻画盈利增长动能的边际变化。
"""

from __future__ import annotations

import polars as pl


def dupond_decomposition(
    df: pl.DataFrame,
    *,
    net_income_col: str = "n_income",
    revenue_col: str = "revenue",
    total_assets_col: str = "total_assets",
    equity_col: str = "total_hldr_eqy_exc_min_int",
) -> pl.DataFrame:
    """对标准化财报长表做杜邦三因子拆解并合成 ROE。

    公式: ROE = 净利率 × 总资产周转率 × 权益乘数
        净利率 = 净利润 / 营业收入
        总资产周转率 = 营业收入 / 总资产
        权益乘数 = 总资产 / 归母权益

    任一比率分母为 0 或为负时输出 null（fail-closed），缺失值透传；
    任一必需列缺失时原样返回输入帧。

    Args:
        df: 标准化财报长表，需含净利润、营业收入、总资产与归母权益列。
        net_income_col: 净利润列名（默认 "n_income"）。
        revenue_col: 营业收入列名（默认 "revenue"）。
        total_assets_col: 总资产列名（默认 "total_assets"）。
        equity_col: 归母权益（不含少数股东权益）列名
            （默认 "total_hldr_eqy_exc_min_int"）。

    Returns:
        pl.DataFrame: 附加 net_profit_margin、asset_turnover、
            equity_multiplier、roe_dupont 四列的 DataFrame。
    """
    required = {net_income_col, revenue_col, total_assets_col, equity_col}
    if df.is_empty() or not required.issubset(df.columns):
        return df

    net_profit_margin = (
        pl.when(pl.col(revenue_col) > 0)
        .then(pl.col(net_income_col) / pl.col(revenue_col))
        .otherwise(None)
        .alias("net_profit_margin")
    )
    asset_turnover = (
        pl.when(pl.col(total_assets_col) > 0)
        .then(pl.col(revenue_col) / pl.col(total_assets_col))
        .otherwise(None)
        .alias("asset_turnover")
    )
    equity_multiplier = (
        pl.when(pl.col(equity_col) > 0)
        .then(pl.col(total_assets_col) / pl.col(equity_col))
        .otherwise(None)
        .alias("equity_multiplier")
    )
    factored = df.with_columns(
        net_profit_margin,
        asset_turnover,
        equity_multiplier,
    )
    roe_dupont = (
        pl.col("net_profit_margin") * pl.col("asset_turnover") * pl.col("equity_multiplier")
    ).alias("roe_dupont")
    return factored.with_columns(roe_dupont)


def earnings_quality(
    df: pl.DataFrame,
    *,
    net_income_col: str = "n_income",
    ocf_col: str = "n_cashflow_act",
) -> pl.DataFrame:
    """计算盈利现金含量（OCF / 净利润）。

    经营现金流净额对净利润的比率刻画应计利润与经营现金流的偏离
    （Sloan 1996 应计质量文献背景）：比率越高，净利润的现金支撑越充分。

    Args:
        df: 标准化财报长表，需含净利润与经营活动现金流净额列。
        net_income_col: 净利润列名（默认 "n_income"）。
        ocf_col: 经营活动现金流净额列名（默认 "n_cashflow_act"）。

    Returns:
        pl.DataFrame: 附加 ocf_to_net_profit 列的 DataFrame。
    """
    required = {net_income_col, ocf_col}
    if df.is_empty() or not required.issubset(df.columns):
        return df

    ocf_to_net_profit = (
        pl.when(pl.col(net_income_col) > 0)
        .then(pl.col(ocf_col) / pl.col(net_income_col))
        .otherwise(None)
        .alias("ocf_to_net_profit")
    )
    return df.with_columns(ocf_to_net_profit)


def growth_acceleration(
    df: pl.DataFrame,
    metric_col: str,
    *,
    level_col: str = "level",
) -> pl.DataFrame:
    """计算增长加速度（YoY 增速的一阶差分 ΔYoY）。

    level=1 表示最新报告期、level=2 表示上一期（调用方负责对齐财报期次）。
    实现为按 level 自连接对齐后相减：level=1 行输出 (level=1 值 − level=2 值)；
    对应 level=2 行缺失时输出 null。

    Args:
        df: 标准化财报长表，需含指标列与 level 列。
        metric_col: 待差分的指标列名（如同比增速 YoY）。
        level_col: 财报期次列名（默认 "level"，1 为最新期）。

    Returns:
        pl.DataFrame: 附加 {metric_col}_accel 列的 DataFrame。
    """
    required = {metric_col, level_col}
    if df.is_empty() or not required.issubset(df.columns):
        return df

    key_cols = [c for c in df.columns if c != metric_col and c != level_col]
    prev = df.select([*key_cols, level_col, metric_col]).rename(
        {level_col: "_prev_level", metric_col: "_prev_value"}
    )

    joined = df.join(
        prev,
        left_on=[*key_cols, pl.col(level_col) + 1],
        right_on=[*key_cols, "_prev_level"],
        how="left",
        suffix="_prev",
    )
    accel = (pl.col(metric_col) - pl.col("_prev_value")).alias(f"{metric_col}_accel")
    drop_cols = [f"{col}_prev" for col in key_cols] + ["_prev_level", "_prev_value"]
    return joined.with_columns(accel).drop(drop_cols)


__all__ = [
    "dupond_decomposition",
    "earnings_quality",
    "growth_acceleration",
]
