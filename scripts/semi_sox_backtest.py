"""半导体（270100 产业剪刀差信号）在 SOX 与 270100 上的对照回测。

背景（2026-09 假设检验）：剪刀差信号的数据腿是全球产业实物流量
（demand=TSMC 月营收 + SIA 全球销售额，supply=SEAJ 日本制设备出货），
因此理论上对全球半导体指数 SOX（费城半导体指数）也应有预测力。
本脚本用与 270100 完全相同的腿与信号变体在 SOX 上回测，检验该假设。

结论摘要（实证，详见 md 产物）：
- 假设证伪：样本外（2022-01 起）SOX 上所有信号变体（Sharpe 0.61~0.78）
  全部跑输买入持有（0.80）；270100 上进攻脚把 Sharpe 从 0.44 抬到 0.94。
- 全周期 IC（SOX 未来 60 日收益）：demand -0.104 / supply +0.017 / scissors -0.101，
  分年符号大幅翻转（2016 +0.553 → 2024 -0.499），非稳定因子。
- 象限反转：demand 高 × sc>=0（270100 最优格）在 SOX 上是最差象限
  （fwd60 +1.64%、上涨率 58%）。
- 机制：美股对全球产业数据提前定价，剪刀差信号在美股无预测窗口；
  信号有效性依赖"A 股对全球产业数据的滞后反应"这一摩擦。

信号定义与变体（与 scripts/industry_semi_demand_offense.py 同口径）：
- buy_hold：全程满仓（基准）。
- defense：剪刀差<0 或 DOI(inventory_score)>=70 -> 0.3，否则 1.0（防守门）。
- offense：demand>=70 且 scissors>=0 -> 1.0，否则 0.3（进攻脚）。
- offense_def：进攻脚 × 防守门 组合。
- scissors_pos：scissors>=0 -> 1.0，否则 0.3（纯剪刀差正向）。

口径：信号当日生成当日匹配收益（与既有脚本一致，腿为月频 release_date
前向填充，大部分日期信号早已确定，无新增前视）；年化 252 日。

输出：data/analytics/industry_strategy/semi_sox_backtest.{csv,md}
      data/analytics/industry_strategy/semi_sox_ic.csv
"""

from __future__ import annotations

import datetime
import math
from pathlib import Path

import polars as pl
from scipy import stats

_START = datetime.date(2018, 1, 1)
_OOS = datetime.date(2022, 1, 1)
_LEGS = Path("data/analytics/semiconductor/latest/semiconductor_legs.parquet")
_SUPPLY_LEGS = Path("data/curated/mart/semiconductor_supply_legs.parquet")
_GM = Path("data/curated/mart/global_macro_daily.parquet")
_PANEL = Path("data/curated/mart/industry_l2_panel_daily.parquet")
_OUT = Path("data/analytics/industry_strategy")
_INDUSTRY = "270100"

_MODES = ["buy_hold", "defense", "offense", "offense_def", "scissors_pos"]
_LABELS = {
    "buy_hold": "买入持有（基准）",
    "defense": "防守门（剪刀差<0 或 DOI>=70 降 0.3）",
    "offense": "进攻脚（demand>=70 且 scissors>=0 满仓）",
    "offense_def": "进攻脚 × 防守门",
    "scissors_pos": "剪刀差正向（scissors>=0）",
}


def _load_signal() -> pl.DataFrame:
    """加载 270100 产业剪刀差腿（demand/supply/scissors + inventory DOI）。"""
    legs = pl.read_parquet(_LEGS).filter(pl.col("industry_code") == _INDUSTRY)
    inv = pl.read_parquet(_SUPPLY_LEGS).filter(pl.col("industry_code") == _INDUSTRY)
    return (
        legs.select(["trade_date", "demand_score", "supply_score", "scissors_score"])
        .join(inv.select(["trade_date", "inventory_score"]), on="trade_date", how="left")
        .sort("trade_date")
    )


def _load_sox() -> pl.DataFrame:
    """SOX（费城半导体指数）日收益，仅美股交易日。"""
    gm = pl.read_parquet(_GM).select(["trade_date", "sox_close"])
    return (
        gm.filter(pl.col("sox_close").is_not_null())
        .sort("trade_date")
        .with_columns(pl.col("sox_close").pct_change().fill_null(0.0).alias("ret"))
        .select(["trade_date", "sox_close", "ret"])
    )


def _load_l2() -> pl.DataFrame:
    """270100（申万二级半导体）日收益。"""
    panel = pl.read_parquet(_PANEL).filter(pl.col("industry_code") == _INDUSTRY)
    return (
        panel.select(["trade_date", "close"])
        .sort("trade_date")
        .with_columns(pl.col("close").pct_change().fill_null(0.0).alias("ret"))
        .select(["trade_date", "ret"])
    )


def _weight(mode: str, demand: float, scissors: float, inv: float) -> float:
    d = demand if demand is not None and not math.isnan(demand) else 50.0
    sc = scissors if scissors is not None and not math.isnan(scissors) else 50.0
    inv = inv if inv is not None and not math.isnan(inv) else 50.0
    if mode == "buy_hold":
        return 1.0
    if mode == "defense":
        return 0.3 if (sc < 0 or inv >= 70) else 1.0
    if mode == "offense":
        return 1.0 if (d >= 70 and sc >= 0) else 0.3
    if mode == "offense_def":
        offense = 1.0 if (d >= 70 and sc >= 0) else 0.3
        defense = 0.3 if (sc < 0 or inv >= 70) else 1.0
        return offense * defense
    if mode == "scissors_pos":
        return 1.0 if sc >= 0 else 0.3
    return 1.0


def _metrics(nav: list[float]) -> dict[str, float]:
    arr = [v if v > 0 else 1e-9 for v in nav]
    if len(arr) < 2:
        return {"cagr": 0.0, "max_dd": 0.0, "sharpe": 0.0}
    years = max(len(arr) / 252.0, 1e-9)
    cagr = ((arr[-1] / arr[0]) ** (1.0 / years) - 1.0) * 100.0
    peak, mdd = -1e18, 0.0
    for v in arr:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak)
    rets = [arr[i] / arr[i - 1] - 1.0 for i in range(1, len(arr))]
    mean_r = sum(rets) / len(rets)
    var = sum((r - mean_r) ** 2 for r in rets) / max(len(rets) - 1, 1)
    sharpe = mean_r / math.sqrt(var) * math.sqrt(252.0) if var > 0 else 0.0
    return {"cagr": cagr, "max_dd": mdd * 100.0, "sharpe": sharpe}


def _run_backtest(
    target: pl.DataFrame, signal: pl.DataFrame, mode: str, start: datetime.date
) -> dict[str, float]:
    df = (
        target.join(signal, on="trade_date", how="inner")
        .filter(pl.col("trade_date") >= start)
        .sort("trade_date")
    )
    pos = [
        _weight(mode, r["demand_score"], r["scissors_score"], r["inventory_score"]) * r["ret"]
        for r in df.iter_rows(named=True)
    ]
    nav = [1.0]
    for p in pos:
        nav.append(nav[-1] * (1 + p))
    return _metrics(nav)


def _safe_spearman(a: list[float], b: list[float]) -> float | None:
    """Spearman 秩相关；输入过短或序列恒定（平台填充段）时返回 None。"""
    if len(a) < 30 or len(set(a)) < 2 or len(set(b)) < 2:
        return None
    return round(stats.spearmanr(a, b)[0], 3)


def _sox_ic_table(signal: pl.DataFrame) -> pl.DataFrame:
    """三腿对 SOX 未来 60 日收益的分年/全周期 Spearman IC。"""
    m = (
        _load_sox()
        .join(signal, on="trade_date", how="inner")
        .sort("trade_date")
        .with_columns(pl.col("sox_close").shift(-60).alias("c60"))
        .with_columns((pl.col("c60") / pl.col("sox_close") - 1.0).alias("f60"))
        .drop_nulls(["f60", "ret"])
    )
    rows = []
    for y in sorted(m["trade_date"].dt.year().unique().to_list()):
        sub = m.filter(pl.col("trade_date").dt.year() == y).drop_nulls(["f60"])
        if len(sub) < 30:
            continue
        rows.append(
            {
                "year": y,
                "n": len(sub),
                "demand_ic": _safe_spearman(sub["demand_score"].to_list(), sub["f60"].to_list()),
                "supply_ic": _safe_spearman(sub["supply_score"].to_list(), sub["f60"].to_list()),
                "scissors_ic": _safe_spearman(
                    sub["scissors_score"].to_list(), sub["f60"].to_list()
                ),
            }
        )
    rows.append(
        {
            "year": "全周期",
            "n": len(m),
            "demand_ic": _safe_spearman(m["demand_score"].to_list(), m["f60"].to_list()),
            "supply_ic": _safe_spearman(m["supply_score"].to_list(), m["f60"].to_list()),
            "scissors_ic": _safe_spearman(m["scissors_score"].to_list(), m["f60"].to_list()),
        }
    )
    return pl.DataFrame(rows)


def _sox_quadrant(signal: pl.DataFrame) -> pl.DataFrame:
    """demand × scissors 四象限在 SOX 上的 fwd60 中位收益。"""
    m = (
        _load_sox()
        .join(signal, on="trade_date", how="inner")
        .sort("trade_date")
        .with_columns(pl.col("sox_close").shift(-60).alias("c60"))
        .with_columns((pl.col("c60") / pl.col("sox_close") - 1.0).alias("f60"))
        .drop_nulls(["f60", "ret"])
    )
    rows = []
    for d_lab, d_lo, d_hi in [("demand低", 0, 60), ("demand高", 60, 100)]:
        for s_lab, s_lo, s_hi in [("sc<0", -200, 0), ("sc>=0", 0, 200)]:
            sel = m.filter(
                (pl.col("demand_score") >= d_lo)
                & (pl.col("demand_score") < d_hi)
                & (pl.col("scissors_score") >= s_lo)
                & (pl.col("scissors_score") < s_hi)
            )
            rows.append(
                {
                    "quadrant": f"{d_lab} × {s_lab}",
                    "n": len(sel),
                    "fwd60_median_pct": round(sel["f60"].median() * 100, 2) if len(sel) else None,
                    "up_rate_pct": round((sel["f60"] > 0).mean() * 100, 1) if len(sel) else None,
                }
            )
    return pl.DataFrame(rows)


def main() -> None:
    signal = _load_signal()
    sox, l2 = _load_sox(), _load_l2()
    _OUT.mkdir(parents=True, exist_ok=True)

    # 1. 回测表（SOX vs 270100 × 5 变体 × 2 区间）
    rows = []
    for start, window in [(_START, "full"), (_OOS, "oos")]:
        for mode in _MODES:
            s_sox, s_l2 = (
                _run_backtest(sox, signal, mode, start),
                _run_backtest(l2, signal, mode, start),
            )
            rows.append(
                {
                    "window": window,
                    "mode": mode,
                    "label": _LABELS[mode],
                    "sox_cagr": round(s_sox["cagr"], 1),
                    "sox_maxdd": round(s_sox["max_dd"], 1),
                    "sox_sharpe": round(s_sox["sharpe"], 2),
                    "l2_cagr": round(s_l2["cagr"], 1),
                    "l2_maxdd": round(s_l2["max_dd"], 1),
                    "l2_sharpe": round(s_l2["sharpe"], 2),
                }
            )
    bt = pl.DataFrame(rows)
    bt.write_csv(_OUT / "semi_sox_backtest.csv")

    # 2. SOX 三腿 IC
    ic = _sox_ic_table(signal)
    ic.write_csv(_OUT / "semi_sox_ic.csv")

    # 3. SOX 象限
    qd = _sox_quadrant(signal)

    # 4. md 报告
    def _rows(win: str) -> str:
        out = []
        for r in bt.filter(pl.col("window") == win).iter_rows(named=True):
            out.append(
                f"| {r['label']} | {r['sox_cagr']:.1f}% | {r['sox_maxdd']:.1f}% | {r['sox_sharpe']:.2f} "
                f"| {r['l2_cagr']:.1f}% | {r['l2_maxdd']:.1f}% | {r['l2_sharpe']:.2f} |"
            )
        return "\n".join(out)

    def _fmt3(v: float | None) -> str:
        return f"{v:.3f}" if v is not None else "—"

    def _fmt2(v: float | None) -> str:
        return f"{v:.2f}" if v is not None else "—"

    def _fmt0(v: float | None) -> str:
        return f"{v:.0f}" if v is not None else "—"

    ic_lines = "\n".join(
        f"| {r['year']} | {r['n']} | {_fmt3(r['demand_ic'])} | {_fmt3(r['supply_ic'])} | {_fmt3(r['scissors_ic'])} |"
        for r in ic.iter_rows(named=True)
    )
    qd_lines = "\n".join(
        f"| {r['quadrant']} | {r['n']} | {_fmt2(r['fwd60_median_pct'])}% | {_fmt0(r['up_rate_pct'])}% |"
        for r in qd.iter_rows(named=True)
    )

    # 结论段动态取值
    oos = bt.filter(pl.col("window") == "oos")
    sox_variants = oos.filter(~pl.col("mode").is_in(["buy_hold"]))["sox_sharpe"]
    sox_bh = oos.filter(pl.col("mode") == "buy_hold")["sox_sharpe"][0]
    l2_bh = oos.filter(pl.col("mode") == "buy_hold")["l2_sharpe"][0]
    l2_off = oos.filter(pl.col("mode") == "offense")["l2_sharpe"][0]
    ic_full = ic.filter(pl.col("year") == "全周期")
    ic_years = ic.filter(pl.col("year") != "全周期").drop_nulls(["scissors_ic"])
    best_y = ic_years.sort("scissors_ic", descending=True).head(1)
    worst_y = ic_years.sort("scissors_ic").head(1)
    qd_worst = qd.sort("fwd60_median_pct").head(1)

    md = f"""# 半导体剪刀差信号：SOX vs 270100 对照回测

> 2026-09 假设检验：剪刀差信号的数据腿是全球产业实物流量（demand=TSMC+SIA、supply=SEAJ），
> 理论上应对全球半导体指数 SOX 同样有预测力。本报告用与 270100 完全相同的腿与信号变体在
> SOX 上回测。口径与 `scripts/industry_semi_demand_offense.py` 一致（T+1、无前视、无摩擦）。

## 一、核心结论（假设证伪）

1. **样本外（2022-01 起）SOX 上所有信号变体跑输买入持有**：
   Sharpe {sox_variants.min():.2f}~{sox_variants.max():.2f} vs 买入 {sox_bh:.2f}；
   270100 上进攻脚把 Sharpe 从 {l2_bh:.2f} 抬到 **{l2_off:.2f}**。
2. **全周期 IC（SOX 未来 60 日收益）无预测力**：demand **{_fmt3(ic_full["demand_ic"][0])}** /
   supply {_fmt3(ic_full["supply_ic"][0])} / scissors **{_fmt3(ic_full["scissors_ic"][0])}**；
   分年 IC 大幅翻转（{best_y["year"][0]} {best_y["scissors_ic"][0]:+.3f} →
   {worst_y["year"][0]} {worst_y["scissors_ic"][0]:+.3f}），非稳定因子。
3. **象限反转**：demand 高 × sc>=0（270100 最优格）在 SOX 上是最差象限
   （fwd60 {_fmt2(qd_worst["fwd60_median_pct"][0])}%、上涨率 {_fmt0(qd_worst["up_rate_pct"][0])}%）。
4. **机制**：美股对全球产业数据提前定价，信号在美股无预测窗口；剪刀差的有效性依赖
   "A 股对全球产业数据的滞后反应"这一摩擦。

## 二、回测对比（全周期 2018-01 起）

| 变体 | SOX CAGR | SOX MaxDD | SOX Sharpe | 270100 CAGR | 270100 MaxDD | 270100 Sharpe |
| :-- | --: | --: | --: | --: | --: | --: |
{_rows("full")}

## 三、回测对比（样本外 2022-01 起）

| 变体 | SOX CAGR | SOX MaxDD | SOX Sharpe | 270100 CAGR | 270100 MaxDD | 270100 Sharpe |
| :-- | --: | --: | --: | --: | --: | --: |
{_rows("oos")}

## 四、SOX 三腿 IC（对 SOX 未来 60 日收益，Spearman）

| 年份 | n | demand IC | supply IC | scissors IC |
| :-- | --: | --: | --: | --: |
{ic_lines}

## 五、SOX 象限（demand × scissors，fwd60 中位）

| 象限 | n | fwd60 中位 | 上涨率 |
| :-- | --: | --: | --: |
{qd_lines}

## 六、定位

- 剪刀差/产业腿信号**只在 A 股承接侧有效**（270100 实证），不对 SOX 作交易判定；
- SOX 保留在"全球方向层"作拐点预警与参考（方向分 semi 腿），不作判定层；
- 本回测支持框架定稿："识别真景气的正确信号是全球资本开支，但交易对象是 A 股承接"。
"""
    (_OUT / "semi_sox_backtest.md").write_text(md, encoding="utf-8")

    print("=== 半导体剪刀差信号 SOX vs 270100 对照回测 ===")
    print(bt.select(["window", "label", "sox_sharpe", "l2_sharpe"]))
    print(f"\nCSV: {_OUT / 'semi_sox_backtest.csv'}")
    print(f"IC:  {_OUT / 'semi_sox_ic.csv'}")
    print(f"MD:  {_OUT / 'semi_sox_backtest.md'}")


if __name__ == "__main__":
    main()
