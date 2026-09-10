#!/usr/bin/env python3
"""出口金额 3MMA yoy × 财报 yoy 的领先-滞后相关（行业层逐序列，27 号文档）。

口径：
- 出口：产品级 `value_yoy_3mma`（`customs_company_exposure.parquet`），按
  `company_exposure_map.csv` 的 product_key→sw_l2 映射展开到申万二级行业，每月行业内
  产品简单均值；
- 财报：`fina_indicator` 的 `or_yoy`（营收累计同比）/ `netprofit_yoy`（净利累计同比）/
  `q_sales_yoy`（单季营收同比），锚定报告期末 `end_date`（季度末月）；
- 对齐：财报季度末月 - k 的出口 yoy vs 财报季度末月 yoy，k>0 = 出口领先财报 k 月，
  k<0 = 财报领先出口 |k| 月；
- 相关：每行业一条时间序列**单独**算 Pearson corr（≥12 个对齐点），横截面取中位数 +
  正占比。逐序列（而非 pooled）避免把不同行业×时间堆叠后被共同宏观 beta 抬高。

输出：k 从 --k-min 到 --k-max 的领先-滞后相关矩阵（打印 + 可选写 csv）。

用法:
    uv run python scripts/export_finance_lead_lag.py
    uv run python scripts/export_finance_lead_lag.py --output data/analytics/industry/export_finance_lead_lag.csv
"""

from __future__ import annotations

import argparse
import csv
import glob
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

import polars as pl

DEFAULT_EXP = "data/analytics/industry/customs_company_exposure.parquet"
DEFAULT_MAP = "config/data/customs/company_exposure_map.csv"
DEFAULT_FINA = "data/curated/tushare/market=CN/fina_indicator"
MIN_POINTS = 12


def _mint(s: str) -> int:
    """'YYYY-MM' → 整数月份编码（year*12 + month-1），便于做 ±k 月运算。"""
    y, m = s.split("-")
    return int(y) * 12 + int(m) - 1


def load_exports(path: str) -> dict[str, dict[int, float]]:
    df = pl.read_parquet(path)
    out: dict[str, dict[int, float]] = defaultdict(dict)
    for key, month, v in df.filter(pl.col("value_yoy_3mma").is_not_null()).select(
        ["key", "report_month", "value_yoy_3mma"]
    ).iter_rows():
        out[key][_mint(month)] = v
    return dict(out)


def load_map(path: str) -> tuple[dict[str, set[str]], dict[str, tuple[float, str]]]:
    """返回 (product_key → set[sw_l2], stock_code → (max_exposure, sw_l2))。

    同一公司绑多产品时取 exposure 最高的产品确定其 sw_l2 归属（与回测/信号口径一致）。
    """
    prod2l2: dict[str, set[str]] = defaultdict(set)
    best: dict[str, tuple[float, str]] = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            code = r["stock_code"]
            e = float(r["exposure"] or 0)
            l2 = (r["sw_l2"] or "").strip()
            if l2:
                prod2l2[r["product_key"]].add(l2)
            if code not in best or e > best[code][0]:
                best[code] = (e, l2)
    return dict(prod2l2), best


def load_fina(root: str) -> dict[str, dict[int, tuple[float | None, float | None, float | None]]]:
    """symbol → {季度末月整数编码: (or_yoy, netprofit_yoy, q_sales_yoy)}。"""
    files = sorted(glob.glob(str(Path(root) / "year=*" / "month=*" / "data.parquet")))
    out: dict[str, dict[int, tuple[float | None, float | None, float | None]]] = defaultdict(dict)
    for f in files:
        df = pl.read_parquet(f).select(
            ["symbol", "end_date", "or_yoy", "netprofit_yoy", "q_sales_yoy"]
        )
        for sym, end, ory, npy, qy in df.filter(
            (pl.col("or_yoy").is_not_null())
            | (pl.col("netprofit_yoy").is_not_null())
            | (pl.col("q_sales_yoy").is_not_null())
        ).iter_rows():
            out[sym][int(end.year) * 12 + int(end.month) - 1] = (ory, npy, qy)
    return dict(out)


def series_corr(xs: list[float], ys: list[float], min_points: int) -> float | None:
    if len(xs) < min_points:
        return None
    xm, ym = mean(xs), mean(ys)
    sx = sum((x - xm) ** 2 for x in xs) ** 0.5
    sy = sum((y - ym) ** 2 for y in ys) ** 0.5
    if sx == 0 or sy == 0:
        return None
    return sum((x - xm) * (y - ym) for x, y in zip(xs, ys)) / (sx * sy)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exp", default=DEFAULT_EXP)
    parser.add_argument("--map", default=DEFAULT_MAP)
    parser.add_argument("--fina", default=DEFAULT_FINA)
    parser.add_argument("--min-points", type=int, default=MIN_POINTS)
    parser.add_argument("--k-min", type=int, default=-3)
    parser.add_argument("--k-max", type=int, default=12)
    parser.add_argument("--output", default=None, help="可选 csv 输出路径")
    args = parser.parse_args()

    exports = load_exports(args.exp)
    prod2l2, best = load_map(args.map)
    fina = load_fina(args.fina)

    # 行业出口 yoy：每月行业内产品均值
    l2_exp: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for key, mm in exports.items():
        pk = key.split("::")[0]
        for l2 in prod2l2.get(pk, []):
            for m, v in mm.items():
                l2_exp[l2][m].append(v)
    l2_exp_mean = {l2: {m: mean(vs) for m, vs in mm.items()} for l2, mm in l2_exp.items()}

    # 行业财报中位数（季度）
    l2_fin: dict[str, dict[int, list[tuple]]] = defaultdict(lambda: defaultdict(list))
    for code, (_e, l2) in best.items():
        if not l2:
            continue
        for qm, (ory, npy, qy) in fina.get(code, {}).items():
            l2_fin[l2][qm].append((ory, npy, qy))
    l2_fin_med: dict[str, dict[int, tuple]] = {}
    for l2, mm in l2_fin.items():
        row: dict[int, tuple] = {}
        for m, vs in mm.items():
            ors = [x[0] for x in vs if x[0] is not None]
            nps = [x[1] for x in vs if x[1] is not None]
            qys = [x[2] for x in vs if x[2] is not None]
            row[m] = (
                median(ors) if ors else None,
                median(nps) if nps else None,
                median(qys) if qys else None,
            )
        l2_fin_med[l2] = row

    # 领先-滞后相关：逐行业算 corr，横截面汇总
    out_rows = []
    for k in range(args.k_min, args.k_max + 1):
        cors_or: list[float] = []
        cors_np: list[float] = []
        cors_q: list[float] = []
        for l2, em in l2_exp_mean.items():
            fm = l2_fin_med.get(l2)
            if not fm:
                continue
            xs_or: list[float] = []
            ys_or: list[float] = []
            xs_np: list[float] = []
            ys_np: list[float] = []
            xs_q: list[float] = []
            ys_q: list[float] = []
            for qm, (ory, npy, qy) in fm.items():
                xm = qm - k
                if xm not in em:
                    continue
                x = em[xm]
                if ory is not None:
                    xs_or.append(x)
                    ys_or.append(ory)
                if npy is not None:
                    xs_np.append(x)
                    ys_np.append(npy)
                if qy is not None:
                    xs_q.append(x)
                    ys_q.append(qy)
            c = series_corr(xs_or, ys_or, args.min_points)
            if c is not None:
                cors_or.append(c)
            c = series_corr(xs_np, ys_np, args.min_points)
            if c is not None:
                cors_np.append(c)
            c = series_corr(xs_q, ys_q, args.min_points)
            if c is not None:
                cors_q.append(c)

        def stat(cs: list[float]) -> tuple[float, float, int]:
            if not cs:
                return float("nan"), float("nan"), 0
            return median(cs), sum(1 for c in cs if c > 0) / len(cs), len(cs)

        m_or, p_or, n_or = stat(cors_or)
        m_np, p_np, _ = stat(cors_np)
        m_q, p_q, _ = stat(cors_q)
        out_rows.append(
            {
                "k": k,
                "rev_median_corr": m_or,
                "rev_pos_ratio": p_or,
                "np_median_corr": m_np,
                "np_pos_ratio": p_np,
                "q_median_corr": m_q,
                "q_pos_ratio": p_q,
                "n_industries": n_or,
            }
        )

    print(
        f"{'k':>4} {'营收累计corr':>12} {'正占比':>8} {'净利累计corr':>12} "
        f"{'正占比':>8} {'单季营收corr':>12} {'正占比':>8} {'行业数':>6}"
    )
    for r in out_rows:
        print(
            f"{r['k']:+4d} {r['rev_median_corr']:+12.3f} {r['rev_pos_ratio']*100:7.0f}% "
            f"{r['np_median_corr']:+12.3f} {r['np_pos_ratio']*100:7.0f}% "
            f"{r['q_median_corr']:+12.3f} {r['q_pos_ratio']*100:7.0f}% {r['n_industries']:6d}"
        )
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        pl.DataFrame(out_rows).write_csv(args.output)
        print(f"\n已写出: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
