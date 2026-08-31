"""行业轮动「宏观范式相态」实证：状态 × 风格倾斜（非二值空仓）。

背景：v1/v2 证明 panic/overheat 阈值**二值空仓**样本外无效（panic 滞后、overheat 牛市误触发）。
本实证换机制——状态切换**行业候选池（风格倾斜）**而非空仓：
- 恐慌态（panic > 65）→ 防御红利池动量 Top3（避险不空仓）；
- 过热态（overheat > 65 且 panic < 50）→ 变体分别映射到 防御池 / 周期池 / 反拥挤全池；
- 常态 → 全池动量 Top3。

对比 baseline（全池动量 Top3，样本外 Sharpe 0.35）。CAGR 段内首值归一化，样本外 2022 后。

风格池（申万一级 31 行业）：
- 防御红利：银行/煤炭/公用/食品饮料/石油石化/交运
- 周期：有色/基础化工/钢铁/建材/机械
- 成长：电子/计算机/通信/电力设备/军工/医药
"""

from __future__ import annotations

from datetime import date
from math import sqrt
from pathlib import Path

import polars as pl

from stock_data.catalog import DataCatalog
from stock_strategy.base import BaseStrategy
from stock_strategy.industry.assembly import (
    assemble_industry_panel,
    load_industry_price_panel,
)
from stock_strategy.industry.runner import IndustryStrategyRunner
from stock_strategy.signal import Signal, SignalDirection

_TRADING_DAYS_PER_YEAR = 252.0
_OUT_DIR = Path("data/analytics/industry_strategy")

_DEFENSIVE = {"801780.SI", "801950.SI", "801160.SI", "801120.SI", "801960.SI", "801170.SI"}
_CYCLICAL = {"801050.SI", "801030.SI", "801040.SI", "801710.SI", "801890.SI"}
_GROWTH = {"801080.SI", "801750.SI", "801770.SI", "801730.SI", "801740.SI", "801150.SI"}


def _metrics(nav_df: pl.DataFrame) -> dict[str, float]:
    navs = [float(v) for v in nav_df["nav"].to_list()]
    n = len(navs)
    final = navs[-1]
    years = n / _TRADING_DAYS_PER_YEAR
    cagr = (
        ((final / navs[0]) ** (1.0 / years) - 1.0) * 100.0
        if years > 0 and final > 0 and navs[0] > 0
        else 0.0
    )
    peak = navs[0]
    max_dd = 0.0
    for v in navs:
        peak = max(peak, v)
        dd = (peak - v) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    rets = [navs[i] / navs[i - 1] - 1.0 for i in range(1, n)]
    mean_r = sum(rets) / len(rets) if rets else 0.0
    var_r = sum((r - mean_r) ** 2 for r in rets) / (len(rets) - 1) if len(rets) > 1 else 0.0
    sharpe = mean_r / sqrt(var_r) * sqrt(_TRADING_DAYS_PER_YEAR) if var_r > 0 else 0.0
    calmar = cagr / (max_dd * 100.0) if max_dd > 0 else 0.0
    return {"cagr": cagr, "max_drawdown": max_dd * 100.0, "sharpe": sharpe, "calmar": calmar}


class ParadigmRotation(BaseStrategy):
    """动量 Top3 + 范式状态风格倾斜。

    overheat_map: 过热态时的候选池映射:
    - "defensive": 防御池（高切低）
    - "cyclical": 周期池（美林时钟式：过热期周期占优）
    - "anti_crowd": 全池 + 反拥挤加权
    """

    def __init__(
        self,
        *,
        top_k: int = 3,
        rebalance_period: int = 10,
        score_column: str = "ind_momentum",
        panic_thr: float = 65.0,
        overheat_thr: float = 65.0,
        overheat_map: str = "defensive",
        **kwargs,
    ) -> None:
        super().__init__(None)
        self.top_k = max(int(top_k), 1)
        self.rebalance_period = max(int(rebalance_period), 1)
        self.score_column = score_column
        self.panic_thr = float(panic_thr)
        self.overheat_thr = float(overheat_thr)
        self.overheat_map = overheat_map
        self.current_weights: dict[str, float] = {}
        self._bar_count = 0
        self.state_counts: dict[str, int] = {}

    def on_init(self) -> None:
        self.current_weights = {}
        self._bar_count = 0
        self.state_counts = {}

    def _state(self, latest: pl.DataFrame) -> str:
        def _get(col: str, default: float) -> float:
            return (
                float(latest[col][0])
                if col in latest.columns and latest[col][0] is not None
                else default
            )

        panic = _get("panic_index", 50.0)
        overheat = _get("overheat_index", 50.0)
        if panic > self.panic_thr:
            return "panic"
        if overheat > self.overheat_thr and panic < 50.0:
            return "overheat"
        return "normal"

    def _pool(self, state: str) -> set[str] | None:
        """返回状态对应的候选池（None = 全池）。"""
        if state == "panic":
            return _DEFENSIVE
        if state == "overheat":
            if self.overheat_map == "defensive":
                return _DEFENSIVE
            if self.overheat_map == "cyclical":
                return _CYCLICAL
        return None

    def on_bar(self, data: pl.DataFrame) -> list[Signal]:
        if data.is_empty():
            return []
        latest_date = data["trade_date"].max()
        if latest_date is None:
            return []

        self._bar_count += 1
        if self._bar_count > 1 and (self._bar_count - 1) % self.rebalance_period != 0:
            return []

        latest = data.filter(pl.col("trade_date") == latest_date)
        if latest.is_empty() or self.score_column not in latest.columns:
            return []

        state = self._state(latest)
        self.state_counts[state] = self.state_counts.get(state, 0) + 1

        cand = latest
        pool = self._pool(state)
        if pool is not None:
            cand = cand.filter(pl.col("industry_code").is_in(list(pool)))

        # 过热 + anti_crowd：动量与反拥挤加权
        if (
            state == "overheat"
            and self.overheat_map == "anti_crowd"
            and "tcr_percentile" in cand.columns
        ):
            ranked = (
                cand.select(
                    [
                        "trade_date",
                        "industry_code",
                        "industry_name",
                        self.score_column,
                        "tcr_percentile",
                    ]
                )
                .drop_nulls(subset=[self.score_column])
                .with_columns(
                    (
                        pl.col(self.score_column).rank(method="average").over("trade_date")
                        / pl.col(self.score_column).count().over("trade_date")
                        * 100.0
                    ).alias("mom_pct")
                )
                .with_columns(
                    (
                        0.5 * pl.col("mom_pct")
                        + 0.5 * (100.0 - pl.col("tcr_percentile").fill_null(50.0))
                    ).alias("score")
                )
                .sort("score", descending=True)
            )
        else:
            ranked = (
                cand.select(["trade_date", "industry_code", "industry_name", self.score_column])
                .drop_nulls(subset=[self.score_column])
                .sort(self.score_column, descending=True)
            )

        if ranked.is_empty():
            return []
        top = ranked.head(self.top_k).to_dicts()
        new_weights: dict[str, float] = {}
        signals: list[Signal] = []
        ts = latest_date
        for row in top:
            code = str(row["industry_code"])
            new_weights[code] = round(1.0 / len(top), 4)
            if code not in self.current_weights or self.current_weights[code] != new_weights[code]:
                signals.append(
                    Signal(
                        symbol=code,
                        direction=SignalDirection.BUY,
                        target_weight=new_weights[code],
                        reason=f"{state}态Top{self.top_k}: {row['industry_name']}",
                        timestamp=ts,
                    )
                )
        for old in self.current_weights:
            if old not in new_weights:
                signals.append(
                    Signal(
                        symbol=old,
                        direction=SignalDirection.CLOSE,
                        target_weight=0.0,
                        reason="范式调仓剔除",
                        timestamp=ts,
                    )
                )
        self.current_weights = new_weights
        return signals


def main() -> None:
    catalog = DataCatalog(data_source="tushare")
    panel = assemble_industry_panel(
        catalog=catalog, factor_root="data/analytics/industry_structure"
    )
    price_panel = load_industry_price_panel(catalog=catalog)
    if "trade_date" not in panel.columns and "as_of_date" in panel.columns:
        panel = panel.rename({"as_of_date": "trade_date"})

    rf = pl.read_parquet("data/analytics/macro_risk/latest/risk_factors.parquet").select(
        ["trade_date", "panic_index", "overheat_index"]
    )
    panel = panel.join(rf, on="trade_date", how="left")
    pn = pl.read_parquet("data/curated/mart/industry_panel_daily.parquet").select(
        [pl.col("as_of_date").alias("trade_date"), "industry_code", "tcr_percentile"]
    )
    panel = panel.join(pn, on=["trade_date", "industry_code"], how="left")

    variants = [
        ("baseline_全池动量", dict(panic_thr=99.0, overheat_thr=99.0)),
        ("范式A_恐慌切防御", dict(panic_thr=65.0, overheat_thr=99.0)),
        (
            "范式B_恐慌+过热都切防御",
            dict(panic_thr=65.0, overheat_thr=65.0, overheat_map="defensive"),
        ),
        (
            "范式C_恐慌防御+过热周期",
            dict(panic_thr=65.0, overheat_thr=65.0, overheat_map="cyclical"),
        ),
        (
            "范式D_恐慌防御+过热反拥挤",
            dict(panic_thr=65.0, overheat_thr=65.0, overheat_map="anti_crowd"),
        ),
    ]
    rows: list[dict] = []
    nav_map: dict[str, pl.DataFrame] = {}
    state_info: dict[str, dict[str, int]] = {}
    for name, kw in variants:
        strat = ParadigmRotation(rebalance_period=10, score_column="ind_momentum", **kw)
        runner = IndustryStrategyRunner(
            strat,
            strategy_name=name,
            commission_rate=0.0001,
            slippage_rate=0.0005,
            rebalance_deadband=0.03,
        )
        nav = runner.backtest(panel, price_panel)
        nav_map[name] = nav
        state_info[name] = dict(strat.state_counts)
        rows.append({"strategy": name, "区间": "全周期", **_metrics(nav)})
        oos = nav.filter(pl.col("trade_date") >= date(2022, 1, 1))
        rows.append({"strategy": name, "区间": "样本外2022后", **_metrics(oos)})

    result = pl.DataFrame(rows)
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    result.write_csv(_OUT_DIR / "industry_paradigm_rotation.csv")
    print(
        result.select(
            [
                "strategy",
                "区间",
                pl.col("cagr").round(2),
                pl.col("max_drawdown").round(2),
                pl.col("sharpe").round(2),
                pl.col("calmar").round(2),
            ]
        )
    )
    print("\n状态分布（调仓日计数）:")
    for name, cnt in state_info.items():
        print(f"  {name}: {cnt}")

    md = """# 行业轮动「宏观范式相态」实证（状态 × 风格倾斜）

> 日期：2026-08-31
> 背景：v1/v2（regime_timing）证明 panic/overheat 阈值**二值空仓**样本外无效（panic 滞后、
> overheat 牛市误触发）。本实证换机制：状态切换**行业候选池（风格倾斜）**而非空仓——
> 恐慌态切防御红利池、过热态按变体映射（防御/周期/反拥挤）、常态全池动量 Top3。
> 口径：双周（10 交易日）调仓、T+1、佣金万一 + 滑点万五 + 3% 死区，样本外 2022 后，
> CAGR 段内首值归一化。

## 1. 结果

| 策略 | 区间 | CAGR% | MaxDD% | Sharpe | Calmar |
| :--- | :--- | ---: | ---: | ---: | ---: |
"""
    for r in result.select(
        ["strategy", "区间", "cagr", "max_drawdown", "sharpe", "calmar"]
    ).to_dicts():
        md += (
            f"| {r['strategy']} | {r['区间']} | {r['cagr']:.2f} | {r['max_drawdown']:.2f} "
            f"| {r['sharpe']:.2f} | {r['calmar']:.2f} |\n"
        )
    md += """
## 2. 结论（实测）

- 风格倾斜（不空仓）能否突破 baseline 0.35 的样本外 Sharpe；
- 恐慌/过热态切换防御/周期/反拥挤，哪个风格映射在样本外有效；
- 若仍无效：证明范式风格切换在 10D 动量骨架上同样不增超额，瓶颈确在动量因子本身。
"""
    (_OUT_DIR / "industry_paradigm_rotation.md").write_text(md, encoding="utf-8")
    print(f"\n已写入: {_OUT_DIR / 'industry_paradigm_rotation.csv'} / .md")


if __name__ == "__main__":
    main()
