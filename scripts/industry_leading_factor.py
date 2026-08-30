"""行业轮动「先导因子叠加」实证：在 baseline 10D Top3 动量骨架上叠加三层共振因子。

背景：相态择时（regime_timing）与分散度（diversification）样本外均证伪——Top3 等权无改进
就是唯一有效骨架（样本外 Sharpe 0.35）。本脚本验证"先导因子"能否在**不动骨架**的前提下
叠加增益（此前 prosperity_crowd 已测业绩预告/反拥挤计分均 ≤0.35，未测方向分与量价齐升）：
- baseline：10D Top3 ind_momentum；
- 方向分防守门：direction_score > 66 且非量价齐升 → 剔除（对齐 L2 池 direction_gate，
  一级池未测过；方向分来自 global_resonance_map）；
- 量价齐升硬门：营收/净利 TTM 双正才入选；
- 量价齐升加分：动量 +10（对齐 L2 池 qlq_bonus）；
- 组合：量价齐升加分 + 反拥挤计分（100-tcr 加权）。

样本外统一 2022-01-01 后，CAGR 用段内首值归一化。输出 csv + md 留档。
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


class LeadingFactorTopK(BaseStrategy):
    """10D 动量 Top K + 可选先导因子。

    - direction_gate：direction_score > 阈值 且 非量价齐升 → 剔除（防守门）；
    - qlq_gate：仅量价齐升行业入选（硬门）；
    - qlq_bonus：量价齐升行业动量加分；
    - anti_crowd_weight：score = 0.5*动量 + 0.5*(100-tcr 分位)。
    """

    def __init__(
        self,
        *,
        top_k: int = 3,
        rebalance_period: int = 10,
        score_column: str = "ind_momentum",
        direction_gate: bool = False,
        direction_threshold: float = 66.0,
        qlq_gate: bool = False,
        qlq_bonus: float = 0.0,
        anti_crowd_weight: float = 0.0,
        **kwargs,
    ) -> None:
        super().__init__(None)
        self.top_k = max(int(top_k), 1)
        self.rebalance_period = max(int(rebalance_period), 1)
        self.score_column = score_column
        self.direction_gate = bool(direction_gate)
        self.direction_threshold = float(direction_threshold)
        self.qlq_gate = bool(qlq_gate)
        self.qlq_bonus = float(qlq_bonus)
        self.anti_crowd_weight = float(anti_crowd_weight)
        self.current_weights: dict[str, float] = {}
        self._bar_count = 0

    def on_init(self) -> None:
        self.current_weights = {}
        self._bar_count = 0

    def _qlq(self, latest: pl.DataFrame) -> pl.Series:
        return (pl.col("revenue_growth_ttm") > 0.0) & (pl.col("profit_growth_ttm") > 0.0)

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
        # 方向分防守门：高位 × 非量价齐升 → 剔除（对齐 L2 direction_gate）
        if self.direction_gate and "direction_score" in cand.columns:
            cand = cand.filter(
                ~((pl.col("direction_score") > self.direction_threshold) & (~self._qlq(cand)))
            )
        # 量价齐升硬门
        if self.qlq_gate:
            if "revenue_growth_ttm" not in cand.columns:
                return []
            cand = cand.filter(self._qlq(cand))

        ranked = (
            cand.select(
                [
                    "trade_date",
                    "industry_code",
                    "industry_name",
                    self.score_column,
                    "revenue_growth_ttm",
                    "profit_growth_ttm",
                ]
            )
            .drop_nulls(subset=[self.score_column])
            .with_columns(
                pl.when(self._qlq(cand))
                .then(pl.col(self.score_column) + self.qlq_bonus)
                .otherwise(pl.col(self.score_column))
                .alias("base")
            )
        )
        if ranked.is_empty():
            return []

        # 反拥挤计分（可选）：score = (1-w)*动量分位 + w*反拥挤分位
        if self.anti_crowd_weight > 0 and "tcr_percentile" in cand.columns:
            ranked = ranked.join(
                cand.select(["industry_code", "tcr_percentile"]), on="industry_code", how="left"
            )
            ranked = ranked.with_columns(
                (
                    pl.col("base").rank(method="average").over("trade_date")
                    / pl.col("base").count().over("trade_date")
                    * 100.0
                ).alias("mom_pct")
            ).with_columns(
                (
                    (1.0 - self.anti_crowd_weight) * pl.col("mom_pct")
                    + self.anti_crowd_weight * (100.0 - pl.col("tcr_percentile").fill_null(50.0))
                ).alias("score")
            )
        else:
            ranked = ranked.with_columns(pl.col("base").alias("score"))

        ranked = ranked.sort("score", descending=True)
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
                        reason=f"Top{self.top_k}: {row['industry_name']}",
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

    # join 量价齐升（revenue/profit_growth_ttm）与拥挤度分位（tcr_percentile）
    pn = pl.read_parquet("data/curated/mart/industry_panel_daily.parquet").select(
        [
            pl.col("as_of_date").alias("trade_date"),
            "industry_code",
            "revenue_growth_ttm",
            "profit_growth_ttm",
            "tcr_percentile",
        ]
    )
    panel = panel.join(pn, on=["trade_date", "industry_code"], how="left")

    # join 一级方向分（global_resonance_map，801xxx.SI 口径）
    gm = pl.read_parquet("data/curated/mart/global_resonance_map.parquet")
    panel = panel.join(gm, on=["trade_date", "industry_code"], how="left")

    variants = [
        ("baseline_Top3动量", dict()),
        ("方向防守门(dir>66×非量价齐升)", dict(direction_gate=True)),
        ("量价齐升硬门", dict(qlq_gate=True)),
        ("量价齐升加分+10", dict(qlq_bonus=10.0)),
        ("动量+反拥挤(0.5:0.5)", dict(anti_crowd_weight=0.5)),
        ("量价齐升加分+反拥挤", dict(qlq_bonus=10.0, anti_crowd_weight=0.5)),
    ]
    rows: list[dict] = []
    nav_map: dict[str, pl.DataFrame] = {}
    for name, kw in variants:
        strat = LeadingFactorTopK(rebalance_period=10, score_column="ind_momentum", **kw)
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
    result.write_csv(_OUT_DIR / "industry_leading_factor.csv")
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

    md = """# 行业轮动「先导因子叠加」实证（三层共振因子 × 不动骨架）

> 日期：2026-08-31
> 背景：相态择时（regime_timing）与分散度（diversification）样本外均证伪——Top3 等权无改进
> 是唯一有效骨架（样本外 Sharpe 0.35）。本实证在**不动骨架**前提下叠加先导因子，补齐此前
> 未测的方向分（一级池）与量价齐升（一级池）；业绩预告/反拥挤计分见 prosperity_crowd。
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

- 各先导因子相对 baseline 样本外 Sharpe/CAGR/MaxDD 变化；
- 能否突破 0.35~0.38 天花板：方向分防守门（一级池）、量价齐升门/加分、反拥挤组合。
"""
    (_OUT_DIR / "industry_leading_factor.md").write_text(md, encoding="utf-8")
    print(f"\n已写入: {_OUT_DIR / 'industry_leading_factor.csv'} / .md")


if __name__ == "__main__":
    main()
