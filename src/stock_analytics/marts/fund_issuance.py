"""公募基金月度新发规模与情绪领域 Mart。

从公募基金基础信息表 (fund_basic) 聚合全市场各月度新发基金只数与规模，
细分偏股型 (股票型+混合型)、债券型及其他基金，并计算偏股新发规模与数量的
5 年滚动历史百分位 (Pct5Y)，用于刻画场外增量资金弹药与基民情绪过热/冰点。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from stock_core.utils.logger import logger
from stock_data.catalog import DataCatalog

FUND_ISSUANCE_MART_NAME = "fund_issuance_monthly"

FUND_ISSUANCE_SCHEMA: dict[str, Any] = {
    "month": pl.Utf8,
    "total_fund_count": pl.Int64,
    "total_issue_amount_yi": pl.Float64,
    "equity_fund_count": pl.Int64,
    "equity_fund_count_pct5y": pl.Float64,
    "equity_issue_amount_yi": pl.Float64,
    "bond_fund_count": pl.Int64,
    "bond_issue_amount_yi": pl.Float64,
    "other_fund_count": pl.Int64,
    "other_issue_amount_yi": pl.Float64,
    "equity_issue_ma12m_yi": pl.Float64,
    "equity_issue_pct5y": pl.Float64,
}

EQUITY_FUND_TYPES = frozenset(
    {"股票型", "混合型", "偏股混合型", "平衡混合型", "灵活配置型", "指数型"}
)
BOND_FUND_TYPES = frozenset({"债券型", "保本型", "偏债混合型", "固收+"})


def empty_fund_issuance() -> pl.DataFrame:
    """返回稳定 schema 的空公募月度新发规模 Mart。"""
    return pl.DataFrame(schema=FUND_ISSUANCE_SCHEMA)


def _rolling_percentile_5y(values: list[float | None], window: int = 60) -> list[float | None]:
    """计算滚动 5 年 (60 个月) 历史百分位 [0.0, 100.0]。

    当月发行规模缺失（``None``，上游 issue_amount 未落地）时返回 ``None``，
    不拿「缺数」参与分位计算，避免把空白月份当成「零发行」压在分位最底部。
    """
    percentiles: list[float | None] = []
    for i in range(len(values)):
        cur = values[i]
        if cur is None:
            percentiles.append(None)
            continue
        start_idx = max(0, i - window + 1)
        sub = [v for v in values[start_idx : i + 1] if v is not None]
        if not sub:
            percentiles.append(None)
            continue
        count_less = sum(1 for x in sub if x < cur)
        count_equal = sum(1 for x in sub if x == cur)
        pct = (count_less + 0.5 * count_equal) / len(sub) * 100.0
        percentiles.append(round(pct, 2))
    return percentiles


def build_fund_issuance_frame(fund_basic: pl.DataFrame) -> pl.DataFrame:
    """从 fund_basic 基础信息表聚合月度新发规模与偏股情绪指标。

    Args:
        fund_basic: 基金基础信息表，需包含 ts_code, found_date/issue_date,
                    fund_type, issue_amount 等字段。

    Returns:
        pl.DataFrame: 月频公募新发规模与 5Y 滚动百分位特征表。
    """
    if fund_basic.is_empty():
        return empty_fund_issuance()

    # 1. 规范化成立日期 / 发行日期并提取月份 (YYYY-MM)
    date_col = None
    for cand in ("found_date", "issue_date", "list_date"):
        if cand in fund_basic.columns:
            date_col = cand
            break

    if date_col is None:
        logger.warning("fund_basic 缺失成立或发行日期列 (found_date/issue_date)")
        return empty_fund_issuance()

    # 2. 提取月份与标准化发行份额 (亿元)
    df = fund_basic.with_columns(
        [
            pl.col(date_col).cast(pl.Utf8, strict=False).alias("_raw_date"),
            pl.col("fund_type").fill_null("其他").cast(pl.Utf8).alias("_fund_type"),
        ]
    )

    # 过滤空日期与异常格式日期
    df = df.filter(
        pl.col("_raw_date").is_not_null()
        & (pl.col("_raw_date").str.len_chars() >= 6)
        & ~pl.col("_raw_date").str.starts_with("19")
        & ~pl.col("_raw_date").str.starts_with("00")
    )

    if df.is_empty():
        return empty_fund_issuance()

    # 转换月份为 YYYY-MM
    df = df.with_columns(
        pl.col("_raw_date")
        .map_elements(
            lambda s: f"{s[:4]}-{s[4:6]}" if len(s) >= 6 and s[4] != "-" else s[:7],
            return_dtype=pl.Utf8,
        )
        .alias("month")
    )

    # 提取 issue_amount 并归一为亿元；保留 null（缺失不得伪造成 0 发行）
    if "issue_amount" in df.columns:
        # 兼容两种可能：已转为元 (>> 1e5) 或原生亿元
        df = df.with_columns(pl.col("issue_amount").cast(pl.Float64, strict=False))
        max_amt_val = df["issue_amount"].max()
        max_amt = float(max_amt_val) if isinstance(max_amt_val, int | float) else 0.0
        amt_factor = 1e8 if max_amt > 100_000.0 else 1.0

        df = df.with_columns((pl.col("issue_amount") / amt_factor).alias("amount_yi"))
    else:
        df = df.with_columns(pl.lit(None, dtype=pl.Float64).alias("amount_yi"))

    # 3. 标记基金分类
    df = df.with_columns(
        [
            pl.col("_fund_type")
            .map_elements(
                lambda t: any(kw in t for kw in ("股票", "混合", "指数")),
                return_dtype=pl.Boolean,
            )
            .alias("is_equity"),
            pl.col("_fund_type")
            .map_elements(
                lambda t: any(kw in t for kw in ("债券", "保本", "固收")),
                return_dtype=pl.Boolean,
            )
            .alias("is_bond"),
        ]
    )

    # 4. 按月度 GroupBy 聚合
    monthly = (
        df.group_by("month")
        .agg(
            [
                pl.len().alias("total_fund_count"),
                pl.col("amount_yi").count().alias("_amount_rows"),
                pl.col("amount_yi").sum().round(4).alias("total_issue_amount_yi"),
                pl.col("is_equity").sum().alias("equity_fund_count"),
                pl.col("amount_yi")
                .filter(pl.col("is_equity"))
                .sum()
                .round(4)
                .alias("equity_issue_amount_yi"),
                pl.col("is_bond").sum().alias("bond_fund_count"),
                pl.col("amount_yi")
                .filter(pl.col("is_bond"))
                .sum()
                .round(4)
                .alias("bond_issue_amount_yi"),
            ]
        )
        .with_columns(
            [
                (
                    pl.col("total_fund_count")
                    - pl.col("equity_fund_count")
                    - pl.col("bond_fund_count")
                )
                .clip(lower_bound=0)
                .alias("other_fund_count"),
                (
                    pl.col("total_issue_amount_yi")
                    - pl.col("equity_issue_amount_yi")
                    - pl.col("bond_issue_amount_yi")
                )
                .clip(lower_bound=0.0)
                .round(4)
                .alias("other_issue_amount_yi"),
            ]
        )
        # 整月无任何 issue_amount（上游未落地）时，金额置 null 而非 0：
        # 「缺数」不是「零发行」，否则会被 12M 均线与 5Y 分位当成真实最低值。
        .with_columns(
            [
                pl.when(pl.col("_amount_rows") > 0)
                .then(pl.col(column))
                .otherwise(None)
                .alias(column)
                for column in (
                    "total_issue_amount_yi",
                    "equity_issue_amount_yi",
                    "bond_issue_amount_yi",
                    "other_issue_amount_yi",
                )
            ]
        )
        .drop("_amount_rows")
        .sort("month")
    )

    if monthly.is_empty():
        return empty_fund_issuance()

    # 5. 计算 12 个月移动均线与 5 年 (60 个月) 滚动历史百分位
    equity_amounts = monthly["equity_issue_amount_yi"].to_list()
    pct5y_list = _rolling_percentile_5y(equity_amounts, window=60)
    equity_counts = [
        float(value) if value is not None else None
        for value in monthly["equity_fund_count"].to_list()
    ]
    count_pct5y_list = _rolling_percentile_5y(equity_counts, window=60)

    result = monthly.with_columns(
        [
            pl.col("equity_issue_amount_yi")
            .rolling_mean(window_size=12, min_samples=1)
            .round(4)
            .alias("equity_issue_ma12m_yi"),
            pl.Series("equity_issue_pct5y", pct5y_list, dtype=pl.Float64),
            pl.Series("equity_fund_count_pct5y", count_pct5y_list, dtype=pl.Float64),
        ]
    )

    return result.select(list(FUND_ISSUANCE_SCHEMA))


def build_fund_issuance_mart(
    catalog: DataCatalog,
    output_dir: Path | None = None,
    overwrite: bool = True,
) -> pl.DataFrame:
    """从 DataCatalog 加载 fund_basic 并构建落盘公募月度新发 Mart。"""
    try:
        fund_basic = catalog.load_dataset("fund_basic")
    except Exception as e:
        logger.warning(f"从 DataCatalog 加载 fund_basic 黄金表失败 [{e}]")
        fund_basic = pl.DataFrame()

    mart_df = build_fund_issuance_frame(fund_basic)
    if mart_df.is_empty():
        logger.warning("构建得到的 fund_issuance_monthly 为空，跳过写入")
        return mart_df

    target_dir = output_dir or Path("data/curated/mart")
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{FUND_ISSUANCE_MART_NAME}.parquet"

    if overwrite or not target_path.exists():
        mart_df.write_parquet(target_path)
        logger.info(
            f"成功构建并物化公募月度新发规模 Mart: {target_path} ({len(mart_df)} 行月度记录)"
        )

    return mart_df
