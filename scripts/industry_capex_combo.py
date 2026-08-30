"""L2 方向池「防守门组合」实证：capex 门 C × 拥挤度 × 恐慌降仓。

背景：capex 门 C（capex_growth_ttm>60 或 fix_assets_yoy>40 剔除）是首个样本外改善 baseline
的先导因子（0.15→0.22）。本脚本验证防守门组合能否进一步叠加：
- baseline：return_60d Top3 + pe5y<=90（季度 63 日调仓）
- 门C：+ capex 组合剔除
- 门C+拥挤：+ crowding_score >= 85 剔除（SKILL 拥挤度一票否决阈值）
- 门C+恐慌：+ panic>65 时持仓降仓 50%（L2 池无防御行业可切，用降仓）
- 门C+拥挤+恐慌：三合一

样本外 2022 后，CAGR 段内归一化。输出 csv + md。
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


class L2ComboGuardStrategy(BaseStrategy):
    """L2 方向池动量 Top3 + 估值防守 + 组合防守门。"""

    def __init__(
        self,
        *,
        top_k: int = 3,
        rebalance_period: int = 63,
        score_column: str = "return_60d",
        valuation_max: float = 90.0,
        capex_gate: bool = False,
        crowd_gate: bool = False,
        crowd_max: float = 85.0,
        panic_scale: float = 0.0,  # 0=不启用；>0 且 <1 = 恐慌时降仓比例
        panic_thr: float = 65.0,
        **kwargs,
    ) -> None:
        super().__init__(None)
        self.top_k = max(int(top_k), 1)
        self.rebalance_period = max(int(rebalance_period), 1)
        self.score_column = score_column
        self.valuation_max = float(valuation_max)
        self.capex_gate = bool(capex_gate)
        self.crowd_gate = bool(crowd_gate)
        self.crowd_max = float(crowd_max)
        self.panic_scale = float(panic_scale)
        self.panic_thr = float(panic_thr)
        self.current_weights: dict[str, float] = {}
        self._bar_count = 0

    def on_init(self) -> None:
        self.current_weights = {}
        self._bar_count = 0

    def _panic(self, latest: pl.DataFrame) -> float:
        if "panic_index" in latest.columns and latest["panic_index"][0] is not None:
            return float(latest["panic_index"][0])
        return 50.0

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

        signals: list[Signal] = []
        ts = latest_date

        # 恐慌降仓：仅调仓日检查（持仓按比例下调）
        if self.panic_scale > 0 and self.panic_scale < 1 and self._panic(latest) > self.panic_thr:
            new_weights = {c: w * self.panic_scale for c, w in self.current_weights.items()}
            for old in self.current_weights:
                signals.append(
                    Signal(symbol=old, direction=SignalDirection.BUY,
                           target_weight=new_weights[old], reason="恐慌降仓", timestamp=ts)
                )
            self.current_weights = new_weights
            return signals

        cand = latest
        if "pe_ttm_ew_percentile_5y" in cand.columns:
            cand = cand.filter(
                pl.col("pe_ttm_ew_percentile_5y").is_null()
                | (pl.col("pe_ttm_ew_percentile_5y") <= self.valuation_max)
            )
        # capex 门 C（缺失放行）
        if self.capex_gate and "capex_growth_ttm" in cand.columns:
            cand = cand.filter(
                pl.col("capex_growth_ttm").is_null()
                | (
                    (pl.col("capex_growth_ttm") <= 60.0)
                    & (pl.col("fix_assets_yoy").is_null() | (pl.col("fix_assets_yoy") <= 40.0))
                )
            )
        # 拥挤度门（crowding_score >= 阈值剔除，缺失放行）
        if self.crowd_gate and "crowding_score" in cand.columns:
            cand = cand.filter(
                pl.col("crowding_score").is_null() | (pl.col("crowding_score") < self.crowd_max)
            )

        ranked = (
            cand.select(["industry_code", "industry_name", self.score_column])
            .drop_nulls(subset=[self.score_column])
            .sort(self.score_column, descending=True)
        )
        if ranked.is_empty():
            return []
        top = ranked.head(self.top_k).to_dicts()
        new_weights: dict[str, float] = {}
        for row in top:
            code = str(row["industry_code"])
            new_weights[code] = round(1.0 / len(top), 4)
            if code not in self.current_weights or self.current_weights[code] != new_weights[code]:
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

    # join 宏观恐慌指数（risk_factors）
    rf = pl.read_parquet("data/analytics/macro_risk/latest/risk_factors.parquet").select(
        ["trade_date", "panic_index"]
    )
    panel = panel.join(rf, on="trade_date", how="left")

    variants = [
        ("baseline", dict()),
        ("门C_capex", dict(capex_gate=True)),
        ("门C+拥挤85", dict(capex_gate=True, crowd_gate=True)),
        ("门C+恐慌降仓50%", dict(capex_gate=True, panic_scale=0.5)),
        ("门C+拥挤+恐慌", dict(capex_gate=True, crowd_gate=True, panic_scale=0.5)),
        ("拥挤85单独", dict(crowd_gate=True)),
    ]
    rows: list[dict] = []
    nav_map: dict[str, pl.DataFrame] = {}
    for name, kw in variants:
        strat = L2ComboGuardStrategy(rebalance_period=63, score_column="return_60d", **kw)
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
    result.write_csv(_OUT_DIR / "industry_capex_combo.csv")
    print(
        result.select(
            ["strategy", "区间", pl.col("cagr").round(2), pl.col("max_drawdown").round(2),
             pl.col("sharpe").round(2), pl.col("calmar").round(2)]
        )
    )

    md = """# L2 方向池「防守门组合」实证（capex × 拥挤度 × 恐慌降仓）

> 日期：2026-08-31
> 背景：capex 门 C 是首个样本外改善 baseline 的先导因子（0.15→0.22）。本实证组合验证
> 三个防守门是否叠加：capex（capex_growth_ttm>60 或 fix_assets_yoy>40 剔除）、拥挤度
> （crowding_score>=85 剔除，SKILL 阈值）、恐慌降仓（panic>65 持仓降至 50%）。
> L2 方向池无一级防御行业可切，恐慌用降仓形式。样本外 2022 后，CAGR 段内归一化。

## 1. 结果

| 策略 | 区间 | CAGR% | MaxDD% | Sharpe | Calmar |
| :--- | :--- | ---: | ---: | ---: | ---: |
"""
    for r in result.select(["strategy", "区间", "cagr", "max_drawdown", "sharpe", "calmar"]).to_dicts():
        md += (
            f"| {r['strategy']} | {r['区间']} | {r['cagr']:.2f} | {r['max_drawdown']:.2f} "
            f"| {r['sharpe']:.2f} | {r['calmar']:.2f} |\n"
        )
    md += """
## 2. 结论（实测）

- 组合门相对门 C 单独：样本外 Sharpe/CAGR/MaxDD 是否进一步改善（叠加有效）还是抵消；
- 拥挤度、恐慌降仓在 L2 方向池的效果与一级池对比。
"""
    (_OUT_DIR / "industry_capex_combo.md").write_text(md, encoding="utf-8")
    print(f"\n已写入: {_OUT_DIR / 'industry_capex_combo.csv'} / .md")


if __name__ == "__main__":
    main()
