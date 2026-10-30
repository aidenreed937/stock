#!/usr/bin/env python3
"""电网设备 2023-2024 量驱动期公司筛选（决策时点 asof，无前视）。

口径：质量硬门 = 决策时点的「最新（当前）财报」——每个公司取其「第 2 个放量月」
为决策月，财报取 ``ann_date ≤ 决策月末`` 的最新报告期（or_yoy / dt_netprofit_yoy）；
资金腿 = 截至决策月末的 20 交易日主力净流入（tushare moneyflow）。

筛选门槛：
- 窗口 2023-10~2024-06；公司段出现 ≥2 个月「量驱动/量价齐升 且 量 yoy>0」；
- exp ≥ 0.2；金额 yoy > 0 月份 ≥ 2；
- 财报真扩张 = or_yoy>0 且 dt_netprofit_yoy>0；增收不增利 = or>0 且 dt≤0；
- 入选 = 真扩张 且 资金正；候选 = 真扩张 但资金负；其余剔除。

产出：
- data/analytics/industry/customs_grid_2023_2024_selection_asof.csv

用法：uv run python scripts/select_grid_2023_2024_asof.py
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from pathlib import Path

import polars as pl

EXPOSURE = Path("data/curated/mart/customs_company_h8_exposure.parquet")
PRODUCT_PANEL = Path("data/analytics/industry/customs_company_h8_product_panel.parquet")
OUT = Path("data/analytics/industry/customs_grid_2023_2024_selection_asof.csv")
FINA_FMT = "data/curated/tushare/market=CN/fina_indicator/year={y}/month={m:02d}/data.parquet"
MF_FMT = "data/curated/tushare/market=CN/moneyflow/year={y}/month={m:02d}/data.parquet"
WINDOW = ("2023-10", "2024-06")


def product_map() -> pl.DataFrame:
    e = pl.read_parquet(EXPOSURE)
    return e.select(["product_key", "target_l2_names"]).unique(subset=["product_key"], keep="first")


def decisions(win: pl.DataFrame) -> pl.DataFrame:
    finite_pos = (
        pl.col("volume_yoy_3mma").is_not_null()
        & (~pl.col("volume_yoy_3mma").is_nan())
        & (pl.col("volume_yoy_3mma") > 0)
    )
    qual = pl.col("驱动类型").is_in(["量驱动", "量价齐升"]) & finite_pos
    rows = []
    for (sym, prod), g in win.group_by(["symbol", "product_key"]):
        qm = g.filter(qual)["report_month"].to_list()
        if len(qm) >= 2:
            dm = qm[1]
            y, m = int(dm[:4]), int(dm[5:7])
            rows.append(
                {
                    "symbol": sym,
                    "product": prod,
                    "decision_month": dm,
                    "decision_date": date(y, m, calendar.monthrange(y, m)[1]),
                    "drv_months": len(qm),
                }
            )
    return pl.DataFrame(rows)


def load_financial() -> pl.DataFrame:
    parts = []
    for y in (2023, 2024):
        for m in (3, 6, 9, 12):
            f = FINA_FMT.format(y=y, m=m)
            if Path(f).exists():
                parts.append(
                    pl.read_parquet(f).select(
                        ["symbol", "end_date", "ann_date", "or_yoy", "dt_netprofit_yoy"]
                    )
                )
    return (
        pl.concat(parts)
        .drop_nulls("ann_date")
        .with_columns(pl.col("ann_date").cast(pl.Date), pl.col("end_date").cast(pl.Date))
    )


def mf_asof(decision_date: date) -> pl.DataFrame:
    files = [MF_FMT.format(y=decision_date.year, m=decision_date.month)]
    prev = decision_date.replace(day=1) - timedelta(days=1)
    files.append(MF_FMT.format(y=prev.year, m=prev.month))
    frames = []
    for f in files:
        p = Path(f)
        if p.exists():
            frames.append(pl.read_parquet(p).select(["symbol", "trade_date", "net_mf_amount"]))
    m = pl.concat(frames).filter(pl.col("trade_date") <= decision_date).sort("trade_date")
    return (
        m.group_by("symbol")
        .tail(20)
        .group_by("symbol")
        .agg(pl.col("net_mf_amount").sum().alias("mf20"))
    )


def main() -> None:
    e = pl.read_parquet(EXPOSURE)
    pmap = product_map()
    grid_products = (
        pmap.filter(pl.col("target_l2_names") == "电网设备")["product_key"].unique().to_list()
    )
    pp = pl.read_parquet(PRODUCT_PANEL)
    win = pp.filter(
        pl.col("product_key").is_in(grid_products)
        & (pl.col("report_month") >= WINDOW[0])
        & (pl.col("report_month") <= WINDOW[1])
    ).sort(["symbol", "product_key", "report_month"])

    dec = decisions(win)
    fin = load_financial()
    exp = (
        e.filter(
            pl.col("product_key").is_in(grid_products)
            & (pl.col("report_month") >= WINDOW[0])
            & (pl.col("report_month") <= WINDOW[1])
        )
        .group_by(["symbol", "product_key"])
        .agg(pl.col("product_exposure").max().alias("exp"))
        .rename({"product_key": "product"})
    )
    names = pp.select(["symbol", "company_name"]).unique(subset=["symbol", "company_name"])

    rows = []
    for r in dec.iter_rows(named=True):
        vis = fin.filter(
            (pl.col("symbol") == r["symbol"]) & (pl.col("ann_date") <= r["decision_date"])
        ).sort("end_date")
        latest = vis.tail(1)
        fr = latest.row(0, named=True) if latest.height else None
        mf = mf_asof(r["decision_date"]).filter(pl.col("symbol") == r["symbol"])
        rows.append(
            {
                "symbol": r["symbol"],
                "product": r["product"],
                "decision_month": r["decision_month"],
                "drv_months": r["drv_months"],
                "end_date": fr["end_date"] if fr else None,
                "or_yoy": fr["or_yoy"] if fr else None,
                "dt_netprofit_yoy": fr["dt_netprofit_yoy"] if fr else None,
                "mf20": mf["mf20"].item() if mf.height else None,
            }
        )
    res = pl.DataFrame(rows)
    res = res.join(exp, on=["symbol", "product"], how="left").join(names, on="symbol", how="left")
    res = res.with_columns(
        pl.when((pl.col("or_yoy") > 0) & (pl.col("dt_netprofit_yoy") > 0))
        .then(pl.lit("真扩张"))
        .when((pl.col("or_yoy") > 0) & (pl.col("dt_netprofit_yoy") <= 0))
        .then(pl.lit("增收不增利"))
        .when(pl.col("or_yoy").is_not_null())
        .then(pl.lit("营收负/缺"))
        .otherwise(pl.lit("财报缺"))
        .alias("财报判定"),
        pl.when(pl.col("mf20") > 0)
        .then(pl.lit("资金正"))
        .otherwise(pl.lit("资金负"))
        .alias("资金20d"),
    )
    res = res.with_columns(
        pl.when((pl.col("财报判定") == "真扩张") & (pl.col("mf20") > 0))
        .then(pl.lit("入选"))
        .when(pl.col("财报判定") == "真扩张")
        .then(pl.lit("候选(资金负)"))
        .otherwise(pl.lit("剔除"))
        .alias("结论")
    )
    out = res.select(
        [
            "symbol",
            "company_name",
            "product",
            "decision_month",
            "end_date",
            "or_yoy",
            "dt_netprofit_yoy",
            "财报判定",
            "mf20",
            "资金20d",
            "结论",
            "drv_months",
        ]
    ).sort(["结论", "decision_month", "symbol"])
    out.write_csv(OUT)
    print(f"written: {OUT}  rows={out.height}")
    print("分布:", out.group_by("结论").len().sort("len", descending=True).to_dicts())
    print(
        "入选:",
        out.filter(pl.col("结论") == "入选")
        .select(["symbol", "company_name", "product", "decision_month"])
        .to_dicts(),
    )


if __name__ == "__main__":
    main()
