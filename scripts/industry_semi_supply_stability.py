"""半导体(270100)供给端腿稳定性全维验证."""

from __future__ import annotations

import datetime
import math
from pathlib import Path

import polars as pl
from scipy import stats

_START = datetime.date(2020, 5, 1)
_OOS = datetime.date(2022, 1, 1)
_POST = datetime.date(2024, 1, 1)
_PANEL = Path("data/curated/mart/industry_l2_panel_daily.parquet")
_LEGS = Path("data/curated/mart/semiconductor_supply_legs.parquet")
_OUT = Path("data/analytics/industry_strategy")
_SEGS = [
    ("2021-11-22", "2022-05-23", "2021Q4~2022H1"),
    ("2022-05-24", "2022-11-16", "2022H2"),
    ("2023-11-15", "2024-05-16", "2023Q4~2024H1"),
    ("2026-05-13", "2026-08-28", "2026洪峰后"),
]


def load():
    p = pl.read_parquet(_PANEL)
    semi = p.filter((pl.col("industry_code") == "270100") & (pl.col("trade_date") >= _START)).sort(
        "trade_date"
    )
    sl = (
        pl.read_parquet(_LEGS)
        .filter((pl.col("industry_code") == "270100") & (pl.col("trade_date") >= _START))
        .sort("trade_date")
    )
    return (
        semi.select(["trade_date", "close", "scissors_score"])
        .join(
            sl.select(["trade_date", "utilization_score", "inventory_score"]),
            on="trade_date",
            how="left",
        )
        .sort("trade_date")
        .with_columns(pl.col("close").pct_change().fill_null(0.0).alias("ret"))
    )


def weight(sc, inv, th):
    sc = sc if sc is not None else 50.0
    inv = inv if inv is not None else 50.0
    if sc < 0 and inv >= th:
        return 0.0
    if sc < 0 or inv >= th:
        return 0.3
    return 1.0


def metrics(arr):
    arr = [v if v > 0 else 1e-9 for v in arr]
    if len(arr) < 2:
        return (0.0, 0.0, 0.0)
    final, y = arr[-1], max(len(arr) / 252.0, 1e-9)
    cagr = ((final / arr[0]) ** (1.0 / y) - 1.0) * 100.0 if arr[0] > 0 else 0.0
    peak, mdd = -1e9, 0.0
    for v in arr:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak)
    rets = [arr[i] / arr[i - 1] - 1.0 for i in range(1, len(arr)) if arr[i - 1] > 0]
    mr = sum(rets) / len(rets) if rets else 0.0
    var = sum((r - mr) ** 2 for r in rets) / max(len(rets) - 1, 1) if len(rets) > 1 else 0.0
    sharpe = mr / math.sqrt(var) * math.sqrt(252.0) if var > 0 else 0.0
    return (cagr, mdd * 100.0, sharpe)


def combo(m, th):
    pos = [
        weight(r["scissors_score"], r["inventory_score"], th) * r["ret"]
        for r in m.iter_rows(named=True)
    ]
    return metrics((1 + pl.Series(pos)).cum_prod().to_list())


def buyhold(m):
    return metrics((1 + m["ret"]).cum_prod().to_list())


def yearly_ic(m):
    mm = m.with_columns(pl.col("close").shift(-60).alias("c60")).with_columns(
        (pl.col("c60") / pl.col("close") - 1.0).alias("f60")
    )
    rows = []
    for y in sorted(mm["trade_date"].dt.year().unique().to_list()):
        sub = mm.filter(pl.col("trade_date").dt.year() == y).drop_nulls(["f60"])
        row = {"year": y, "n": len(sub)}
        for col in ["utilization_score", "inventory_score", "scissors_score"]:
            s = sub.drop_nulls([col])
            row[col] = (
                round(stats.spearmanr(s[col].to_list(), s["f60"].to_list())[0], 3)
                if len(s) >= 30
                else None
            )
        rows.append(row)
    return pl.DataFrame(rows)


def threshold(m):
    rows = []
    for th in [40, 50, 60, 70, 80, 90]:
        f = combo(m, th)
        o = combo(m.filter(pl.col("trade_date") >= _OOS), th)
        p = combo(m.filter(pl.col("trade_date") >= _POST), th)
        rows.append(
            {
                "th": th,
                "fc": round(f[0], 1),
                "fd": round(f[1], 1),
                "fs": round(f[2], 2),
                "oc": round(o[0], 1),
                "od": round(o[1], 1),
                "os": round(o[2], 2),
                "pc": round(p[0], 1),
                "pd": round(p[1], 1),
                "ps": round(p[2], 2),
            }
        )
    return pl.DataFrame(rows)


def drawdown(m):
    rows = []
    for s, e, lab in _SEGS:
        seg = m.filter(
            (pl.col("trade_date") >= datetime.date.fromisoformat(s))
            & (pl.col("trade_date") <= datetime.date.fromisoformat(e))
        )
        h = buyhold(seg)[0]
        d = combo(seg, 70)[0]
        sh = (
            seg.filter(pl.col("inventory_score") >= 70).height / len(seg) * 100 if len(seg) else 0.0
        )
        rows.append(
            {"seg": lab, "hold": round(h, 1), "defense": round(d, 1), "doi_share": round(sh, 1)}
        )
    return pl.DataFrame(rows)


def main():
    m = load()
    _OUT.mkdir(parents=True, exist_ok=True)
    y = yearly_ic(m)
    t = threshold(m)
    d = drawdown(m)
    y.write_csv(_OUT / "industry_semi_supply_stability_ic.csv")
    t.write_csv(_OUT / "industry_semi_supply_stability_threshold.csv")
    d.write_csv(_OUT / "industry_semi_supply_stability_drawdown.csv")
    print("== 年度IC ==")
    print(y)
    print("\n== 阈值敏感性 ==")
    print(t)
    print("\n== 回撤段防御(th=70) ==")
    print(d)
    return y, t, d


if __name__ == "__main__":
    main()
