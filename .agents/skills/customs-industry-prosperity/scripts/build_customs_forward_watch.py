#!/usr/bin/env python3
"""申万 L2/L3 × 海关出口 前瞻观察表生成器（METHODOLOGY_FINAL 定稿口径）。

合并来源（全部本地黄金表）：
  - 金额面板: data/analytics/industry/customs_export_prosperity_panel.parquet
  - 量价面板: data/analytics/industry/customs_l2_volume_price_monthly.parquet
  - 财报:     sw_2021_l2_fs_* / sw_2021_l3_fs_*（营收/净利 TTM yoy，后视验证列）
  - 维度表:   sw_2021_industry_dimension_golden（index_code ↔ industry_code 桥接唯一源）

输出：
  - L2 观察表: data/analytics/industry/customs_forward_watch_l2.parquet
  - L3 观察表: data/analytics/industry/customs_forward_watch_l3.parquet

列：industry_code / industry_name / idx_code / 金额yoy / 量yoy / 价yoy / 驱动类型 /
    分位36m（当前 yoy 在近 36 个频点内 ≤ 当前值比例）/ 财报营收yoy / 财报净利yoy /
    一致率分级（仅 L2，02 文档）/ n_hs8

用法:
    uv run python scripts/build_customs_forward_watch.py
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import polars as pl

from stock_data.catalog import DataCatalog
from stock_data.catalog.sw_industry_golden import load_sw_2021_industry_dimension
from stock_data.core.runtime import DataRuntimeContext

DEFAULT_OUTPUT_DIR = Path("data/analytics/industry")
# 一致率分级（02_effectiveness_matrix.md 2026-09-14 口径，仅 L2）
CONSISTENCY = {
    "801738.SI": (1.00, "A"), "801963.SI": (1.00, "A"), "801735.SI": (0.92, "A"),
    "801952.SI": (0.92, "A"), "801737.SI": (0.92, "A"), "801081.SI": (0.85, "A"),
    "801095.SI": (0.77, "B"), "801153.SI": (0.77, "B"), "801101.SI": (0.77, "B"),
    "801951.SI": (0.77, "B"), "801112.SI": (0.77, "B"), "801881.SI": (0.77, "B"),
    "801093.SI": (0.73, "B"), "801072.SI": (0.73, "B"), "801044.SI": (0.69, "B"),
    "801038.SI": (0.69, "B"), "801151.SI": (0.69, "B"), "801744.SI": (0.69, "B"),
    "801053.SI": (0.65, "B"), "801713.SI": (0.65, "B"), "801733.SI": (0.65, "B"),
    "801155.SI": (0.65, "B"), "801111.SI": (0.65, "B"), "801083.SI": (0.62, "B"),
    "801132.SI": (0.62, "B"), "801033.SI": (0.62, "B"), "801096.SI": (0.62, "B"),
    "801032.SI": (0.62, "B"), "801131.SI": (0.58, "C"), "801015.SI": (0.58, "C"),
    "801712.SI": (0.54, "C"), "801113.SI": (0.54, "C"), "801077.SI": (0.46, "C"),
    "801055.SI": (0.46, "C"), "801085.SI": (0.42, "C"), "801102.SI": (0.42, "C"),
    "801142.SI": (0.35, "C"), "801736.SI": (0.31, "C"), "801045.SI": (0.23, "C"),
    "801114.SI": (0.38, "C"),  # 厨卫电器（02 文档全表口径；catalog 无产品映射 → 观察表不出现该行）
}


def _load_dim() -> tuple[pl.DataFrame, pl.DataFrame]:
    runtime = DataRuntimeContext.from_root("data")
    cat = DataCatalog(data_source="derived", runtime=runtime)
    l2 = load_sw_2021_industry_dimension(
        cat, level="L2", columns=("industry_code", "industry_name", "index_code")
    ).rename({"index_code": "idx_code", "industry_code": "industry_code"})
    l3 = load_sw_2021_industry_dimension(
        cat, level="L3", columns=("industry_code", "industry_name", "index_code", "parent_code")
    ).rename({"index_code": "idx_code"})
    return l2, l3


def _load_financial(data_source: str, dataset: str) -> pl.DataFrame:
    """财报 TTM yoy：官方优先、派生兜底（data-catalog §1.3 口径）。

    end_date 动态取当前日期（P5-1 修复：原硬编码 2026-12-31 会在 2027 年
    后漏掉最新财报期，导致观察表财报列过期）。
    """
    runtime = DataRuntimeContext.from_root("data")
    cat = DataCatalog(data_source=data_source, runtime=runtime)
    fs = cat.load_dataset(dataset, start_date=date(2020, 1, 1), end_date=date.today())
    toi = pl.col("q").struct.field("ps").struct.field("toi")
    np_ = pl.col("q").struct.field("ps").struct.field("np")
    fs2 = fs.with_columns(
        pl.coalesce([toi.struct.field("ttm_y2y"), toi.struct.field("ttm_y2y_derived")]).alias("revenue_y2y"),
        pl.coalesce([np_.struct.field("ttm_y2y"), np_.struct.field("ttm_y2y_derived")]).alias("profit_y2y"),
    ).select(["symbol", "reportDate", "revenue_y2y", "profit_y2y"])
    latest = fs2.sort("reportDate").group_by("symbol").agg(pl.col("reportDate").max().alias("reportDate"))
    return fs2.join(latest, on=["symbol", "reportDate"], how="inner").rename({"symbol": "industry_code"})


def _emp_pct_36m(grp: pl.DataFrame) -> pl.DataFrame:
    """Framework §1 口径：当前 yoy 在近 36 个频点内 ≤ 当前值的比例 × 100。"""
    ys = grp.sort("report_month")
    vals = ys["yoy_growth_3mma"].to_list()
    out = []
    for i in range(len(vals)):
        lo = max(0, i - 35)
        win = [v for v in vals[lo : i + 1] if v is not None]
        cur = vals[i]
        out.append(None if (cur is None or len(win) < 12) else round(sum(1 for v in win if v <= cur) / len(win) * 100, 1))
    return ys.with_columns(pl.Series("yoy_pct_36m", out))


def build_level(level: str, output_dir: Path) -> None:
    dim_l2, dim_l3 = _load_dim()
    dim = dim_l2 if level == "L2" else dim_l3

    # 1. 金额面板（含全历史 → 36 月分位）
    c = pl.read_parquet(output_dir / "customs_export_prosperity_panel.parquet")
    l2_all = c.filter(pl.col("granularity") == level.lower()).rename({"code": "idx_code"})
    m_all = l2_all.join(dim, on="idx_code", how="left").filter(pl.col("industry_code").is_not_null())
    if level == "L2":
        m_all = m_all.filter(pl.col("idx_code").str.contains(";").not_())  # 组合码跳过
    m_all = pl.concat([_emp_pct_36m(g) for _, g in m_all.group_by("industry_code")])
    cur = m_all.filter(pl.col("report_month") == m_all["report_month"].max())

    # 2. 量价分解
    vp = pl.read_parquet(output_dir / "customs_l2_volume_price_monthly.parquet")
    vp_lv = vp.filter((pl.col("粒度") == level) & (pl.col("report_month") == cur["report_month"].max()))
    cur = cur.join(
        vp_lv.select(["code", "volume_yoy_3mma", "price_yoy_3mma", "驱动类型"]).rename({"code": "idx_code"}),
        on="idx_code", how="left",
    )

    # 3. 财报（后视验证列）
    if level == "L2":
        fin = pl.concat([
            _load_financial("lixinger", "sw_2021_l2_fs_non_financial"),
            _load_financial("lixinger", "sw_2021_l2_fs_bank"),
            _load_financial("lixinger", "sw_2021_l2_fs_security"),
            _load_financial("lixinger", "sw_2021_l2_fs_insurance"),
        ])
    else:
        fin = _load_financial("lixinger", "sw_2021_l3_fs_non_financial")
    cur = cur.join(fin, on="industry_code", how="left")

    # 4. 一致率分级（仅 L2）
    if level == "L2":
        cons = pl.DataFrame(
            [{"idx_code": k, "consistency": v[0], "grade": v[1]} for k, v in CONSISTENCY.items()]
        )
        cur = cur.join(cons, on="idx_code", how="left")

    out_cols = [
        "industry_code", "industry_name", "idx_code", "report_month",
        "yoy_growth_3mma", "volume_yoy_3mma", "price_yoy_3mma", "驱动类型",
        "yoy_pct_36m", "revenue_y2y", "profit_y2y", "n_hs8",
    ]
    if level == "L2":
        out_cols += ["grade", "consistency"]
    out = cur.select(out_cols).sort("yoy_growth_3mma", descending=True)
    dst = output_dir / f"customs_forward_watch_{level.lower()}.parquet"
    out.write_parquet(dst)
    print(f"[{level}] 观察表 {out.height} 行 → {dst}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="生成申万 L2/L3 × 海关出口 前瞻观察表")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    parser.add_argument("--level", choices=["L2", "L3", "both"], default="both")
    args = parser.parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    levels = ["L2", "L3"] if args.level == "both" else [args.level]
    for lv in levels:
        df = build_level(lv, out_dir)
        latest = df.head(5)
        print(latest.select(["industry_code", "industry_name", "yoy_growth_3mma", "volume_yoy_3mma", "price_yoy_3mma", "驱动类型"]).to_pandas().round(3).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
