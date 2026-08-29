"""聪明钱组合信号构建：产业资本增持 + 大宗折价接盘 + 国家队股东锚点。

三个子信号（各自 0-100 滚动分位）等权合成日频 ``smart_money_score``，
供宏观因子管线（``data_fetchers.fetch_smart_money``）消费：

1. 产业资本增持: ``insider_activity_daily`` 董监高净增持金额 20 日滚动和,
   1250 日滚动分位 (announcement_date 对齐, PIT);
2. 大宗折价接盘: ``block_trade`` 折价深度×金额 (前收盘为基准) 日聚合,
   250 日滚动分位;
3. 国家队股东锚点: ``top10_floatholders`` 汇金/证金/社保/梧桐树净增持
   (ann_date 对齐, asof 生效), 500 日滚动分位。

用法:
    uv run python scripts/build_smart_money_signal.py [--output data/analytics/macro_strategy/smart_money_signal.parquet]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl

from stock_analytics.features import FeatureStore
from stock_analytics.primitives.rules import rolling_percentile
from stock_data.catalog import DataCatalog

DEFAULT_OUTPUT = Path("data/analytics/macro_strategy/smart_money_signal.parquet")

# 国家队主体关键词（排除过于宽泛的"中金"以避免券商误报）
NAT_TEAM_KEYWORDS = ("中央汇金", "汇金", "中国证券金融", "证金", "社保基金", "梧桐树")


def _trading_calendar(cat: DataCatalog) -> pl.DataFrame:
    close = cat.load_bars(
        symbol="000985.CSI", dataset="index_daily_bar", columns=["trade_date", "close"]
    )
    return close.select("trade_date").sort("trade_date")


def build_insider_score(cat: DataCatalog, cal: pl.DataFrame) -> pl.DataFrame:
    """产业资本增持分位：董监高净增持 20 日滚动和 → 1250 日滚动分位。"""
    fs = FeatureStore()
    try:
        ins = fs.get_domain_mart("insider_activity_daily")
    except Exception:
        ins = pl.DataFrame()
    if (
        ins.is_empty()
        or "announcement_date" not in ins.columns
        or "insider_net_buy_amount" not in ins.columns
    ):
        return cal.with_columns(pl.lit(None, dtype=pl.Float64).alias("insider_score"))
    daily = (
        cal.join(
            ins.select(
                pl.col("announcement_date").cast(pl.Date).alias("trade_date"),
                pl.col("insider_net_buy_amount").cast(pl.Float64, strict=False),
            ),
            on="trade_date",
            how="left",
        )
        .fill_null(0.0)
        .with_columns(pl.col("insider_net_buy_amount").rolling_sum(window_size=20).alias("_net20"))
    )
    return daily.with_columns(
        rolling_percentile("_net20", 1250, min_samples=500).alias("insider_score")
    ).select(["trade_date", "insider_score"])


def build_block_score(cat: DataCatalog, cal: pl.DataFrame) -> pl.DataFrame:
    """大宗折价接盘分位：每日 Σ 金额×(前收/成交价-1, 仅折价) → 250 日滚动分位。"""
    sd = (
        cat.load_dataset("stock_daily_bar")
        .select(["symbol", "trade_date", "close"])
        .sort(["symbol", "trade_date"])
    )
    sd = sd.with_columns(pl.col("close").shift(1).over("symbol").alias("prev_close"))
    bt = cat.load_dataset("block_trade").select(["symbol", "trade_date", "price", "amount"])
    merged = (
        bt.join(sd, on=["symbol", "trade_date"], how="left")
        .drop_nulls(subset=["prev_close"])
        .with_columns(
            (
                pl.col("amount")
                * (pl.col("prev_close") / pl.col("price") - 1.0).clip(lower_bound=0.0)
            ).alias("disc_depth")
        )
    )
    daily = cal.join(
        merged.group_by("trade_date").agg(pl.col("disc_depth").sum().alias("disc_depth")),
        on="trade_date",
        how="left",
    ).fill_null(0.0)
    return daily.with_columns(
        rolling_percentile("disc_depth", 250, min_samples=60).alias("block_score")
    ).select(["trade_date", "block_score"])


def build_national_team_score(cat: DataCatalog, cal: pl.DataFrame) -> pl.DataFrame:
    """国家队股东锚点分位：汇金/证金/社保/梧桐树净增持股数 (ann_date 生效) → 500 日分位。"""
    th = cat.load_dataset("top10_floatholders").select(["ann_date", "holder_name", "hold_change"])
    mask = pl.Series([False] * len(th))
    for kw in NAT_TEAM_KEYWORDS:
        mask = mask | th["holder_name"].str.contains(kw, literal=True)
    agg = (
        th.filter(mask & pl.col("hold_change").is_not_null())
        .group_by("ann_date")
        .agg(pl.col("hold_change").sum().alias("net_change"))
        .with_columns(pl.col("ann_date").cast(pl.Date))
        .sort("ann_date")
    )
    asof = cal.join_asof(agg, left_on="trade_date", right_on="ann_date", strategy="backward")
    return asof.with_columns(
        rolling_percentile("net_change", 500, min_samples=20).alias("nat_score")
    ).select(["trade_date", "nat_score"])


def main() -> None:
    parser = argparse.ArgumentParser(description="构建聪明钱组合信号并落盘。")
    parser.add_argument("--output", type=str, default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    cat = DataCatalog(data_source="tushare")
    cal = _trading_calendar(cat)

    insider = build_insider_score(cat, cal)
    block = build_block_score(cat, cal)
    nat = build_national_team_score(cat, cal)

    signal = (
        cal.join(insider, on="trade_date", how="left")
        .join(block, on="trade_date", how="left")
        .join(nat, on="trade_date", how="left")
        .with_columns(
            pl.mean_horizontal(["insider_score", "block_score", "nat_score"]).alias(
                "smart_money_score"
            )
        )
        .sort("trade_date")
    )
    signal.write_parquet(out)
    non_null = signal["smart_money_score"].is_not_null().sum()
    print(
        f"聪明钱组合信号已落盘: {out} ({len(signal)} 行, "
        f"{signal['trade_date'].min()} ~ {signal['trade_date'].max()}, 组合分位非空 {non_null})"
    )


if __name__ == "__main__":
    main()
