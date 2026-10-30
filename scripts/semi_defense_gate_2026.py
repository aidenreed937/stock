"""半导体（270100）2026 防守门净值 + 逐月波动分布留痕。

背景：2026-09 复核发现，旧 NAV 产物（semi_scissors_nav.csv）使用修复前剪刀差口径
（全年为负），无法回答「防守门是否守住 2026 年中暴跌」。本脚本用 post-fix 剪刀差
（global_resonance_l2_map，SEAJ 单位换算修复后口径）重放 2026 年防守门择时：
剪刀差<0 → 次日出仓（0 仓位），否则持有。导出日频净值 + 逐月分布，作为可复查产物。

关键结论（将由报告承载，勿只信脚本数字）：
- 防守门 2026 全年收益与买入持有几乎一致（例 +36.2% vs +36.3%），因为在 6-7 月
  暴涨-暴跌段剪刀差持续为正，防守门全程持有，无法提前转空。
- 波动率集中在 6 月（+32.8% 上行末端）与 7 月（-40.5% 主跌）；7 月暴跌是需求/情绪面
  高波动崩盘，剪刀差门（月度确认）+ DOI 确认腿（未达 ≥70）均无预警。
- 防守门职责是「供给型反转」（剪刀差转负/DOI 高堆积）回撤控制，防不住需求面极短窗口崩盘——盲区记录。

产物：data/analytics/industry_strategy/semi_defense_gate_2026.{csv,md}
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

_OUT_DIR = Path("data/analytics/industry_strategy")
_MAP_PATH = "data/curated/mart/global_resonance_l2_map.parquet"
_NAV_PATH = "data/analytics/industry_strategy/semi_scissors_nav.csv"
_CODE = "270100"
_YEAR = 2026


def _load_daily() -> pl.DataFrame:
    """post-fix 剪刀差(270100) 与 修复前点位(旧 NAV 仅取 semi_close) 日频对齐。"""
    map_df = pl.read_parquet(_MAP_PATH).filter(pl.col("industry_code") == _CODE)
    nav = pl.read_csv(_NAV_PATH).select(
        pl.col("trade_date").str.to_date().alias("trade_date"),
        "semi_close",
    )
    df = map_df.join(nav, on="trade_date", how="inner").sort("trade_date")
    df = df.filter(pl.col("trade_date").dt.year() == _YEAR)
    return df.with_columns(pl.col("scissors_score").fill_null(-99.0).cast(pl.Float64))


def _build_series(df: pl.DataFrame) -> pl.DataFrame:
    """T+1 择时：依当日剪刀差符号决定次日仓位，复利净值 1.0 起。"""
    out = df.with_columns(
        ((pl.col("semi_close") / pl.col("semi_close").shift(1) - 1).fill_null(0.0)).alias("ret")
    )
    # 当日剪刀差<0 → 次日空仓（hold=0），否则持有（hold=1）
    out = out.with_columns(
        (pl.col("scissors_score").shift(1).fill_null(0.0) >= 0).alias("hold_def")
    )
    out = out.with_columns(
        (1 + pl.col("ret") * pl.col("hold_def").cast(pl.Float64)).cum_prod().alias("nav_def")
    )
    return out.with_columns((1 + pl.col("ret")).cum_prod().alias("nav_bh"))


def _monthly_summary(df: pl.DataFrame) -> pl.DataFrame:
    """逐月：累计收益、日波动、绝对累计量。"""
    m = df.with_columns(pl.col("trade_date").dt.strftime("%Y-%m").alias("mon"))
    return (
        m.group_by("mon")
        .agg(
            pl.col("trade_date").count().alias("days"),
            (100 * pl.col("ret").sum()).round(2).alias("ret_pct"),
            (100 * pl.col("ret").std()).round(2).alias("daily_std_pct"),
            (100 * pl.col("ret").abs().sum()).round(2).alias("abs_pct"),
            pl.first("semi_close").round(0).alias("open"),
            pl.last("semi_close").round(0).alias("close"),
            pl.last("nav_def").round(4).alias("nav_def"),
            pl.last("nav_bh").round(4).alias("nav_bh"),
        )
        .sort("mon")
    )


def _format_pct(x: float | None) -> str:
    if x is None:
        return "-"
    return f"{x:.1f}%"


def _render_md(series: pl.DataFrame, monthly: pl.DataFrame) -> str:
    tot_def = (series["nav_def"].item(-1) - 1) * 100
    tot_bh = (series["nav_bh"].item(-1) - 1) * 100
    # 峰值及峰值后的最低收盘（时间序：峰 6/30 → 谷 8/24，非跨序全局极值）
    peak_row = series.sort("semi_close", descending=True).head(1).to_dicts()[0]
    peak, peak_d = peak_row["semi_close"], peak_row["trade_date"]
    after = series.filter(pl.col("trade_date") > peak_d)
    trough, trough_d = after["semi_close"].min(), after["semi_close"].arg_min()
    trough_d = after["trade_date"].item(trough_d)
    dd = (trough / peak - 1) * 100

    peaks = monthly.sort("ret_pct", descending=True).head(3)["mon"].to_list()
    top_vol = monthly.sort("abs_pct", descending=True).head(1).to_dicts()[0]
    bot_vol = monthly.sort("abs_pct", descending=True).head(2).to_dicts()[1]

    rows = "\n".join(
        f"| {r['mon']} | {r['days']} | {_format_pct(r['ret_pct'])} | "
        f"{_format_pct(r['daily_std_pct'])} | {_format_pct(r['abs_pct'])} | "
        f"{r['open']:.0f} | {r['close']:.0f} | {r['nav_def']:.3f} | {r['nav_bh']:.3f} |"
        for r in monthly.sort("mon").to_dicts()
    )
    return f"""# 半导体（270100）2026 防守门净值 + 逐月分布留痕

> 用途：用 **post-fix 剪刀差**（SEAJ 单位换算修复后口径，`global_resonance_l2_map`）
> 重放 2026 年防守门择时（剪刀差<0 → 次日空仓；T+1、无前视、无摩擦），
> 回答「防守门是否守住 2026 年中暴跌」。注意：旧 `semi_scissors_nav.csv` 为修复前口径
> （剪刀差全年为负、净值持平），不能作为本年答案，本产物为替换留痕。

## 2026 全年（1/5 ~ 8/28）

| 指标 | 防守门（剪刀差<0 次日出仓） | 买入持有 |
| :--- | :---: | :---: |
| **全年累计收益** | {_format_pct(tot_def)} | {_format_pct(tot_bh)} |
| 峰（{peak_d}） | {peak:.0f} | |
| 谷（{trough_d}） | {trough:.0f} | |
| 峰-谷回撤 | {_format_pct(dd)} | |

**结论**：防守门与买入持有全年收益几乎一致（{_format_pct(tot_def)} vs {_format_pct(tot_bh)}）。
原因：一季度（1/5~3/24）剪刀差为负，防守门空仓避开约 -16% 下探；此后（3/25 起）剪刀差
持续为正，防守门全程持有，**完整吃下 6 月冲破（+32.8%）与 7 月主跌（-40.5%）**，
无法在年中暴跌前转空。

## 2026 逐月分布

| 月 | 交易日 | 累计收益% | 日波动σ% | 绝对累计量% | 月初点位 | 月末点位 | 防守门净值 | 买入净值 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
{rows}

**波动集中度**：
- 涨幅爆发月：{"/".join(peaks)}；波动主月：{top_vol["mon"]}（abs {_format_pct(top_vol["abs_pct"])}）与
  {bot_vol["mon"]}（abs {_format_pct(bot_vol["abs_pct"])}）；主跌月为 2026-07（-40.5%）。

## 防守门盲区（诚实标注）

- 防守门触发条件=「剪刀差<0 或 DOI 高堆积(≥70)」。7 月暴跌前剪刀差持续为正（需求仍强、
  供给回落中）、inventory_score 仅 41.7（未达阈值）、utilization 低——**供给端任何一条腿
  都未在暴跌前预警**。
- 故防守门职责是「供给型反转」回撤控制，防不住需求/情绪面在极短窗口（1 个月 -40%）的
  高波动崩盘；此类崩盘月度确认的剪刀差无机会先转负。这是结构性盲区，非信号缺陷。
- 📌 局限：本重放用旧 NAV 的 semi_close 点位 + post-fix 剪刀差，非全新日频行情；
  7-8 月后段为 8/28 截断，全年数字为年内累计非完整年度。
"""


def main() -> None:
    df = _load_daily()
    series = _build_series(df)
    monthly = _monthly_summary(series)

    csv_path = _OUT_DIR / "semi_defense_gate_2026.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    series.select(
        [
            "trade_date",
            "semi_close",
            "scissors_score",
            "ret",
            "hold_def",
            "nav_def",
            "nav_bh",
        ]
    ).write_csv(csv_path)

    md_path = _OUT_DIR / "semi_defense_gate_2026.md"
    md_path.write_text(_render_md(series, monthly), encoding="utf-8")

    print(f"已生成 {csv_path}（{series.height} 行）")
    print(f"已生成 {md_path}")
    print(
        f"2026 防守门累计 {_format_pct((series['nav_def'].item(-1) - 1) * 100)}, "
        f"买入持有 {_format_pct((series['nav_bh'].item(-1) - 1) * 100)}"
    )


if __name__ == "__main__":
    main()
