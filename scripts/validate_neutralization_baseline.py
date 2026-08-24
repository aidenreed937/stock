"""Phase 2 真实数据基线验证：行业+市值联合中性化（Ground Truth First）。

对 pe_ttm 因子做申万 L1 行业 + ln(circ_mv) 联合中性化，比较：
1. 中性化前后 与 circ_mv 的 Rank IC（市值暴露是否被剥离）；
2. 中性化前后 与 fwd_ret_20d 的 Rank IC / ICIR（Alpha 纯度变化）。
"""

from __future__ import annotations

from datetime import date

import polars as pl

from stock_analytics.primitives.factor_evaluation import ic_summary, rank_ic_series
from stock_analytics.primitives.neutralization import cross_sectional_neutralize
from stock_data.catalog import DataCatalog

CATALOG = DataCatalog()
START = date(2025, 8, 1)
END = date(2026, 8, 21)


def build_panel() -> pl.DataFrame:
    """加载日线 + 估值 + L1 行业映射，输出截面面板。"""
    bars = CATALOG.load_dataset(
        "stock_daily_bar", start_date=START, end_date=END, columns=["symbol", "trade_date", "close"]
    ).sort(["symbol", "trade_date"])
    basic = CATALOG.load_dataset(
        "daily_basic",
        start_date=START,
        end_date=END,
        columns=["symbol", "trade_date", "pe_ttm", "circ_mv"],
    )
    panel = bars.join(basic, on=["symbol", "trade_date"], how="left")

    # L1 行业成分映射（index_member 时点 join + index_classify L1 过滤）
    cls = CATALOG.load_dataset("index_classify", columns=["index_code", "level"])
    l1_codes = cls.filter(pl.col("level") == "L1")["index_code"].unique().to_list()
    mem = CATALOG.load_dataset(
        "index_member", columns=["index_code", "con_code", "in_date", "out_date"]
    )
    l1 = mem.filter(pl.col("index_code").is_in(l1_codes)).select(
        pl.col("con_code").alias("symbol"), "index_code", "in_date", "out_date"
    )
    panel = panel.join(
        l1,
        on="symbol",
        how="left",
        # 时点映射：in_date <= trade_date < out_date（含 out_date 为空=仍在职）
    )
    panel = panel.filter(
        (pl.col("in_date") <= pl.col("trade_date"))
        & ((pl.col("out_date").is_null()) | (pl.col("out_date") > pl.col("trade_date")))
    ).drop("in_date", "out_date")

    return panel


def main() -> None:
    panel = build_panel()
    print(f"面板: {panel.height} 行, 标的 {panel['symbol'].n_unique()}, 日期 {panel['trade_date'].n_unique()}")
    print(f"L1 行业覆盖: 映射成功 {panel['index_code'].is_not_null().sum()} / {panel.height}")

    # 前向收益 + 对数市值
    from stock_analytics.primitives.factor_evaluation import add_forward_returns

    panel = add_forward_returns(panel, horizons=(20,), price_col="close").with_columns(
        pl.col("circ_mv").log().alias("ln_circ_mv")
    )
    panel = panel.filter(
        pl.col("pe_ttm").is_not_null()
        & pl.col("ln_circ_mv").is_not_null()
        & pl.col("index_code").is_not_null()
    )
    print(f"有效截面样本: {panel.height}")

    # 中性化
    neutralized = cross_sectional_neutralize(
        panel, "pe_ttm", "index_code", ["ln_circ_mv"], output_col="pe_ttm_neutral"
    )

    # 1. 市值暴露对比：因子 vs ln_circ_mv 的 Rank IC
    def factor_ic(frame: pl.DataFrame, factor: str) -> pl.DataFrame:
        ic = rank_ic_series(frame, factor, ["ln_circ_mv"])
        return ic_summary(ic)

    print("\n=== 因子 vs ln_circ_mv 的 Rank IC（市值暴露）===")
    for factor in ["pe_ttm", "pe_ttm_neutral"]:
        s = factor_ic(neutralized, factor)
        row = s.row(0, named=True)
        print(
            f"  {factor:<16} IC={row['ic_mean']:.4f} ICIR={row['icir']:.3f} "
            f"t={row['t_stat']:.2f} n={row['n_days']}"
        )

    # 2. Alpha 纯度对比：因子 vs fwd_ret_20d
    print("\n=== 因子 vs fwd_ret_20d 的 Rank IC（预测力）===")
    for factor in ["pe_ttm", "pe_ttm_neutral"]:
        ic = rank_ic_series(neutralized, factor, ["fwd_ret_20d"])
        s = ic_summary(ic)
        row = s.row(0, named=True)
        print(
            f"  {factor:<16} IC={row['ic_mean']:.4f} ICIR={row['icir']:.3f} "
            f"t={row['t_stat']:.2f} n={row['n_days']}"
        )


if __name__ == "__main__":
    main()
