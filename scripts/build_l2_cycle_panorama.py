#!/usr/bin/env python3
"""二级行业景气周期全景 + 历史交易规则回放（电网设备 801738.SI 示例）。

数据（GACC 段，2018-01~2026-07）：
- 出口：``customs_l2_volume_price_monthly.parquet``（金额/量/价 3MMA yoy、驱动类型）；
- 财报：``sw_2021_l2_fs_*``（营收/净利 TTM yoy，按报告日 asof 无前视对齐）；
- 拐点/二阶导：与 ``product_panel.py`` 同口径（金额符号翻转 / 量增速见顶回落）。

产出：
- CSV：``data/analytics/industry/customs_l2_panorama_801738.csv``（月度全景表）；
- PNG：``data/analytics/industry/customs_l2_panorama_801738.png``（周期图，中文标签）；
- MD：``docs/research/customs_export_forward/43_grid_equipment_cycle_panorama_2026_10.md``。

用法（仓库根目录）：
    MPLCONFIGDIR="$PWD/.mplcache" uv run python scripts/build_l2_cycle_panorama.py
"""

from __future__ import annotations

import argparse
import calendar
import math
from datetime import date
from pathlib import Path

import polars as pl

from stock_data.catalog import DataCatalog
from stock_data.core.runtime import DataRuntimeContext

PANEL = Path("data/analytics/industry/customs_l2_volume_price_monthly.parquet")
OUT_CSV = Path("data/analytics/industry/customs_l2_panorama_801738.csv")
OUT_PNG = Path("data/analytics/industry/customs_l2_panorama_801738.png")
OUT_MD = Path("docs/research/customs_export_forward/43_grid_equipment_cycle_panorama_2026_10.md")

CODE = "801738.SI"
NAME = "电网设备"
FIN_DATASETS = (
    "sw_2021_l2_fs_non_financial",
    "sw_2021_l2_fs_bank",
    "sw_2021_l2_fs_security",
    "sw_2021_l2_fs_insurance",
)


def month_end(ym: str) -> date:
    y, m = int(ym[:4]), int(ym[5:7])
    return date(y, m, calendar.monthrange(y, m)[1])


def load_financial(storage_dir: Path) -> pl.DataFrame:
    """全历史 L2 财报 TTM yoy（官方优先、派生兜底，去重）。"""
    runtime = DataRuntimeContext.from_root(storage_dir)
    cat = DataCatalog(data_source="lixinger", runtime=runtime)
    frames = []
    for ds in FIN_DATASETS:
        f = cat.load_dataset(ds)
        toi = pl.col("q").struct.field("ps").struct.field("toi")
        np_ = pl.col("q").struct.field("ps").struct.field("np")
        out = f.with_columns(
            pl.coalesce([toi.struct.field("ttm_y2y"), toi.struct.field("ttm_y2y_derived")]).alias(
                "revenue_y2y"
            ),
            pl.coalesce([np_.struct.field("ttm_y2y"), np_.struct.field("ttm_y2y_derived")]).alias(
                "profit_y2y"
            ),
        ).select(["symbol", "reportDate", "revenue_y2y", "profit_y2y"])
        frames.append(out)
    return pl.concat(frames).unique(subset=["symbol", "reportDate", "revenue_y2y", "profit_y2y"])


def build_monthly(code: str, storage_dir: Path | str = "data") -> pl.DataFrame:
    v = (
        pl.read_parquet(PANEL)
        .filter((pl.col("粒度") == "L2") & (pl.col("code") == code))
        .sort("report_month")
        .with_columns(
            pl.col("value_yoy_3mma").shift(1).alias("prev_val"),
            pl.col("volume_yoy_3mma").rolling_max(4, min_samples=2).shift(1).alias("qmax4"),
            pl.col("volume_yoy_3mma").rolling_max(6, min_samples=3).alias("qmax6"),
            pl.col("report_month").map_elements(month_end, return_dtype=pl.Date).alias("month_end"),
        )
    )
    v = v.with_columns(
        pl.when(
            pl.col("prev_val").is_not_null()
            & (~pl.col("prev_val").is_nan())
            & (pl.col("prev_val") < 0)
            & pl.col("value_yoy_3mma").is_not_null()
            & (~pl.col("value_yoy_3mma").is_nan())
            & (pl.col("value_yoy_3mma") >= 0)
        )
        .then(pl.lit("启动拐点"))
        .when(
            pl.col("prev_val").is_not_null()
            & (~pl.col("prev_val").is_nan())
            & (pl.col("prev_val") > 0)
            & pl.col("value_yoy_3mma").is_not_null()
            & (~pl.col("value_yoy_3mma").is_nan())
            & (pl.col("value_yoy_3mma") <= 0)
        )
        .then(pl.lit("见顶拐点"))
        .otherwise(None)
        .alias("拐点"),
        pl.when(
            pl.col("volume_yoy_3mma").is_not_null()
            & (~pl.col("volume_yoy_3mma").is_nan())
            & (pl.col("volume_yoy_3mma") >= 0)
            & (pl.col("volume_yoy_3mma") < pl.col("qmax4"))
            & (pl.col("qmax6") > 0.1)
        )
        .then(pl.lit("量增速回落"))
        .otherwise(None)
        .alias("二阶导"),
    )

    from stock_analytics.pipelines.customs_prosperity.forward_watch import load_dim

    l2, _ = load_dim(Path(storage_dir))
    ic = l2.filter(pl.col("idx_code") == code)["industry_code"].first()
    fin = (
        load_financial(Path(storage_dir))
        .filter(pl.col("symbol") == ic)
        .sort("reportDate")
        .select(["reportDate", "revenue_y2y", "profit_y2y"])
    )
    v = v.sort("month_end").join_asof(
        fin, left_on="month_end", right_on="reportDate", strategy="backward"
    )
    v = v.with_columns(
        pl.when(
            (pl.col("value_yoy_3mma") > 0)
            & pl.col("revenue_y2y").is_not_null()
            & (pl.col("revenue_y2y") < 0)
        )
        .then(pl.lit("前瞻窗口"))
        .otherwise(None)
        .alias("前瞻窗口"),
    )
    return v.sort("report_month")


def replay_trading(df: pl.DataFrame) -> pl.DataFrame:
    """纯金额择时规则回放（skill 第三层纪律的行业层演示版）。"""
    d = df.with_columns(pl.col("value_yoy_3mma").shift(1).alias("prev_yoy")).sort("report_month")
    state = "空仓"
    pos = 0
    pos_months = 0
    down2 = 0
    up2 = 0
    out = []
    for r in d.to_dicts():
        y = r["value_yoy_3mma"]
        finite = y is not None and not math.isnan(y)
        prev = r["prev_yoy"]
        action = ""
        if finite:
            pos_months = pos_months + 1 if y > 0 else 0
            if prev is not None and not math.isnan(prev):
                down2 = down2 + 1 if y < prev else 0
                up2 = up2 + 1 if y > prev else 0
            else:
                down2 = up2 = 0
            if state == "空仓":
                if pos_months >= 2:
                    state = "建仓中"
                    pos = 1
                    action = "分批建仓 1/3"
            elif state == "建仓中":
                if y <= 0:
                    state, pos, action = "空仓", 0, "清仓（金额≤0）"
                else:
                    pos += 1
                    if pos < 3:
                        action = f"分批建仓 {pos}/3"
                    else:
                        state, pos, action = "满仓", 4, "分批建仓 3/3（满仓）"
            if state in ("满仓", "减半"):
                if state == "满仓":
                    if y <= 0:
                        state, pos, action = "空仓", 0, "清仓（金额≤0）"
                    elif down2 >= 2:
                        state, pos, action = "减半", 2, "景气减仓 半仓"
                elif state == "减半":
                    if y <= 0:
                        state, pos, action = "空仓", 0, "清仓（金额≤0）"
                    elif up2 >= 2:
                        state, pos, action = "满仓", 4, "恢复满仓（金额回升）"
        out.append({**r, "state": state, "position": pos, "action": action})
    return pl.DataFrame(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code", default=CODE)
    parser.add_argument("--name", default=NAME)
    parser.add_argument("--out-csv", type=Path, default=OUT_CSV)
    parser.add_argument("--out-png", type=Path, default=OUT_PNG)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    args = parser.parse_args()

    df = replay_trading(build_monthly(args.code))

    cols = [
        "report_month",
        "value_yoy_3mma",
        "volume_yoy_3mma",
        "price_yoy_3mma",
        "驱动类型",
        "拐点",
        "二阶导",
        "revenue_y2y",
        "profit_y2y",
        "前瞻窗口",
        "state",
        "action",
    ]
    df.select(cols).write_csv(args.out_csv)

    try:
        _draw_png(df, args.out_png)
    except Exception as exc:  # noqa: BLE001
        print(f"PNG 生成失败（不影响 CSV/MD）: {exc}")

    md = build_md(df, args)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(md, encoding="utf-8")
    print(f"csv: {args.out_csv}")
    print(f"png: {args.out_png}")
    print(f"md:  {args.out_md}")


def _draw_png(df: pl.DataFrame, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    for f in ("/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Medium.ttc"):
        if Path(f).exists():
            font_manager.fontManager.addfont(f)
            break
    plt.rcParams["font.family"] = "PingFang SC"
    plt.rcParams["axes.unicode_minus"] = False

    d = df.sort("report_month")
    x = d["report_month"].to_list()
    fig, axes = plt.subplots(3, 1, figsize=(16, 12), sharex=True)
    ax = axes[0]
    ax.plot(x, d["value_yoy_3mma"].to_list(), label="金额 yoy", color="#c0392b", lw=1.6)
    ax.plot(x, d["volume_yoy_3mma"].to_list(), label="量 yoy", color="#2980b9", lw=1.2)
    ax.plot(x, d["price_yoy_3mma"].to_list(), label="价 yoy", color="#27ae60", lw=1.2)
    ax.axhline(0, color="gray", lw=0.8)
    ax.set_ylabel("3MMA yoy")
    ax.legend(loc="upper left", fontsize=9)
    ax.set_title(f"{NAME}（{CODE}）景气周期全景（GACC 段）", fontsize=14)

    ax2 = axes[1]
    drv_color = {"量价齐升": "#e74c3c", "量驱动": "#e67e22", "价驱动": "#9b59b6", "双弱": "#7f8c8d"}
    for r in d.iter_rows(named=True):
        c = drv_color.get(r["驱动类型"])
        if c:
            ax2.axvspan(r["report_month"], r["report_month"], color=c, alpha=0.15)
    ax2.plot(x, d["value_yoy_3mma"].to_list(), color="black", lw=1.0)
    for r in d.filter(pl.col("拐点") == "启动拐点").iter_rows(named=True):
        ax2.plot(r["report_month"], r["value_yoy_3mma"], "^", color="#27ae60", ms=10)
    for r in d.filter(pl.col("拐点") == "见顶拐点").iter_rows(named=True):
        ax2.plot(r["report_month"], r["value_yoy_3mma"], "v", color="#c0392b", ms=10)
    ax2.axhline(0, color="gray", lw=0.8)
    ax2.set_ylabel("驱动类型/拐点")

    ax3 = axes[2]
    ax3.plot(x, d["position"].to_list(), color="#2980b9", lw=1.5, drawstyle="steps-post")
    ax3.set_ylim(-0.2, 4.5)
    ax3.set_yticks([0, 1, 2, 3, 4])
    ax3.set_yticklabels(["空仓", "建仓1", "建仓2", "建仓3", "满仓"])
    for r in d.filter(pl.col("action") != "").iter_rows(named=True):
        ax3.annotate(
            r["action"],
            (r["report_month"], r["position"]),
            fontsize=7,
            rotation=90,
            textcoords="offset points",
            xytext=(3, 3),
        )
    ax3.set_ylabel("择时仓位")
    plt.xticks(x[::6], rotation=90, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def build_md(df: pl.DataFrame, args: argparse.Namespace) -> str:
    d = df.sort("report_month")
    actions = d.filter(pl.col("action") != "").select(
        [
            "report_month",
            "value_yoy_3mma",
            "volume_yoy_3mma",
            "price_yoy_3mma",
            "驱动类型",
            "action",
        ]
    )
    return f"""# {args.name}（{args.code}）景气周期全景与历史交易回放（GACC 段）

> 口径：出口金额/量/价 3MMA yoy（`customs_l2_volume_price_monthly.parquet`，{d["report_month"].min()}~{d["report_month"].max()}）；
> 拐点=金额符号翻转、二阶导=量增速见顶回落（与 product_panel 同口径）；
> 财报=营收/净利 TTM yoy（`sw_2021_l2_fs_*`，asof 无前视）；交易回放=纯金额择时纪律（skill 第三层规则的行业层演示）。
> 复现：`MPLCONFIGDIR="$PWD/.mplcache" uv run python scripts/build_l2_cycle_panorama.py`

## 1. 月度全景

| 月份 | 金额 yoy | 量 yoy | 价 yoy | 驱动 | 拐点 | 二阶导 | 财报营收 | 财报净利 | 前瞻窗口 | 仓位动作 |
| :-- | --: | --: | --: | :-- | :-- | :-- | --: | --: | :-- | :-- |
{_md_rows(d)}

## 2. 周期阶段（驱动分段概览）

| 驱动段 | 起止 | 月数 | 平均金额 yoy | 段内拐点 | 二阶导月数 | 段内动作 |
| :-- | :-- | --: | --: | :-- | --: | :-- |
{_md_segments(d)}

## 3. 历史交易规则回放（信号 → 动作）

| 时间 | 金额 yoy | 量/价 | 驱动 | 规则动作 |
| :-- | --: | :-- | :-- | :-- |
{_md_actions(actions)}

## 4. 限制

- 演示版用行业金额 yoy 执行第三层择时纪律；实战建仓/减仓应以**产品/公司段金额 yoy** 为准（skill 第三层口径）；
- 减半后「连续 2 个月回升恢复满仓」为演示假设，skill 未定义该再入规则；
- 未纳入资金腿/财报腿（三腿 AND），只回放金额单腿；
- 财报列为季度 TTM yoy，按报告日 asof 对齐，无前视；**财报列自 2022-10 起有值**（理杏仁 L2 fs 覆盖，官方与派生均无更早数据），此前为空。
"""


def _fmt(v: object, nd: int = 3) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return f"{v:.{nd}f}"


def _md_rows(d: pl.DataFrame) -> str:
    lines = []
    for r in d.iter_rows(named=True):
        lines.append(
            f"| {r['report_month']} | {_fmt(r['value_yoy_3mma'])} | {_fmt(r['volume_yoy_3mma'])} | "
            f"{_fmt(r['price_yoy_3mma'])} | {r['驱动类型'] or '—'} | {r['拐点'] or '—'} | "
            f"{r['二阶导'] or '—'} | {_fmt(r['revenue_y2y'], 2)} | {_fmt(r['profit_y2y'], 2)} | "
            f"{r['前瞻窗口'] or '—'} | {r['action'] or '—'} |"
        )
    return "\n".join(lines)


def _md_segments(d: pl.DataFrame) -> str:
    rows = d.sort("report_month").to_dicts()
    segs: list[dict] = []
    cur_drv = None
    cur_start = None
    cur_months: list[str] = []
    for r in rows:
        drv = r["驱动类型"]
        if drv != cur_drv:
            if cur_drv is not None:
                segs.append(
                    {
                        "drv": cur_drv,
                        "start": cur_start,
                        "end": cur_months[-1],
                        "months": cur_months,
                    }
                )
            cur_drv = drv
            cur_start = r["report_month"]
            cur_months = []
        if drv is not None:
            cur_months.append(r["report_month"])
    if cur_drv is not None:
        segs.append(
            {"drv": cur_drv, "start": cur_start, "end": cur_months[-1], "months": cur_months}
        )

    lines = []
    for s in segs:
        sub = d.filter(pl.col("report_month").is_in(s["months"]))
        avg = sub["value_yoy_3mma"].mean()
        turns = sub.filter(pl.col("拐点").is_not_null())["拐点"].unique().to_list()
        sec = sub.filter(pl.col("二阶导").is_not_null()).height
        acts = sub.filter(pl.col("action") != "")["action"].unique().to_list()
        lines.append(
            f"| {s['drv']} | {s['start']}~{s['end']} | {len(s['months'])} | "
            f"{_fmt(avg)} | {'、'.join(turns) if turns else '—'} | {sec} | "
            f"{'；'.join(acts) if acts else '—'} |"
        )
    return "\n".join(lines)


def _md_actions(a: pl.DataFrame) -> str:
    lines = []
    for r in a.iter_rows(named=True):
        lines.append(
            f"| {r['report_month']} | {_fmt(r['value_yoy_3mma'])} | 量 {_fmt(r['volume_yoy_3mma'])} / "
            f"价 {_fmt(r['price_yoy_3mma'])} | {r['驱动类型'] or '—'} | **{r['action']}** |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
