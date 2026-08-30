"""L2 方向池「资本开支先导」实证：capex 特征的预测力检验 + 产能洪峰防守门回测。

背景：用户供需失衡框架第 1 维（资本开支/在建工程先导）。IC 检验发现 capex_growth_ttm /
cip_to_fa_ratio / fix_assets_yoy 与未来收益显著负相关（资本开支高速扩张 → 未来 1-2 年供给
过剩 → 收益差）。本脚本在 L2 方向池基线（return_60d Top3 + pe5y<=90）上叠加产能防守门：
- 门 A：capex_growth_ttm > 60 → 剔除（激进扩产）
- 门 B：cip_to_fa_ratio > 0.5 → 剔除（在建/固资比高 = 产能洪峰）
- 门 C：capex_growth_ttm > 60 或 fix_assets_yoy > 40 → 剔除（组合）
- 门 D：capex_growth_ttm < 20 → 动量加分 +10（供给克制 → 紧缺预期）

基线 CAGR 12.50%（样本外 0.15 Sharpe）。CAGR 段内归一化，样本外 2022 后。
"""

from __future__ import annotations

from datetime import date
from math import sqrt
from pathlib import Path

import polars as pl

from stock_cli.industry_trend_strategy import load_l2_panel, load_l2_price_panel
from stock_strategy.base import BaseStrategy
from stock_strategy.industry.runner import IndustryStrategyRunner
from stock_strategy.signal import Signal, SignalDirection

_TRADING_DAYS_PER_YEAR = 252.0
_OUT_DIR = Path("data/analytics/industry_strategy")


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


class L2CapexGateStrategy(BaseStrategy):
    """L2 方向池动量 Top3 + 估值防守 + 可选资本开支防守门。"""

    def __init__(
        self,
        *,
        top_k: int = 3,
        rebalance_period: int = 63,
        score_column: str = "return_60d",
        valuation_max: float = 90.0,
        capex_gate: str = "none",  # none / capex_high / cip_fa_high / combo / capex_low_bonus
        **kwargs,
    ) -> None:
        super().__init__(None)
        self.top_k = max(int(top_k), 1)
        self.rebalance_period = max(int(rebalance_period), 1)
        self.score_column = score_column
        self.valuation_max = float(valuation_max)
        self.capex_gate = capex_gate
        self.current_weights: dict[str, float] = {}
        self._bar_count = 0

    def on_init(self) -> None:
        self.current_weights = {}
        self._bar_count = 0

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

        cand = latest
        if "pe_ttm_ew_percentile_5y" in cand.columns:
            cand = cand.filter(
                pl.col("pe_ttm_ew_percentile_5y").is_null()
                | (pl.col("pe_ttm_ew_percentile_5y") <= self.valuation_max)
            )
        # 资本开支防守门（缺失放行）
        if self.capex_gate == "capex_high" and "capex_growth_ttm" in cand.columns:
            cand = cand.filter(
                pl.col("capex_growth_ttm").is_null() | (pl.col("capex_growth_ttm") <= 60.0)
            )
        elif self.capex_gate == "cip_fa_high" and "cip_to_fa_ratio" in cand.columns:
            cand = cand.filter(
                pl.col("cip_to_fa_ratio").is_null() | (pl.col("cip_to_fa_ratio") <= 0.5)
            )
        elif self.capex_gate == "combo" and "capex_growth_ttm" in cand.columns:
            cand = cand.filter(
                pl.col("capex_growth_ttm").is_null()
                | (
                    (pl.col("capex_growth_ttm") <= 60.0)
                    & (pl.col("fix_assets_yoy").is_null() | (pl.col("fix_assets_yoy") <= 40.0))
                )
            )

        ranked = (
            cand.select(["industry_code", "industry_name", self.score_column, "capex_growth_ttm"])
            .drop_nulls(subset=[self.score_column])
            .with_columns(
                pl.when(
                    (self.capex_gate == "capex_low_bonus")
                    & pl.col("capex_growth_ttm").is_not_null()
                    & (pl.col("capex_growth_ttm") < 20.0)
                )
                .then(pl.col(self.score_column) + 10.0)
                .otherwise(pl.col(self.score_column))
                .alias("score")
            )
            .sort("score", descending=True)
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
            if code not in self.current_weights:
                signals.append(
                    Signal(symbol=code, direction=SignalDirection.BUY, target_weight=new_weights[code],
                           reason=f"Top{self.top_k}: {row['industry_name']}", timestamp=ts)
                )
        for old in self.current_weights:
            if old not in new_weights:
                signals.append(
                    Signal(symbol=old, direction=SignalDirection.CLOSE, target_weight=0.0,
                           reason="调仓剔除", timestamp=ts)
                )
        self.current_weights = new_weights
        return signals


def main() -> None:
    panel = load_l2_panel()
    price = load_l2_price_panel()

    variants = [
        ("baseline_动量Top3+估值防守", "none"),
        ("门A_capex增速>60剔除", "capex_high"),
        ("门B_在建固资比>0.5剔除", "cip_fa_high"),
        ("门C_capex或固资增速组合剔除", "combo"),
        ("门D_capex增速<20动量加分+10", "capex_low_bonus"),
    ]
    rows: list[dict] = []
    nav_map: dict[str, pl.DataFrame] = {}
    for name, gate in variants:
        strat = L2CapexGateStrategy(rebalance_period=63, score_column="return_60d", capex_gate=gate)
        runner = IndustryStrategyRunner(
            strat, strategy_name=name, commission_rate=0.0001, slippage_rate=0.0005,
            rebalance_deadband=0.03,
        )
        nav = runner.backtest(panel, price)
        nav_map[name] = nav
        rows.append({"strategy": name, "区间": "全周期", **_metrics(nav)})
        oos = nav.filter(pl.col("trade_date") >= date(2022, 1, 1))
        rows.append({"strategy": name, "区间": "样本外2022后", **_metrics(oos)})

    result = pl.DataFrame(rows)
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    result.write_csv(_OUT_DIR / "industry_capex_leading.csv")
    print(
        result.select(
            ["strategy", "区间", pl.col("cagr").round(2), pl.col("max_drawdown").round(2),
             pl.col("sharpe").round(2), pl.col("calmar").round(2)]
        )
    )

    md = """# L2 方向池「资本开支先导」实证（供需失衡第 1 维）

> 日期：2026-08-31
> 背景：用户供需失衡先导框架第 1 维（资本开支/在建工程）。IC 检验（2026-08，无前视）：
> capex_growth_ttm / cip_to_fa_ratio / fix_assets_yoy 与未来收益**显著负相关**——
> 资本开支高速扩张是未来 1-2 年供给过剩（产能洪峰）的先导。本实证在 L2 方向池基线
> （return_60d Top3 + pe5y<=90）上叠加产能防守门，样本外 2022 后检验。

## 1. IC 与分位收益（13 方向池，2020-05 起）

| 特征 | IC20 | IC20样本外 | IC60 | IC60样本外 | 低组fwd60 | 高组fwd60 |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| capex_growth_ttm | -6.74% | -5.53% | **-8.62%** | -5.05% | +2.56% | **+1.52%** |
| cip_to_fa_ratio | -2.16% | -1.70% | -4.78% | -4.78% | +3.86% | **+1.88%** |
| fix_assets_yoy | -2.49% | -6.47% | -3.84% | -8.69% | +3.40% | +4.60% |
| cip_yoy | +1.64% | +2.08% | +2.46% | +4.03% | +2.02% | +2.53% |
| inventory_scissors | +0.79% | +1.25% | -0.60% | +0.62% | +2.29% | +1.47% |

## 2. 防守门回测（季度调仓 Top3，T+1，万一佣金+万五滑点+3% 死区）

| 策略 | 区间 | CAGR% | MaxDD% | Sharpe | Calmar |
| :--- | :--- | ---: | ---: | ---: | ---: |
"""
    for r in result.select(["strategy", "区间", "cagr", "max_drawdown", "sharpe", "calmar"]).to_dicts():
        md += (
            f"| {r['strategy']} | {r['区间']} | {r['cagr']:.2f} | {r['max_drawdown']:.2f} "
            f"| {r['sharpe']:.2f} | {r['calmar']:.2f} |\n"
        )
    md += """
## 3. 结论（实测）

- 产能洪峰防守门（capex 高增速/在建固资比高剔除）相对 baseline 样本外 Sharpe/CAGR/MaxDD；
- capex 低位加分（供给克制 → 紧缺预期）是否优于防守门；
- 结合 IC 结论判断：资本开支先导在 L2 方向池适合做防守门还是进攻加分。
"""
    (_OUT_DIR / "industry_capex_leading.md").write_text(md, encoding="utf-8")
    print(f"\n已写入: {_OUT_DIR / 'industry_capex_leading.csv'} / .md")


if __name__ == "__main__":
    main()
