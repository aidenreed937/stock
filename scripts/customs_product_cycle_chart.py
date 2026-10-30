#!/usr/bin/env python3
"""商品段景气周期全景图（金额/量/价 yoy + 驱动 + 拐点 + 二阶导）。

读取 ``data/analytics/industry/customs_product_volume_price.parquet``，绘制：
- 第 1 面板：全部商品段金额 yoy 3MMA 的月度中位数（p25-p75 带），看整体循环；
- 其余面板：每个代表商品段的 金额/量/价 yoy + 四象限驱动底色 + 启动/见顶拐点
  + 量增速回落标记，标题附该段启动/见顶拐点次数。

产出:
- PNG: ``data/analytics/industry/customs_product_cycle_panorama.png``；
- 终端：代表段拐点统计 + 全体段循环强度统计。

用法:
    MPLCONFIGDIR="$PWD/.mplcache" uv run python scripts/customs_product_cycle_chart.py
    MPLCONFIGDIR="$PWD/.mplcache" uv run python scripts/customs_product_cycle_chart.py \
        --seg-keys transformer::units,battery::units
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import polars as pl

PANEL = Path("data/analytics/industry/customs_product_volume_price.parquet")
RANK_CSV = Path("data/analytics/industry/customs_product_pct_rank_latest.csv")
OUT_PNG = Path("data/analytics/industry/customs_product_cycle_panorama.png")

DEFAULT_SEGS = (
    "transformer::units",
    "battery::units",
    "semiconductor_ic::units",
    "tio2::kg",
    "polysilicon::kg",
    "methanol::kg",
)

DRV_COLORS = {
    "量价齐升": "#e74c3c",
    "量驱动": "#e67e22",
    "价驱动": "#9b59b6",
    "双弱": "#7f8c8d",
}


def _month_start(ym: str) -> date:
    y, m = int(ym[:4]), int(ym[5:7])
    return date(y, m, 1)


def _setup_font() -> None:
    from matplotlib import font_manager

    for f in ("/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Medium.ttc"):
        if Path(f).exists():
            font_manager.fontManager.addfont(f)
            break
    plt.rcParams["font.family"] = "PingFang SC"
    plt.rcParams["axes.unicode_minus"] = False


def _draw_panel(ax: plt.Axes, d: pl.DataFrame, seg_key: str, title: str) -> None:
    x = [_month_start(r) for r in d["report_month"].to_list()]
    money = (d["value_yoy_3mma"] * 100).fill_nan(None).to_list()
    vol = (d["volume_yoy_3mma"] * 100).fill_nan(None).to_list()
    price = (d["price_yoy_3mma"] * 100).fill_nan(None).to_list()

    # 驱动底色（axvspan 按月）
    for i in range(len(x) - 1):
        color = DRV_COLORS.get(d["驱动类型"][i])
        if color:
            ax.axvspan(x[i], x[i + 1], color=color, alpha=0.13, lw=0)

    ax.plot(x, money, label="金额 yoy", color="#c0392b", lw=1.6)
    ax.plot(x, vol, label="量 yoy", color="#2980b9", lw=1.2)
    ax.plot(x, price, label="价 yoy", color="#27ae60", lw=1.2)
    ax.axhline(0, color="gray", lw=0.8)

    for r in d.filter(pl.col("拐点") == "启动拐点").iter_rows(named=True):
        ax.plot(
            _month_start(r["report_month"]), r["value_yoy_3mma"] * 100, "^", color="#27ae60", ms=9
        )
    for r in d.filter(pl.col("拐点") == "见顶拐点").iter_rows(named=True):
        ax.plot(
            _month_start(r["report_month"]), r["value_yoy_3mma"] * 100, "v", color="#c0392b", ms=9
        )
    sec = d.filter(pl.col("二阶导") == "量增速回落")
    ax.plot(
        [_month_start(r) for r in sec["report_month"].to_list()],
        (sec["volume_yoy_3mma"] * 100).fill_nan(None).to_list(),
        "x",
        color="#f39c12",
        ms=7,
        label="量增速回落",
    )

    starts = d.filter(pl.col("拐点") == "启动拐点").height
    peaks = d.filter(pl.col("拐点") == "见顶拐点").height
    ax.set_title(f"{title}\n{seg_key} · 启动{starts}次 / 见顶{peaks}次", fontsize=11)
    ax.set_ylabel("3MMA yoy (%)")
    ax.tick_params(axis="x", rotation=90, labelsize=8)
    ax.grid(alpha=0.25)


def _overview_panel(ax: plt.Axes, p: pl.DataFrame) -> None:
    med = (
        p.with_columns(pl.col("value_yoy_3mma").fill_nan(None))
        .group_by("report_month")
        .agg(
            pl.col("value_yoy_3mma").median().alias("med"),
            pl.col("value_yoy_3mma").quantile(0.25).alias("p25"),
            pl.col("value_yoy_3mma").quantile(0.75).alias("p75"),
        )
        .sort("report_month")
    )
    x = [_month_start(r) for r in med["report_month"].to_list()]
    med_y = (med["med"].fill_null(float("nan")) * 100).to_list()
    p25_y = (med["p25"].fill_null(float("nan")) * 100).to_list()
    p75_y = (med["p75"].fill_null(float("nan")) * 100).to_list()
    ax.plot(x, med_y, color="#2c3e50", lw=2, label="中位数 金额yoy")
    ax.fill_between(x, p25_y, p75_y, color="#95a5a6", alpha=0.35, label="p25–p75")
    ax.axhline(0, color="gray", lw=0.8)
    ax.set_title(f"全部 {p['seg_key'].n_unique()} 段金额 yoy 月度中位数（p25–p75）", fontsize=12)
    ax.set_ylabel("3MMA yoy (%)")
    ax.tick_params(axis="x", rotation=90, labelsize=8)
    ax.grid(alpha=0.25)
    ax.legend(loc="upper left", fontsize=9)


def cycle_stats(p: pl.DataFrame) -> pl.DataFrame:
    """全体商品段拐点循环强度统计。"""
    stats = p.group_by("seg_key").agg(
        pl.len().alias("n_months"),
        (pl.col("拐点") == "启动拐点").sum().alias("n_start"),
        (pl.col("拐点") == "见顶拐点").sum().alias("n_peak"),
    )
    return stats.with_columns(
        pl.col("n_start").median().alias("med_start"),
        pl.col("n_peak").median().alias("med_peak"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seg-keys", default=",".join(DEFAULT_SEGS), help="商品段列表，逗号分隔")
    parser.add_argument("--output", type=Path, default=OUT_PNG, help="输出 PNG 路径")
    args = parser.parse_args()

    if not PANEL.exists():
        raise SystemExit(f"缺少商品面板: {PANEL}")
    p = pl.read_parquet(PANEL)
    segs = [s.strip() for s in args.seg_keys.split(",") if s.strip()]
    data = {s: p.filter(pl.col("seg_key") == s).sort("report_month") for s in segs}
    missing = [s for s, d in data.items() if d.height == 0]
    if missing:
        raise SystemExit(f"商品段不存在: {missing}")

    _setup_font()
    fig, axes = plt.subplots(4, 2, figsize=(18, 22))
    _overview_panel(axes[0][0], p)
    axes[0][1].axis("off")
    for ax, seg in zip(axes.flatten()[2:], segs):
        d = data[seg]
        name = d["product_name"][0] if d.height else seg
        _draw_panel(ax, d, seg, name)
    for ax in axes.flatten()[2 + len(segs) :]:
        ax.axis("off")

    # 统一图例
    handles, labels = [], []
    for ax in [axes[0][0]] + [axes[i // 2][i % 2] for i in range(2, 2 + len(segs))]:
        h, lbl = ax.get_legend_handles_labels()
        handles += h
        labels += lbl
    seen, hh, ll = set(), [], []
    for h, lbl in zip(handles, labels):
        if lbl not in seen:
            seen.add(lbl)
            hh.append(h)
            ll.append(lbl)
    driver_handles = [plt.Rectangle((0, 0), 1, 1, color=c, alpha=0.4) for c in DRV_COLORS.values()]
    fig.legend(
        hh + driver_handles,
        ll + [f"驱动:{k}" for k in DRV_COLORS],
        loc="upper center",
        ncol=7,
        fontsize=9,
        frameon=False,
    )

    fig.tight_layout(rect=(0, 0, 1, 0.97))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=110)
    plt.close(fig)
    print(f"PNG: {args.output}")

    # 全体循环强度
    st = cycle_stats(p)
    print(
        f"全体 {st.height} 段：启动拐点 中位 {st['med_start'][0]:.0f} 次、"
        f"见顶拐点 中位 {st['med_peak'][0]:.0f} 次；"
        f"≥2 次启动 {st.filter(pl.col('n_start') >= 2).height} 段、"
        f"≥2 次见顶 {st.filter(pl.col('n_peak') >= 2).height} 段"
    )
    print("\n代表段：")
    ranks = None
    if RANK_CSV.exists():
        ranks = pl.read_csv(RANK_CSV)
    for seg in segs:
        d = data[seg]
        n_s = d.filter(pl.col("拐点") == "启动拐点").height
        n_p = d.filter(pl.col("拐点") == "见顶拐点").height
        stage = ""
        if ranks is not None:
            row = ranks.filter(pl.col("seg_key") == seg)
            if row.height:
                stage = f" | 当前: {row['景气阶段'][0]} (自身36m分位 {row['pct_self_36m'][0]})"
        print(f"  {seg}: 启动{n_s}/见顶{n_p} 次{stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
