"""行业轮动「相态择时 v2」：阈值扫描 × MA20 破位过滤 × 仓位缩放。

v1（industry_regime_timing.py）结论：单点阈值二值空仓样本外全失败——panic 滞后（2022 熊市
触发时已跌一段，空仓后错过反弹反而更差）、overheat 牛市误触发（2025/2026 空仓错过主升）。
本脚本验证更精细的择时形态能否在样本外（2022 后）改善：
- 阈值扫描：panic ∈ {60,70,75,80}、overheat ∈ {55,60,65,70}（门 A/B 结构）；
- MA20 破位过滤：overheat>阈值 且 大盘 close < MA20 才触发（牛市误触发过滤，对齐 meta_router
  相态 1 条件）；
- 仓位缩放：触发时降至 50% 仓位而非空仓（保留部分上行）。

大盘：000985.CSI index_daily_bar 计算 MA20。CAGR 段内首值归一化，样本外 2022 后检验。
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


class RegimeGatedV2(BaseStrategy):
    """动量 Top3 + 精细相态择时。

    mode:
    - "panic": panic > panic_thr → 空仓
    - "both": panic > panic_thr 或 overheat > overheat_thr → 空仓
    - "both_ma20": panic > panic_thr 或 (overheat > overheat_thr 且 close < ma20) → 空仓
    - "scale": panic > panic_thr 或 overheat > overheat_thr → 降至 scale 仓位
    """

    def __init__(
        self,
        *,
        top_k: int = 3,
        rebalance_period: int = 10,
        score_column: str = "ind_momentum",
        mode: str = "panic",
        panic_thr: float = 75.0,
        overheat_thr: float = 65.0,
        scale: float = 0.5,
        **kwargs,
    ) -> None:
        super().__init__(None)
        self.top_k = max(int(top_k), 1)
        self.rebalance_period = max(int(rebalance_period), 1)
        self.score_column = score_column
        self.mode = mode
        self.panic_thr = float(panic_thr)
        self.overheat_thr = float(overheat_thr)
        self.scale = float(scale)
        self.current_weights: dict[str, float] = {}
        self._bar_count = 0

    def on_init(self) -> None:
        self.current_weights = {}
        self._bar_count = 0

    def _triggered(self, latest: pl.DataFrame) -> bool:
        def _get(col: str, default: float) -> float:
            return (
                float(latest[col][0])
                if col in latest.columns and latest[col][0] is not None
                else default
            )

        panic = _get("panic_index", 50.0)
        overheat = _get("overheat_index", 50.0)
        close = _get("benchmark_close", 100.0)
        ma20 = _get("benchmark_ma20", close)
        if self.mode == "panic":
            return panic > self.panic_thr
        if self.mode == "both":
            return panic > self.panic_thr or overheat > self.overheat_thr
        if self.mode == "both_ma20":
            return panic > self.panic_thr or (overheat > self.overheat_thr and close < ma20)
        if self.mode == "scale":
            return panic > self.panic_thr or overheat > self.overheat_thr
        return False

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
        triggered = self._triggered(latest)

        # 择时动作：空仓（或缩放）
        if triggered:
            if self.mode == "scale":
                # 持仓降为 scale 倍（保留部分动量敞口）
                new_weights = {c: w * self.scale for c, w in self.current_weights.items()}
                for old in self.current_weights:
                    signals.append(
                        Signal(
                            symbol=old,
                            direction=SignalDirection.BUY,
                            target_weight=new_weights[old],
                            reason="相态触发降仓",
                            timestamp=ts,
                        )
                    )
                self.current_weights = new_weights
                return signals
            for old in self.current_weights:
                signals.append(
                    Signal(
                        symbol=old,
                        direction=SignalDirection.CLOSE,
                        target_weight=0.0,
                        reason="相态触发空仓",
                        timestamp=ts,
                    )
                )
            self.current_weights = {}
            return signals

        # 正常动量 Top3（若之前缩放，恢复满仓）
        ranked = (
            latest.select(["industry_code", "industry_name", self.score_column])
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
                    Signal(
                        symbol=code,
                        direction=SignalDirection.BUY,
                        target_weight=new_weights[code],
                        reason=f"动量Top{self.top_k}: {row['industry_name']}",
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
                        reason="动量调仓剔除",
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

    # 大盘 close/MA20（000985.CSI）→ 每个交易日一行，join 后广播到行业截面
    bars = (
        catalog.load_bars(symbol="000985.CSI", dataset="index_daily_bar")
        .select(["trade_date", "close"])
        .sort("trade_date")
    )
    bench = bars.with_columns(pl.col("close").rolling_mean(window_size=20).alias("ma20"))
    panel = panel.join(
        bench.rename({"close": "benchmark_close", "ma20": "benchmark_ma20"}),
        on="trade_date",
        how="left",
    )

    variants = [
        ("baseline", dict(mode="panic", panic_thr=99.0)),  # 永不触发
        ("panic>60", dict(mode="panic", panic_thr=60.0)),
        ("panic>70", dict(mode="panic", panic_thr=70.0)),
        ("panic>80", dict(mode="panic", panic_thr=80.0)),
        ("both_p75_o55", dict(mode="both", panic_thr=75.0, overheat_thr=55.0)),
        ("both_p75_o60", dict(mode="both", panic_thr=75.0, overheat_thr=60.0)),
        ("both_p75_o70", dict(mode="both", panic_thr=75.0, overheat_thr=70.0)),
        ("both_ma20_p75_o65", dict(mode="both_ma20", panic_thr=75.0, overheat_thr=65.0)),
        ("both_ma20_p75_o60", dict(mode="both_ma20", panic_thr=75.0, overheat_thr=60.0)),
        ("scale50_p75_o65", dict(mode="scale", panic_thr=75.0, overheat_thr=65.0)),
        ("scale50_p70_o60", dict(mode="scale", panic_thr=70.0, overheat_thr=60.0)),
    ]
    rows: list[dict] = []
    for name, kw in variants:
        strat = RegimeGatedV2(rebalance_period=10, score_column="ind_momentum", **kw)
        runner = IndustryStrategyRunner(
            strat,
            strategy_name=name,
            commission_rate=0.0001,
            slippage_rate=0.0005,
            rebalance_deadband=0.03,
        )
        nav = runner.backtest(panel, price_panel)
        rows.append({"strategy": name, "区间": "全周期", **_metrics(nav)})
        oos = nav.filter(pl.col("trade_date") >= date(2022, 1, 1))
        rows.append({"strategy": name, "区间": "样本外2022后", **_metrics(oos)})

    result = pl.DataFrame(rows)
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    result.write_csv(_OUT_DIR / "industry_regime_timing_v2.csv")
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

    md = """# 行业轮动「相态择时 v2」：阈值扫描 × MA20 破位过滤 × 仓位缩放

> 日期：2026-08-31
> 背景：v1（industry_regime_timing.md）单点阈值二值空仓样本外全失败——panic 滞后（2022 熊市
> 触发时已跌一段、空仓错过反弹）、overheat 牛市误触发（2025/2026 空仓错过主升）。
> 本实证扫描阈值、加大盘 MA20 破位过滤、试仓位缩放，样本外 2022 后检验，CAGR 段内归一化。

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

- 阈值扫描/MA20 过滤/仓位缩放能否在样本外改善 v1 的结论（择时无效）；
- 若 MA20 过滤有效：证明"牛市误触发"是 v1 失效主因，择时方向仍有价值。
"""
    (_OUT_DIR / "industry_regime_timing_v2.md").write_text(md, encoding="utf-8")
    print(f"\n已写入: {_OUT_DIR / 'industry_regime_timing_v2.csv'} / .md")


if __name__ == "__main__":
    main()
