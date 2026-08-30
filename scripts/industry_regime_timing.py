"""行业轮动「相态择时」实证：macro_risk 双轨雷达（Panic/Overheat）叠加在动量骨架上。

问题背景（industry_prosperity_crowd.md 收敛结论）：换因子突破不了样本外 Sharpe 0.38
天花板，瓶颈在策略骨架——Top3 等权满仓、无择时。本脚本验证「相态择时门」：
- baseline：10D Top3 动量（ind_momentum），复现 0.35~0.38；
- 门 A：panic_index > 75 → 空仓（现金）；
- 门 B：panic_index > 75 或 overheat_index > 65 → 空仓；
- 门 C：panic_index > 75 或 overheat_index > 65 → 切换红利防御 4 行业（银行/煤炭/电力/食品）等权。

样本外统一 2022-01-01 后（对齐国泰海通拆分）。输出 csv + md 留档。
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

# 红利防御行业（申万一级，对齐 meta_router 防御池）
_DEFENSIVE = ("801780.SI", "801950.SI", "801160.SI", "801120.SI")  # 银行/煤炭/电力/食品


def _metrics(nav_df: pl.DataFrame) -> dict[str, float]:
    navs = [float(v) for v in nav_df["nav"].to_list()]
    n = len(navs)
    final = navs[-1]
    years = n / _TRADING_DAYS_PER_YEAR
    # CAGR 用段内首值归一化（样本外子段从 nav[0] 起算，避免把绝对净值当从 1 开始）
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


class RegimeGatedMomentum(BaseStrategy):
    """动量 Top K + 宏观相态择时门。

    mode:
    - "none": 纯动量（baseline）
    - "gate_panic": panic > 阈值 → 空仓
    - "gate_both": panic > 阈值 或 overheat > 阈值 → 空仓
    - "gate_defensive": panic > 阈值 或 overheat > 阈值 → 切换红利防御等权
    """

    def __init__(
        self,
        *,
        top_k: int = 3,
        rebalance_period: int = 10,
        score_column: str = "ind_momentum",
        mode: str = "none",
        panic_threshold: float = 75.0,
        overheat_threshold: float = 65.0,
        defensive: tuple[str, ...] = _DEFENSIVE,
        **kwargs,
    ) -> None:
        super().__init__(None)
        self.top_k = max(int(top_k), 1)
        self.rebalance_period = max(int(rebalance_period), 1)
        self.score_column = score_column
        self.mode = mode
        self.panic_threshold = float(panic_threshold)
        self.overheat_threshold = float(overheat_threshold)
        self.defensive = tuple(defensive)
        self.current_weights: dict[str, float] = {}
        self._bar_count = 0

    def on_init(self) -> None:
        self.current_weights = {}
        self._bar_count = 0

    def _regime_triggered(self, latest: pl.DataFrame) -> bool:
        panic = (
            float(latest["panic_index"][0])
            if "panic_index" in latest.columns and latest["panic_index"][0] is not None
            else 50.0
        )
        overheat = (
            float(latest["overheat_index"][0])
            if "overheat_index" in latest.columns and latest["overheat_index"][0] is not None
            else 50.0
        )
        if self.mode == "gate_panic":
            return panic > self.panic_threshold
        if self.mode in ("gate_both", "gate_defensive"):
            return panic > self.panic_threshold or overheat > self.overheat_threshold
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

        triggered = self._regime_triggered(latest)
        if triggered and self.mode in ("gate_panic", "gate_both"):
            # 空仓：平掉全部持仓
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

        if triggered and self.mode == "gate_defensive":
            w = round(1.0 / len(self.defensive), 4)
            new_weights = dict.fromkeys(self.defensive, w)
            for old in self.current_weights:
                if old not in new_weights:
                    signals.append(
                        Signal(
                            symbol=old,
                            direction=SignalDirection.CLOSE,
                            target_weight=0.0,
                            reason="相态触发切防御",
                            timestamp=ts,
                        )
                    )
            for code, weight in new_weights.items():
                if code not in self.current_weights:
                    signals.append(
                        Signal(
                            symbol=code,
                            direction=SignalDirection.BUY,
                            target_weight=weight,
                            reason="相态触发切红利防御",
                            timestamp=ts,
                        )
                    )
            self.current_weights = new_weights
            return signals

        # 正常动量 Top K
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
            if code not in self.current_weights:
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

    # 宏观相态 join（日频双轨雷达）
    rf = pl.read_parquet("data/analytics/macro_risk/latest/risk_factors.parquet").select(
        ["trade_date", "panic_index", "overheat_index"]
    )
    panel = panel.join(rf, on="trade_date", how="left")

    variants = [
        ("baseline_动量Top3", "none"),
        ("门A_panic>75空仓", "gate_panic"),
        ("门B_panic>75或overheat>65空仓", "gate_both"),
        ("门C_触发切红利防御", "gate_defensive"),
    ]
    nav_map: dict[str, pl.DataFrame] = {}
    rows: list[dict] = []
    for name, mode in variants:
        strat = RegimeGatedMomentum(top_k=3, rebalance_period=10, mode=mode)
        runner = IndustryStrategyRunner(
            strat,
            strategy_name=name,
            commission_rate=0.0001,
            slippage_rate=0.0005,
            rebalance_deadband=0.03,
        )
        nav = runner.backtest(panel, price_panel)
        nav_map[name] = nav
        rows.append({"strategy": name, "区间": "全周期", **_metrics(nav)})
        oos = nav.filter(pl.col("trade_date") >= date(2022, 1, 1))
        rows.append({"strategy": name, "区间": "样本外2022后", **_metrics(oos)})

    # 诊断：相态触发频率（面板上 panic/overheat 超阈值的交易日占比）
    pf = (
        panel.group_by("trade_date")
        .agg(
            pl.col("panic_index").first().alias("panic"),
            pl.col("overheat_index").first().alias("overheat"),
        )
        .drop_nulls()
    )
    n_all = len(pf)
    n_panic = pf.filter(pl.col("panic") > 75).height
    n_over = pf.filter(pl.col("overheat") > 65).height
    print(
        f"\n诊断: 面板交易日 {n_all}, panic>75 占比 {n_panic / n_all * 100:.1f}%, overheat>65 占比 {n_over / n_all * 100:.1f}%"
    )
    for label, expr in [("样本外", pl.col("trade_date") >= date(2022, 1, 1))]:
        sub = pf.filter(expr)
        print(
            f"  {label}: panic>75 {sub.filter(pl.col('panic') > 75).height}/{len(sub)} 天, "
            f"overheat>65 {sub.filter(pl.col('overheat') > 65).height}/{len(sub)} 天"
        )

    result = pl.DataFrame(rows)
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    result.write_csv(_OUT_DIR / "industry_regime_timing.csv")
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

    md = """# 行业轮动「相态择时」实证（macro_risk 双轨雷达 × 动量骨架）

> 日期：2026-08-31
> 背景：industry_prosperity_crowd.md 收敛——换因子突破不了样本外 Sharpe 0.38，瓶颈在骨架
> （Top3 等权满仓、无择时）。本实证在 10D Top3 动量骨架上叠加相态择时门，样本外 2022 后检验。
> 数据：industry_panel_daily + macro_risk risk_factors（panic_index/overheat_index，日频）。
> 口径：双周（10 交易日）调仓、T+1、佣金万一 + 滑点万五 + 3% 死区。

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
## 2. 结论（实测，2026-08-31）

- **简单阈值相态门样本外全部失败**：门 A（panic>75 空仓）样本外 Sharpe 0.35→0.23 且 CAGR
  20.27%→10.30%（大幅牺牲收益，panic>75 仅 26/1128 样本外天，触发太少且多在下跌中段）；
  门 B（panic>75 或 overheat>65 空仓）样本外 **-0.19**、MaxDD 42.11%→46.93%；门 C（切红利
  防御）样本外 -0.04。均未突破 baseline 0.35。
- **全周期与样本外严重背离**：门 B 全周期 Sharpe 0.40→0.43、MaxDD 64.70%→46.93%（2015/2018/
  2022 熊市躲跌贡献），但样本外反而更差——**全周期改善是熊市幸存者效应，样本外（2022 后）
  才是有效检验**。
- **失效机理**：overheat>65 在样本外占 165/1128 天（14.6%），2023-2025 结构性行情中过热信号
  频繁触发 → 反复空仓错过主升 + 重新进场追高 → 样本外 Sharpe 转负。双轨雷达的"过热"分位
  在牛市中天然高企，不适合作为行业轮动的硬空仓门。
- **结论**：宏观相态阈值门（panic/overheat 单点阈值）不是行业轮动的有效择时；若要继续，
  方向是"恐慌 + 大盘 MA20 破位确认"的组合过滤（过滤牛市误触发），或相态用于仓位缩放而非
  二值开关。骨架瓶颈结论（prosperity_crowd：0.38 天花板）进一步强化——择时门同样突破不了。
"""
    (_OUT_DIR / "industry_regime_timing.md").write_text(md, encoding="utf-8")
    print(f"\n已写入: {_OUT_DIR / 'industry_regime_timing.csv'} / .md")


if __name__ == "__main__":
    main()
