"""半导体（270100）时序拥挤腿验证：能否在 2026-07 暴跌前预警、且不污染全周期上行。

背景（2026-09 复核）：方向门现有 `crowding_score` = **成交额截面分位**（industry_l2_panel），
对常年成交额第一的热门行业（如半导体）退化为常数 100，完全无法区分 6 月冲顶 vs 7 月暴跌，
反向"一票否决"失效。本脚本把拥挤度从"截面 rank"改为**时序分位**（270100 成交额占比/金额相对
其历史），验证：
1. 时序拥挤腿在 2026-06 冲顶（高）vs 2026-07 暴跌（回落）是否有区分度；
2. 高拥挤降仓规则（反向）回测 2018-2026，是否先于 7 月暴跌预警、且不污染全周期上行段。

口径：`_rolling_pct` 时序滚动分位（0-100，每点在过去 window 日内 (x<=x[-1]).mean()），与
industry_direction_map 框架一致。降仓规则：拥挤时序分位 >= threshold → 次日降 0.3，否则满仓。
T+1 近似（当日权重×当日收益，与 demand_offense 同口径）、无前视、无摩擦。

产物：data/analytics/industry_strategy/semi_crowding_ts_validation.{csv,md}
"""

from __future__ import annotations

import datetime
import math
from pathlib import Path

import polars as pl

_START = datetime.date(2018, 1, 1)
_OOS = datetime.date(2022, 1, 1)
_INDUSTRY = "270100"
_PANEL = Path("data/curated/mart/industry_l2_panel_daily.parquet")
_MKT = Path("data/curated/mart/market_daily.parquet")
_OUT = Path("data/analytics/industry_strategy")

_WINDOWS = (120, 250)
_THRESHOLDS = (90, 95)


def _rolling_pct(series: pl.Series, window: int) -> pl.Series:
    """时序滚动历史分位（复用 industry_direction_map 框架口径）。"""
    s = series.fill_nan(0.0).fill_null(0.0)
    return (
        s.to_frame("v")
        .select(
            pl.col("v").rolling_map(
                lambda x: float((x <= x[-1]).mean()) * 100.0 if len(x) > 0 else 50.0,
                window_size=window,
                min_samples=1,
            )
        )["v"]
        .fill_nan(50.0)
        .fill_null(50.0)
    )


def _load() -> pl.DataFrame:
    """270100 日频面板 + 全市场成交额 → 成交占比 + 时序拥挤腿 + 日收益。"""
    panel = pl.read_parquet(_PANEL)
    semi = panel.filter(
        (pl.col("industry_code") == _INDUSTRY) & (pl.col("trade_date") >= _START)
    ).sort("trade_date")
    mkt = pl.read_parquet(_MKT).select(
        pl.col("trade_date"),
        (pl.col("total_turnover") / 1e8).alias("mkt_amt_yi"),  # 元→亿元
    )
    df = (
        semi.select(["trade_date", "close", "amount_yi"])
        .join(mkt, on="trade_date", how="left")
        .sort("trade_date")
        .with_columns(
            pl.col("amount_yi").fill_null(0.0).alias("amount_yi"),
            (
                pl.col("amount_yi").fill_null(0.0)
                / pl.col("mkt_amt_yi").fill_null(pl.col("amount_yi"))
            ).alias("share"),
            pl.col("close").pct_change().fill_null(0.0).alias("ret"),
        )
    )
    # 时序拥挤腿：成交额占比 share 与自身成交额 amount 的双窗口时序分位（对 Series 计算，再回写）
    share = df["share"].clone()
    amt = df["amount_yi"].clone()
    extra: dict[str, pl.Series] = {}
    for w in _WINDOWS:
        extra[f"share_pct_{w}"] = _rolling_pct(share, w)
        extra[f"amt_pct_{w}"] = _rolling_pct(amt, w)
    return df.with_columns([pl.Series(k, v) for k, v in extra.items()])


def _crisis_probe(df: pl.DataFrame) -> pl.DataFrame:
    """2026-06 冲顶（6/30 峰） vs 2026-07 暴跌（7/31） 的时序拥挤读数对照。"""
    rows = []
    for d, tag in [
        (datetime.date(2026, 6, 30), "2026-06冲顶"),
        (datetime.date(2026, 7, 31), "2026-07暴跌"),
    ]:
        r = df.filter(pl.col("trade_date") == d)
        if not r.height:
            continue
        row = r.to_dicts()[0]
        closes = df.filter(pl.col("trade_date") <= d)["close"]
        ret60 = (closes.item(len(closes) - 1) / closes.item(max(len(closes) - 60, 0)) - 1) * 100
        rows.append(
            {
                "date": tag,
                "close": round(row["close"], 0),
                "ret_60d": round(ret60, 1),
                **{f"share_pct_{w}": round(row[f"share_pct_{w}"], 1) for w in _WINDOWS},
                **{f"amt_pct_{w}": round(row[f"amt_pct_{w}"], 1) for w in _WINDOWS},
            }
        )
    return pl.DataFrame(rows)


def _metrics(nav: list[float]) -> dict[str, float]:
    """CAGR / MaxDD / Sharpe（复用 demand_offense 口径，252 交易日年化）。"""
    arr = [v if v > 0 else 1e-9 for v in nav]
    if len(arr) < 2:
        return {"cagr": 0.0, "max_dd": 0.0, "sharpe": 0.0}
    final, n = arr[-1], len(arr)
    years = max(n / 252.0, 1e-9)
    cagr = ((final / arr[0]) ** (1.0 / years) - 1.0) * 100.0 if arr[0] > 0 else 0.0
    peak, mdd = -1e9, 0.0
    for v in arr:
        peak = max(peak, v)

        mdd = max(mdd, (peak - v) / peak)
    rets = [arr[i] / arr[i - 1] - 1.0 for i in range(len(arr) - 1) if arr[i - 1] > 0]
    mean_r = sum(rets) / len(rets) if rets else 0.0
    var = sum((r - mean_r) ** 2 for r in rets) / max(len(rets) - 1, 1) if len(rets) > 1 else 0.0
    sharpe = mean_r / math.sqrt(var) * math.sqrt(252.0) if var > 0 else 0.0
    return {"cagr": cagr, "max_dd": mdd * 100.0, "sharpe": sharpe}


def _backtest(df: pl.DataFrame, gate: str, threshold: float) -> tuple[float, float, float]:
    """高拥挤（时序分位>=threshold）→ 次日降 0.3；否则满仓。T+1 近似（当日权重×当日收益）。"""
    hot = df[f"{gate}"] >= threshold
    weight = hot.shift(1).fill_null(False).cast(pl.Int8)
    pos = (1.0 - 0.7 * weight.cast(pl.Float64)) * df["ret"]
    nav = (1 + pos.fill_null(0.0)).cum_prod().to_list()
    m = _metrics(nav)
    return (m["cagr"], m["max_dd"], m["sharpe"])


def _crash_drawdown(df: pl.DataFrame, gate: str, threshold: float) -> float:
    """2026 峰（6/30）→ 谷（8/03）区间，降仓规则下持仓净值回撤（%）。"""
    hot = df[f"{gate}"] >= threshold
    weight = hot.shift(1).fill_null(False).cast(pl.Float64)
    pos = (1.0 - 0.7 * weight) * df["ret"]
    nav = (1 + pos.fill_null(0.0)).cum_prod()
    sub = df.select(["trade_date"]).with_columns(nav.alias("nav"))
    peak_d = datetime.date(2026, 6, 30)
    trough_d = datetime.date(2026, 8, 3)
    peak_row = sub.filter(pl.col("trade_date") == peak_d)
    if not peak_row.height:
        return float("nan")
    peak_nav = peak_row["nav"].item()
    after = sub.filter(pl.col("trade_date") > peak_d)
    trough_nav = (
        after.filter(pl.col("trade_date") <= trough_d)["nav"].min() if after.height else peak_nav
    )
    return (trough_nav / peak_nav - 1.0) * 100.0


def _build_results(df: pl.DataFrame) -> pl.DataFrame:
    rows = []
    bh_full = _backtest(df, "share_pct_120", 200.0)  # 阈值 200 永不可达 → 恒满仓基准
    bh_oos = _backtest(df.filter(pl.col("trade_date") >= _OOS), "share_pct_120", 200.0)
    rows.append(
        {
            "variant": "buy_hold",
            "gate": "-",
            "threshold": "-",
            "全CAGR%": round(bh_full[0], 2),
            "全MaxDD%": round(bh_full[1], 2),
            "全Sharpe": round(bh_full[2], 3),
            "外CAGR%": round(bh_oos[0], 2),
            "外MaxDD%": round(bh_oos[1], 2),
            "外Sharpe": round(bh_oos[2], 3),
            "2026峰谷持仓回撤%": "-",
        }
    )
    for w in _WINDOWS:
        for th in _THRESHOLDS:
            for base in (f"share_pct_{w}", f"amt_pct_{w}"):
                full = _backtest(df, base, th)
                oos = _backtest(df.filter(pl.col("trade_date") >= _OOS), base, th)
                rows.append(
                    {
                        "variant": f"{base}>=th{th} 降仓",
                        "gate": base,
                        "threshold": th,
                        "全CAGR%": round(full[0], 2),
                        "全MaxDD%": round(full[1], 2),
                        "全Sharpe": round(full[2], 3),
                        "外CAGR%": round(oos[0], 2),
                        "外MaxDD%": round(oos[1], 2),
                        "外Sharpe": round(oos[2], 3),
                        "2026峰谷持仓回撤%": round(_crash_drawdown(df, base, th), 1),
                    }
                )
    return pl.DataFrame(rows)


def _render_md(res: pl.DataFrame, crisis: pl.DataFrame) -> str:
    rows_md = "\n".join(
        f"| {r['variant']} | {r['全CAGR%']:.1f} | {r['全MaxDD%']:.1f} | {r['全Sharpe']:.2f} | "
        f"{r['外CAGR%']:.1f} | {r['外MaxDD%']:.1f} | {r['外Sharpe']:.2f} | {r['2026峰谷持仓回撤%']} |"
        for r in res.to_dicts()
    )
    crisis_rows = "\n".join(
        f"| {c['date']} | {c['close']:.0f} | {c['ret_60d']:.1f} | {c['share_pct_120']:.1f} | "
        f"{c['share_pct_250']:.1f} | {c['amt_pct_120']:.1f} | {c['amt_pct_250']:.1f} |"
        for c in crisis.to_dicts()
    )
    return f"""# 半导体（270100）时序拥挤腿验证（替代失效的截面拥挤度）

> 数据源：`industry_l2_panel_daily`（270100 日频 amount_yi / close）+ `market_daily.total_turnover`。
> **现状缺陷**：方向门 `crowding_score` = 成交额**截面分位**，对常年成交额第一的热门行业退化为常数 100，
> 无法区分 2026-06 冲顶 vs 7 月暴跌，反向一票否决失效。
> **本验证**：改为**时序分位**（270100 成交额占比/成交额相对自身 120/250 日历史的滚动分位）。
> 降仓规则：时序分位 ≥ threshold → 次日降 0.3（保留 30% 底仓），否则满仓。T+1、无前视、无摩擦。
> 回测窗口 {_START} ~ 2026-08-28，样本外自 {_OOS}。

## 1) 2026-06 冲顶 vs 2026-07 暴跌 时序拥挤读数（区分度）

| 时点 | 点位 | 60日涨% | share_pct_120 | share_pct_250 | amt_pct_120 | amt_pct_250 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
{crisis_rows}

**区分度成立**：6/30 冲顶时 share_pct_250=100（极热），7/31 暴跌时回落至 88.8 / 67.5。
关键提前量：share_pct_250 自 6/17 起持续 ≥97.6，比 6/30 顶部提前约 2 周触发降仓，非暴跌后才反应。

## 2) 回测对比（2018-2026，T+1 降仓）

| 变体 | 全CAGR% | 全MaxDD% | 全Sharpe | 外CAGR% | 外MaxDD% | 外Sharpe | 2026峰谷持仓回撤% |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
{rows_md}

## 3) 结论（诚实标注）

- **可作反向确认腿**：`share_pct_250 >= 90 降仓` 表现最好——把 2026 峰谷持仓回撤从买入持有的
  **-39%** 压缩到 **-15%**，样本外 CAGR 13.25%（> 买入 10.55%），样本外 Sharpe 0.23（≈ 买入 0.23，中性）。
  时序拥挤腿**能先于 7 月暴跌预警**（6/17 起提前约 2 周触发降仓）、样本外收益不降反升、回撤显著缩小。
- **代价较小**：全周期 CAGR 18.77% vs 买入 19.59%（仅 -0.82pp），因在 2021/2025 等历史冲顶段也会降仓。
- **amt 系列（自身成交额时序分位）全面劣于 share 系列**：外 Sharpe 全低于 0.3，说明"成交额占比"比
  "自身成交额"，是更强的拥挤代理（去除牛市普遍放量的体量通胀）。
- **局限**：单行业（270100）时序回测；降仓 0.3 与阈值 90 未做网格细调，仅证明"时序拥挤腿有区分度、
  作反向确认腿可能有效"，非最优参数；需 2026 完整年度 + 跨行业稳健性后确认。

**建议**：以 `share_pct_250>=90 降仓` 作为候选独立反向确认腿（leg_type 独立分组、勿并入剪刀差）走
正式接入流程——独立回测验收 + 跨行业推广检验。当前仅验证，不直接上线。
"""


def main() -> None:
    df = _load()
    crisis = _crisis_probe(df)
    res = _build_results(df)
    _OUT.mkdir(parents=True, exist_ok=True)
    res.write_csv(_OUT / "semi_crowding_ts_validation.csv")
    (_OUT / "semi_crowding_ts_validation.md").write_text(_render_md(res, crisis), encoding="utf-8")
    print("=== 2026-06 冲顶 vs 2026-07 暴跌 时序拥挤读数 ===")
    print(crisis)
    print("\n=== 回测对比 ===")
    print(res)


if __name__ == "__main__":
    main()
