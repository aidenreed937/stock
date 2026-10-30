#!/usr/bin/env python3
"""商品段（product_key×unit_segment）金额 yoy 分位排名（双口径）。

读取 ``data/analytics/industry/customs_product_volume_price.parquet``，取最新
report_month，输出两个分位口径：

- 横截面分位 ``pct_rank_0_100``：各段之间当期金额 3MMA yoy 的百分位排名
  （quant-metric-standards：``(rank_min - 1) / (N - 1) * 100``，并列共享最小名次）；
- 自身 36 月分位 ``pct_self_36m``：每段自己在近 36 个频点内金额 yoy
  ``≤ 当前值`` 的有效样本占比 × 100（与 L2/L3 观察表 ``yoy_pct_36m`` 同口径，
  有效样本 <12 或 yoy 缺失时为空）；
- 景气周期阶段 ``景气阶段``：基于 36m 分位 + 金额 yoy + 驱动类型 + 拐点，
  分四阶段（与 12 号观察文档同构）：① 景气启动/扩张、② 狂热高潮、
  ③ 扩张放缓（量歇价升/量价双弱）、④ 需求萎缩（含量先转正的底部形态与见顶拐点）。

``--sort`` 选择排序口径：``cross``（默认，横截面分位降序）或 ``self``
（自身 36 月分位降序）。

产出:
- 终端: Markdown 排名表（``--top`` 控制行数，0=全部）；
- CSV: ``data/analytics/industry/customs_product_pct_rank_latest.csv``
  （yoy 列保持 parquet 原始小数口径，与既有 ``_latest.csv`` 约定一致）。

用法:
    uv run python scripts/customs_product_pct_rank.py [--top 40] [--sort cross|self]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl

PANEL = Path("data/analytics/industry/customs_product_volume_price.parquet")
OUT_CSV = Path("data/analytics/industry/customs_product_pct_rank_latest.csv")

YOY_COLS = ("value_yoy_3mma", "volume_yoy_3mma", "price_yoy_3mma")
NUM_COLS = YOY_COLS + ("export_value_usd",)


def _emp_pct_36m(grp: pl.DataFrame) -> pl.DataFrame:
    """近 36 频点内自身金额 yoy 分位（≤ 当前值的有效样本占比 × 100，≥12 样本）。"""
    ys = grp.sort("report_month")
    vals = ys["value_yoy_3mma"].to_list()
    out = []
    for i in range(len(vals)):
        lo = max(0, i - 35)
        win = [v for v in vals[lo : i + 1] if v is not None]
        cur = vals[i]
        out.append(
            None
            if (cur is None or len(win) < 12)
            else round(sum(1 for v in win if v <= cur) / len(win) * 100, 1)
        )
    return ys.with_columns(pl.Series("pct_self_36m", out))


def add_self_pct_36m(panel: pl.DataFrame) -> pl.DataFrame:
    """按商品段逐段计算自身 36 月增长分位（与 L2/L3 观察表 yoy_pct_36m 同口径）。"""
    df = panel.with_columns(pl.col("value_yoy_3mma").fill_nan(None))
    return pl.concat([_emp_pct_36m(g) for _, g in df.group_by("seg_key")]).select(
        ["seg_key", "report_month", "pct_self_36m"]
    )


def _stage_expr() -> pl.Expr:
    """景气周期阶段（自身36m分位 + 金额yoy + 驱动 + 拐点的组合判读）。"""
    pct = pl.coalesce(pl.col("pct_self_36m"), 50.0)
    return (
        pl.when(pl.col("拐点") == "见顶拐点")
        .then(pl.lit("④ 见顶拐点"))
        .when(pl.col("value_yoy_3mma") <= 0)
        .then(
            pl.when(pl.col("驱动类型") == "量驱动")
            .then(pl.lit("④ 需求萎缩(量先转正)"))
            .otherwise(pl.lit("④ 需求萎缩"))
        )
        .when(pl.col("拐点") == "启动拐点")
        .then(pl.lit("① 景气启动"))
        .when(pl.col("驱动类型") == "量价齐升")
        .then(pl.when(pct >= 85).then(pl.lit("② 狂热高潮")).otherwise(pl.lit("① 景气扩张/主升")))
        .when(pl.col("驱动类型") == "量驱动")
        .then(
            pl.when(pct >= 85)
            .then(pl.lit("② 狂热高潮(量驱动)"))
            .otherwise(pl.lit("① 景气扩张(量驱动)"))
        )
        .when(pl.col("驱动类型") == "价驱动")
        .then(pl.lit("③ 扩张放缓(量歇价升)"))
        .when(pl.col("驱动类型") == "双弱")
        .then(pl.lit("③ 扩张放缓(量价双弱)"))
        .otherwise(
            pl.when(pct >= 85)
            .then(pl.lit("② 高位(量价不可判)"))
            .otherwise(pl.lit("① 扩张(量价不可判)"))
        )
        .alias("景气阶段")
    )


def build_rank(panel: pl.DataFrame, sort_by: str = "cross") -> pl.DataFrame:
    """最新月商品段金额 yoy：横截面分位 + 自身 36 月增长分位（0~100）。"""
    latest_month = panel["report_month"].max()
    self_pct = add_self_pct_36m(panel)
    df = (
        panel.filter(pl.col("report_month") == latest_month)
        .with_columns([pl.col(c).fill_nan(None) for c in NUM_COLS])
        .join(self_pct, on=["seg_key", "report_month"], how="left")
    )
    df = df.filter(pl.col("value_yoy_3mma").is_not_null())

    n = df.height
    if n == 0:
        raise ValueError("最新月没有有效金额 yoy 段")
    if n == 1:
        df = df.with_columns(pl.lit(50.0).alias("pct_rank_0_100"), pl.lit(1).alias("rank"))
    else:
        df = df.with_columns(pl.col("value_yoy_3mma").rank(method="min").alias("rank"))
        df = df.with_columns(
            ((pl.col("rank") - 1) / (n - 1) * 100).round(1).alias("pct_rank_0_100")
        )

    out = df.with_columns(_stage_expr()).select(
        [
            "rank",
            "pct_rank_0_100",
            "pct_self_36m",
            "seg_key",
            "product_key",
            "unit_segment",
            "product_name",
            "report_month",
            "export_value_usd",
            "value_yoy_3mma",
            "volume_yoy_3mma",
            "price_yoy_3mma",
            "驱动类型",
            "拐点",
            "二阶导",
            "景气阶段",
            "target_l1_name",
            "target_l2_names",
            "target_l3_names",
        ]
    )
    if sort_by == "self":
        out = out.sort(["pct_self_36m", "value_yoy_3mma"], descending=True, nulls_last=True)
    else:
        out = out.sort(["pct_rank_0_100", "value_yoy_3mma"], descending=True)
    return out.with_columns(pl.lit(n).alias("n_segments"))


def _pct(v: object) -> str:
    if v is None:
        return "—"
    return f"{float(v) * 100:+.1f}%"


def _usd_100m(v: object) -> str:
    if v is None:
        return "—"
    return f"{float(v) / 1e8:.2f}亿$"


def _pct100(v: object) -> str:
    return "—" if v is None else f"{float(v):.1f}"


def print_markdown(df: pl.DataFrame, top: int) -> None:
    rows = df.head(top) if top > 0 else df
    print(
        "| 横截面排名 | 横截面分位 | 自身36m分位 | 商品段 | 产品 | 单位段 | 金额yoy | 量yoy | "
        "价yoy | 驱动 | 拐点 | 二阶导 | 景气阶段 | 最新月金额 | L2 | L3 |"
    )
    print(
        "| --: | --: | --: | :-- | :-- | :-- | --: | --: | --: | :-- | :-- | :-- | "
        ":-- | --: | :-- | :-- |"
    )
    for r in rows.iter_rows(named=True):
        print(
            f"| {r['rank']} | {_pct100(r['pct_rank_0_100'])} | {_pct100(r['pct_self_36m'])} | "
            f"{r['seg_key']} | {r['product_name']} | {r['unit_segment']} | "
            f"{_pct(r['value_yoy_3mma'])} | {_pct(r['volume_yoy_3mma'])} | "
            f"{_pct(r['price_yoy_3mma'])} | {r['驱动类型'] or '—'} | {r['拐点'] or '—'} | "
            f"{r['二阶导'] or '—'} | {r['景气阶段'] or '—'} | {_usd_100m(r['export_value_usd'])} | "
            f"{r['target_l2_names'] or '—'} | {r['target_l3_names'] or '—'} |"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--top",
        type=int,
        default=40,
        help="终端输出行数（0=全部）",
    )
    parser.add_argument(
        "--sort",
        choices=("cross", "self"),
        default="cross",
        help="排序口径：cross=商品段间横截面分位；self=自身36月增长分位",
    )
    args = parser.parse_args()

    if not PANEL.exists():
        raise SystemExit(
            f"缺少商品面板: {PANEL}（先运行 `uv run python -m stock_cli.customs_prosperity`）"
        )

    panel = pl.read_parquet(PANEL)
    rank = build_rank(panel, sort_by=args.sort)

    # CSV 统一按横截面分位降序落盘（与打印排序解耦，保证产物顺序稳定）
    csv_out = (
        rank
        if args.sort == "cross"
        else rank.sort(["pct_rank_0_100", "value_yoy_3mma"], descending=True)
    )
    csv_out.write_csv(OUT_CSV)
    print(
        f"=== 商品段景气度分位排名（最新月 {rank['report_month'][0]}，"
        f"有效段 {rank['n_segments'][0]}，排序={args.sort}）==="
    )
    print_markdown(rank, args.top)
    print(f"\n完整 CSV: {OUT_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
