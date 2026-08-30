"""产业趋势跟踪第二步：基本面转弱退出（景气环比转负即退出）。

在「季度 + 趋势确认（环比改善）」基础上，叠加日频监控：持有行业的景气环比一旦转负
（prosperity_mom < 0）立即清仓退出，避免景气见顶后死扛。对比三方案：
- 追高（绝对水平）
- 趋势确认（环比改善）
- 趋势确认 + 基本面转弱退出
"""

from __future__ import annotations

from datetime import date, datetime
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
from stock_strategy.pool.industry_momentum import IndustryMomentumRotationStrategy
from stock_strategy.signal import Signal, SignalDirection

_TRADING_DAYS_PER_YEAR = 252.0


def _cs_percentile(col: str) -> pl.Expr:
    return (
        (
            (pl.col(col).rank(method="average").over("trade_date") - 1.0)
            / (pl.col(col).count().over("trade_date") - 1.0)
            * 100.0
        )
        .fill_nan(50.0)
        .fill_null(50.0)
    )


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


class IndustryTrendExitStrategy(BaseStrategy):
    """季度趋势跟踪 + 日频基本面转弱退出。"""

    def __init__(
        self,
        context=None,
        *,
        top_k: int = 3,
        rebalance_period: int = 63,
        exit_threshold: float = 0.0,
        score_column: str = "prosperity_mom",
        exit_column: str = "prosperity_mom",
    ) -> None:
        super().__init__(context)
        self.top_k = max(int(top_k), 1)
        self.rebalance_period = max(int(rebalance_period), 1)
        self.exit_threshold = float(exit_threshold)
        self.score_column = score_column
        self.exit_column = exit_column
        self.weights: dict[str, float] = {}
        self._bar_count = 0

    def on_init(self) -> None:
        self.weights = {}
        self._bar_count = 0

    def on_bar(self, data: pl.DataFrame) -> list[Signal]:
        if data.is_empty():
            return []
        latest_date = data["trade_date"].max()
        latest = data.filter(pl.col("trade_date") == latest_date)
        if latest.is_empty():
            return []

        self._bar_count += 1
        signals: list[Signal] = []
        ts = latest_date if isinstance(latest_date, (date, datetime)) else None

        # 1. 日频基本面转弱退出：持有行业景气环比跌破阈值，立即清仓
        for code in list(self.weights.keys()):
            row = latest.filter(pl.col("industry_code") == code)
            if row.is_empty() or self.exit_column not in row.columns:
                continue
            mom = row[self.exit_column][0]
            mom_v = float(mom) if mom is not None else 0.0
            if mom_v < self.exit_threshold:
                signals.append(
                    Signal(
                        symbol=code,
                        direction=SignalDirection.CLOSE,
                        target_weight=0.0,
                        reason=f"基本面转弱退出 ({self.exit_column}={mom_v:.1f} < {self.exit_threshold:.1f})",
                        timestamp=ts,
                    )
                )
                del self.weights[code]

        # 2. 季度调仓：按 score_column（环比改善）选 Top K
        if self._bar_count > 1 and (self._bar_count - 1) % self.rebalance_period != 0:
            return signals

        ranked = (
            latest.select(["industry_code", "industry_name", self.score_column])
            .drop_nulls(subset=[self.score_column])
            .sort(self.score_column, descending=True)
        )
        top_rows = ranked.head(self.top_k).to_dicts()
        new_weights: dict[str, float] = {}
        if top_rows:
            w = round(1.0 / len(top_rows), 4)
            for row in top_rows:
                code = str(row["industry_code"])
                new_weights[code] = w
                if code not in self.weights:
                    signals.append(
                        Signal(
                            symbol=code,
                            direction=SignalDirection.BUY,
                            target_weight=w,
                            reason=f"季度趋势建仓 ({self.score_column}={float(row[self.score_column]):.1f})",
                            timestamp=ts,
                        )
                    )

        for code in list(self.weights.keys()):
            if code not in new_weights:
                signals.append(
                    Signal(
                        symbol=code,
                        direction=SignalDirection.CLOSE,
                        target_weight=0.0,
                        reason="季度调仓剔除",
                        timestamp=ts,
                    )
                )
        self.weights = new_weights
        return signals


def main() -> None:
    catalog = DataCatalog(data_source="tushare")
    panel = assemble_industry_panel(
        catalog=catalog, factor_root="data/analytics/industry_structure"
    )
    price_panel = load_industry_price_panel(catalog=catalog)

    p = (
        pl.read_parquet("data/curated/mart/industry_panel_daily.parquet")
        .select(
            [
                "as_of_date",
                "industry_code",
                "forecast_positive_share",
                "express_profit_growth_median",
            ]
        )
        .rename({"as_of_date": "trade_date"})
    )
    p = p.with_columns(
        [
            _cs_percentile("forecast_positive_share").alias("fc"),
            _cs_percentile("express_profit_growth_median").alias("ex"),
        ]
    )
    p = p.select(["trade_date", "industry_code", "fc", "ex"])
    panel = panel.join(p, on=["trade_date", "industry_code"], how="left")
    panel = panel.with_columns(
        ((pl.col("fc") + pl.col("ex") + (100.0 - pl.col("ind_crowding"))) / 3.0).alias(
            "prosperity_ac"
        )
    )
    panel = (
        panel.sort(["industry_code", "trade_date"])
        .with_columns(
            (
                pl.col("prosperity_ac") - pl.col("prosperity_ac").shift(63).over("industry_code")
            ).alias("prosperity_mom")
        )
        .sort(["trade_date", "industry_code"])
    )

    nav_map: dict[str, pl.DataFrame] = {}

    # baseline：追高（绝对水平）
    s1 = IndustryMomentumRotationStrategy(
        top_k=3, rebalance_period=63, score_column="prosperity_ac"
    )
    nav_map["追高(绝对水平)"] = IndustryStrategyRunner(
        s1, commission_rate=0.0001, slippage_rate=0.0005, rebalance_deadband=0.03
    ).backtest(panel, price_panel)

    # 趋势确认（环比改善）
    s2 = IndustryMomentumRotationStrategy(
        top_k=3, rebalance_period=63, score_column="prosperity_mom"
    )
    nav_map["趋势确认(环比)"] = IndustryStrategyRunner(
        s2, commission_rate=0.0001, slippage_rate=0.0005, rebalance_deadband=0.03
    ).backtest(panel, price_panel)

    # 趋势确认 + 基本面转弱退出
    s3 = IndustryTrendExitStrategy(top_k=3, rebalance_period=63, exit_threshold=0.0)
    nav_map["趋势+转弱退出"] = IndustryStrategyRunner(
        s3, commission_rate=0.0001, slippage_rate=0.0005, rebalance_deadband=0.03
    ).backtest(panel, price_panel)

    rows = []
    for name, nav in nav_map.items():
        rows.append({"strategy": name, **_metrics(nav)})
    result = pl.DataFrame(rows)
    out = Path("data/analytics/industry_strategy")
    out.mkdir(parents=True, exist_ok=True)
    result.write_csv(out / "industry_trend_exit.csv")

    print("=== 全周期 ===")
    print(
        result.select(
            [
                "strategy",
                pl.col("cagr").round(2),
                pl.col("max_drawdown").round(2),
                pl.col("sharpe").round(2),
                pl.col("calmar").round(2),
            ]
        )
    )

    print("\n=== 样本外（2022后） ===")
    oos_rows = []
    for name, nav in nav_map.items():
        oos_rows.append(
            {"strategy": name, **_metrics(nav.filter(pl.col("trade_date") >= date(2022, 1, 1)))}
        )
    oos = pl.DataFrame(oos_rows)
    print(
        oos.select(
            [
                "strategy",
                pl.col("cagr").round(2),
                pl.col("max_drawdown").round(2),
                pl.col("sharpe").round(2),
                pl.col("calmar").round(2),
            ]
        )
    )


if __name__ == "__main__":
    main()
