"""中观行业景气 × 海关出口 领先-滞后相关（L2 行业口径，2026-10 重研究）。

取代旧脚本 ``export_finance_lead_lag.py``（依赖已删除的 company_exposure_map.csv /
customs_company_exposure.parquet 旧链，已失效）。新口径：

- 出口：``customs_l2_volume_price_monthly.parquet``（粒度=L2），行业级
  value/volume/price 3MMA yoy 三条序列（2016-01 起，GACC 黄金表派生）；
- 财报：``sw_2021_l2_fs_non_financial``（lixinger，2020-03 起），行业 TTM 营收/净利
  yoy（官方 ttm_y2y 优先、ttm_y2y_derived 兜底），季度锚定 standardDate 季末月；
- 桥接：``sw_2021_industry_dimension_golden``（industry_code ↔ index_code 唯一源）。

回答：出口 yoy（金额/量/价）与财报 yoy（营收/净利）是同步还是领先、领先几个月、
横截面方向一致率如何。口径纪律沿用 27 号文档：逐行业单独算 Pearson 后横截面取中位，
避免 pooled 宏观 beta 伪相关。
"""

from __future__ import annotations

import argparse
import statistics
from pathlib import Path

import polars as pl

from stock_data.catalog import DataCatalog
from stock_data.catalog.sw_industry_golden import load_sw_2021_industry_dimension
from stock_data.core.runtime import DataRuntimeContext

DEFAULT_ROOT = Path("data")
DEFAULT_EXPORT = Path("data/analytics/industry/customs_l2_volume_price_monthly.parquet")
DEFAULT_OUTPUT = Path("data/analytics/industry/export_l2_finance_lead_lag.csv")

K_MIN = -12
K_MAX = 12
MIN_POINTS = 12  # 每行业至少 12 个季度对齐点（27 号同口径）


def _ym(value: object) -> int:
    """'YYYY-MM' 或日期 -> year*12+month 整数月序。"""
    if value is None:
        raise ValueError("null month")
    if isinstance(value, str):
        y, m = value.split("-")[:2]
        return int(y) * 12 + int(m)
    return value.year * 12 + value.month


def load_dim(storage_dir: Path) -> pl.DataFrame:
    runtime = DataRuntimeContext.from_root(storage_dir)
    cat = DataCatalog(data_source="derived", runtime=runtime)
    return load_sw_2021_industry_dimension(
        cat, level="L2", columns=("industry_code", "industry_name", "index_code")
    ).select(["industry_code", "industry_name", "index_code"])


def load_export(path: Path) -> pl.DataFrame:
    df = pl.read_parquet(path)
    l2 = df.filter(pl.col("粒度") == "L2").select(
        ["code", "name", "report_month", "value_yoy_3mma", "volume_yoy_3mma", "price_yoy_3mma"]
    )
    return l2.with_columns(
        pl.col("report_month").map_elements(_ym, return_dtype=pl.Int64).alias("ym")
    )


def load_financial(storage_dir: Path) -> pl.DataFrame:
    runtime = DataRuntimeContext.from_root(storage_dir)
    cat = DataCatalog(data_source="lixinger", runtime=runtime)
    fs = cat.load_dataset("sw_2021_l2_fs_non_financial")
    toi = pl.col("q").struct.field("ps").struct.field("toi")
    np_ = pl.col("q").struct.field("ps").struct.field("np")
    out = fs.with_columns(
        pl.coalesce([toi.struct.field("ttm_y2y"), toi.struct.field("ttm_y2y_derived")]).alias(
            "revenue_y2y"
        ),
        pl.coalesce([np_.struct.field("ttm_y2y"), np_.struct.field("ttm_y2y_derived")]).alias(
            "profit_y2y"
        ),
    ).select(["symbol", "standardDate", "revenue_y2y", "profit_y2y"])
    # parquet 存在整表 2 倍重复行（值完全相同），去重后口径更干净；
    # 不去重也不影响相关性（last-wins 覆盖同一数值），此处显式化。
    out = out.unique(subset=["symbol", "standardDate", "revenue_y2y", "profit_y2y"])
    return out.with_columns(
        pl.col("standardDate").map_elements(_ym, return_dtype=pl.Int64).alias("ym")
    )


def _series(
    df: pl.DataFrame, key_col: str, month_col: str, val_col: str
) -> dict[str, dict[int, float]]:
    out: dict[str, dict[int, float]] = {}
    for r in df.select([key_col, month_col, val_col]).iter_rows(named=True):
        k = str(r[key_col]).strip()
        v = r[val_col]
        if v is None:
            continue
        out.setdefault(k, {})[r[month_col]] = float(v)
    return out


def lead_lag_matrix(
    export: dict[str, dict[int, float]],
    fin: dict[str, dict[int, float]],
    k_min: int,
    k_max: int,
    min_points: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for k in range(k_min, k_max + 1):
        corrs: list[float] = []
        for idx, fi in fin.items():
            ex = export.get(idx, {})
            pairs = [
                (ex[fm + k], fy)
                for fm, fy in fi.items()
                if (fm + k) in ex and ex[fm + k] is not None and fy is not None
            ]
            pairs = [(x, y) for x, y in pairs if x == x and y == y]  # 丢 NaN
            if len(pairs) >= min_points:
                corrs.append(statistics.correlation([p[0] for p in pairs], [p[1] for p in pairs]))
        if corrs:
            rows.append(
                {
                    "k": k,
                    "n_industries": len(corrs),
                    "corr_median": round(statistics.median(corrs), 4),
                    "corr_mean": round(statistics.mean(corrs), 4),
                    "share_positive": round(sum(1 for c in corrs if c > 0) / len(corrs), 3),
                }
            )
    return rows


def cross_section(
    export: dict[str, dict[int, float]],
    fin_rev: dict[str, dict[int, float]],
    fin_prof: dict[str, dict[int, float]],
) -> dict[str, object]:
    """最新财报季度（各行业最新季末月）出口 vs 财报横截面相关。"""
    out: dict[str, object] = {}
    for label, fin in (("revenue", fin_rev), ("profit", fin_prof)):
        pairs: list[tuple[float, float]] = []
        for idx, fi in fin.items():
            if not fi:
                continue
            ym = max(fi)
            ex = export.get(idx, {})
            if ym in ex and ex[ym] is not None and fi[ym] is not None:
                pairs.append((ex[ym], fi[ym]))
        if len(pairs) >= 8:
            xs = [p[0] for p in pairs]
            ys = [p[1] for p in pairs]
            out[f"xs_pearson_{label}"] = round(statistics.correlation(xs, ys), 3)
            out[f"xs_spearman_{label}"] = round(_spearman(xs, ys), 3)
        out[f"xs_n_{label}"] = len(pairs)
    return out


def _spearman(xs: list[float], ys: list[float]) -> float:
    def ranks(vals: list[float]) -> list[float]:
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        r = [0.0] * len(vals)
        for pos, i in enumerate(order):
            r[i] = float(pos + 1)
        return r

    return statistics.correlation(ranks(xs), ranks(ys))


def direction_consistency(
    export: dict[str, dict[int, float]], fin: dict[str, dict[int, float]]
) -> dict[str, object]:
    agree_rev = agree_prof = total_rev = total_prof = 0
    for idx, fi in fin.items():
        ex = export.get(idx, {})
        for ym, fy in fi.items():
            if ym in ex and ex[ym] is not None and fy is not None:
                total_rev += 1
                if (ex[ym] > 0) == (fy > 0):
                    agree_rev += 1
    return {
        "share_sign_agree_revenue": round(agree_rev / total_rev, 3) if total_rev else None,
        "n_points_revenue": total_rev,
    }


def turn_point_lead(
    export: dict[str, dict[int, float]], fin: dict[str, dict[int, float]]
) -> dict[str, object]:
    """出口金额 yoy 首次转正月 领先 财报营收 TTM yoy 首次转正季（月）。"""
    leads: list[int] = []
    for idx, fi in fin.items():
        ex = export.get(idx, {})
        if not ex or not fi:
            continue
        # 对齐起始窗口：出口首转正只在财报可观测窗口内找，避免出口序列
        # 起始更早导致“领先 −39 个月”类窗口伪影。
        win_start = min(fi)
        ex_in_window = {m: v for m, v in ex.items() if m >= win_start}
        if not ex_in_window:
            continue
        ex_sorted = sorted(ex_in_window)
        ex_turn = next(
            (
                m
                for i, m in enumerate(ex_sorted)
                if i > 0 and ex_in_window[m] > 0 and ex_in_window[ex_sorted[i - 1]] <= 0
            ),
            None,
        )
        fi_sorted = sorted(fi)
        fi_turn = next(
            (
                m
                for i, m in enumerate(fi_sorted)
                if i > 0 and fi[m] > 0 and fi[fi_sorted[i - 1]] <= 0
            ),
            None,
        )
        if ex_turn is not None and fi_turn is not None:
            leads.append(ex_turn - fi_turn)
    if leads:
        return {
            "n_industries": len(leads),
            "lead_months_median": round(statistics.median(leads), 1),
            "lead_months_mean": round(statistics.mean(leads), 1),
            "share_export_first": round(sum(1 for x in leads if x < 0) / len(leads), 3),
        }
    return {"n_industries": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-dir", default=str(DEFAULT_ROOT))
    parser.add_argument("--export-path", default=str(DEFAULT_EXPORT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--k-min", type=int, default=K_MIN)
    parser.add_argument("--k-max", type=int, default=K_MAX)
    parser.add_argument("--min-points", type=int, default=MIN_POINTS)
    args = parser.parse_args()

    storage = Path(args.storage_dir)
    dim = load_dim(storage)
    exp_raw = load_export(Path(args.export_path)).rename({"code": "index_code"})
    exp = exp_raw.join(dim, on="index_code", how="inner")
    fin_raw = load_financial(storage).rename({"symbol": "industry_code"})
    fin = fin_raw.join(dim, on="industry_code", how="inner")

    ex_v = _series(exp, "index_code", "ym", "value_yoy_3mma")
    ex_q = _series(exp, "index_code", "ym", "volume_yoy_3mma")
    ex_p = _series(exp, "index_code", "ym", "price_yoy_3mma")
    fi_rev = _series(fin, "index_code", "ym", "revenue_y2y")
    fi_prof = _series(fin, "index_code", "ym", "profit_y2y")

    print("行业数（出口×财报可对齐）:", len(set(ex_v) & set(fi_rev)))
    for label, ex_series, fi_series in (
        ("value_vs_revenue", ex_v, fi_rev),
        ("value_vs_profit", ex_v, fi_prof),
        ("volume_vs_revenue", ex_q, fi_rev),
        ("price_vs_profit", ex_p, fi_prof),
    ):
        mat = lead_lag_matrix(ex_series, fi_series, args.k_min, args.k_max, args.min_points)
        print(f"\n=== {label} ===")
        for row in mat:
            if row["k"] in (-12, -9, -6, -3, 0, 3, 6, 9, 12):
                print(row)

    print("\n=== 横截面（最新财报季） ===")
    print(cross_section(ex_v, fi_rev, fi_prof))
    print("\n=== 方向一致率（k=0 符号一致） ===")
    print(direction_consistency(ex_v, fi_rev))
    print("\n=== 拐点领先（出口金额转正 vs 营收转正） ===")
    print(turn_point_lead(ex_v, fi_rev))

    # 落盘 k=0 附近矩阵供文档引用
    rows: list[dict[str, object]] = []
    for k in range(args.k_min, args.k_max + 1):
        for label, ex_series, fi_series in (
            ("value_vs_revenue", ex_v, fi_rev),
            ("value_vs_profit", ex_v, fi_prof),
            ("volume_vs_revenue", ex_q, fi_rev),
            ("price_vs_profit", ex_p, fi_prof),
        ):
            mat = lead_lag_matrix(ex_series, fi_series, k, k, args.min_points)
            if mat:
                r = dict(mat[0])
                r["series"] = label
                rows.append(r)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_csv(out)
    print(f"\nwritten: {out}")


if __name__ == "__main__":
    main()
