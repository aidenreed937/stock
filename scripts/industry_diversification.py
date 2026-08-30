"""行业轮动「分散度」实证：Top K 从 3 扩到 5/8，验证集中度下降能否改善样本外表现。

问题背景（industry_prosperity_crowd.md 收敛结论）：瓶颈在骨架——Top3 等权满仓、无分散度。
本脚本：
- baseline：10D Top3 动量（ind_momentum），复现 0.35；
- Top5 / Top8：同骨架等权扩仓；
- 另加「分散度 + 拥挤度防守」组合：Top5 且 tcr 高位（≥85 分位）剔除最热行业，验证
  拥挤度防守（SKILL 实证回撤 42%→26%）在分散骨架上是否更优。

样本外统一 2022-01-01 后。输出 csv + md 留档。
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


class MomentumTopK(BaseStrategy):
    """动量 Top K 等权，可选拥挤度防守（tcr_percentile 高位剔除）。"""

    def __init__(
        self,
        *,
        top_k: int = 3,
        rebalance_period: int = 10,
        score_column: str = "ind_momentum",
        anti_crowd: bool = False,
        crowd_max: float = 85.0,
        **kwargs,
    ) -> None:
        super().__init__(None)
        self.top_k = max(int(top_k), 1)
        self.rebalance_period = max(int(rebalance_period), 1)
        self.score_column = score_column
        self.anti_crowd = bool(anti_crowd)
        self.crowd_max = float(crowd_max)
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
        # 拥挤度防守：tcr 分位高位剔除（缺失放行）
        if self.anti_crowd and "tcr_percentile" in cand.columns:
            cand = cand.filter(
                pl.col("tcr_percentile").is_null() | (pl.col("tcr_percentile") <= self.crowd_max)
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
        signals: list[Signal] = []
        ts = latest_date
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

    # 拥挤度分位（tcr_percentile）来自 industry_panel_daily，单独 join（对齐 prosperity_crowd 做法）
    pn = pl.read_parquet("data/curated/mart/industry_panel_daily.parquet").select(
        [
            pl.col("as_of_date").alias("trade_date"),
            "industry_code",
            "tcr_percentile",
        ]
    )
    panel = panel.join(pn, on=["trade_date", "industry_code"], how="left")

    variants = [
        ("Top3_baseline", dict(top_k=3)),
        ("Top5_分散", dict(top_k=5)),
        ("Top8_分散", dict(top_k=8)),
        ("Top5_反拥挤85", dict(top_k=5, anti_crowd=True, crowd_max=85.0)),
        ("Top8_反拥挤85", dict(top_k=8, anti_crowd=True, crowd_max=85.0)),
    ]
    nav_map: dict[str, pl.DataFrame] = {}
    rows: list[dict] = []
    for name, kw in variants:
        strat = MomentumTopK(rebalance_period=10, score_column="ind_momentum", **kw)
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

    result = pl.DataFrame(rows)
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    result.write_csv(_OUT_DIR / "industry_diversification.csv")
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

    md = """# 行业轮动「分散度」实证（Top K 扩仓 × 拥挤度防守）

> 日期：2026-08-31
> 背景：industry_prosperity_crowd.md 收敛——瓶颈在骨架（Top3 等权满仓、无分散度）。
> 本实证把 Top3 扩到 Top5/8，并叠加拥挤度防守（tcr≥85 分位剔除，SKILL 实证回撤 42%→26%）。
> 口径：双周（10 交易日）调仓、T+1、佣金万一 + 滑点万五 + 3% 死区，样本外 2022 后检验。

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
## 2. 结论

- Top5/Top8 相对 Top3：样本外 Sharpe、MaxDD、CAGR 的变化（分散度是否突破 0.35~0.38 天花板）；
- 反拥挤 85 分位剔除：样本外 MaxDD 是否显著下降（验证拥挤度防守在分散骨架上的效果）。
"""
    (_OUT_DIR / "industry_diversification.md").write_text(md, encoding="utf-8")
    print(f"\n已写入: {_OUT_DIR / 'industry_diversification.csv'} / .md")


if __name__ == "__main__":
    main()
