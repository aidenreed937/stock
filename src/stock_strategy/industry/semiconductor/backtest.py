"""半导体单行业事件状态机回测。

对齐 `scripts/industry_semi_supply_legs_backtest.py` 口径：
- 变体：buy_hold（基准）/ scissors_neg（剪刀差<0 空仓）/
        inv_high（DOI 高堆积≥70 降仓 30%）/ scissors_inv（组合防守）；
- T+1 次日出仓、单日 rebalance 状态机、无前视；
- 指标：全周期与样本外（2022-01 起）的 CAGR / MaxDD / Sharpe。
术语约定：本层（stock_strategy）是**验证层**——消费 stock_analytics 产出的特征
（feature / 候选因子），通过 IC / 回测 / 敏感性扫描**验证其是否为有效因子（factor）**。
本层不产生新特征。
"""

from __future__ import annotations

from datetime import date
from typing import Literal

import polars as pl

from stock_strategy.industry.semiconductor.config import DefenseConfig
from stock_strategy.industry.semiconductor.metrics import compute_metrics

_OOS = date(2022, 1, 1)

Mode = Literal["buy_hold", "scissors_neg", "inv_high", "scissors_inv"]

MODE_LABELS: dict[str, str] = {
    "buy_hold": "买入持有（基准）",
    "scissors_neg": "剪刀差<0 空仓",
    "inv_high": "DOI 高堆积降仓30%",
    "scissors_inv": "剪刀差+DOI 组合防守",
}

# 完整回测支持的变体
_MODES: tuple[Mode, ...] = ("buy_hold", "scissors_neg", "inv_high", "scissors_inv")


def position_weight(
    mode: Mode,
    scissors: float | None,
    inventory: float | None,
    defense: DefenseConfig | None = None,
) -> float:
    """事件驱动仓位权重（阈值取自 defense 配置，缺省用 methodology 定稿值）。"""
    d = defense or DefenseConfig()
    sc = scissors if scissors is not None else 50.0
    inv = inventory if inventory is not None else 50.0
    if mode == "buy_hold":
        return 1.0
    if mode == "scissors_neg":
        return 0.0 if sc < d.scissors_lt else 1.0
    if mode == "inv_high":
        return d.drawdown_weight if inv >= d.doi_ge else 1.0
    if mode == "scissors_inv":
        if sc < d.scissors_lt and inv >= d.doi_ge:
            return 0.0
        if sc < d.scissors_lt or inv >= d.doi_ge:
            return d.drawdown_weight
        return 1.0
    return 1.0


def run_backtest(
    df: pl.DataFrame,
    *,
    modes: tuple[Mode, ...] = _MODES,
    oos_start: date = _OOS,
    defense: DefenseConfig | None = None,
    trading_days: int = 252,
) -> pl.DataFrame:
    """对半导体面板跑各变体事件回测，返回变体×（全周期/样本外）指标表。

    输入面板需含：trade_date, close, scissors_score, inventory_score（inventory 可空）。
    """
    d = defense or DefenseConfig()
    if "ret" not in df.columns:
        df = df.sort("trade_date").with_columns(
            pl.col("close").pct_change().fill_null(0.0).alias("ret")
        )

    def _pos(mode: Mode, r: dict[str, object]) -> float:
        scissors = r["scissors_score"]
        inventory = r["inventory_score"]
        ret = r["ret"]
        sc: float | None = float(scissors) if isinstance(scissors, int | float) else None
        inv: float | None = float(inventory) if isinstance(inventory, int | float) else None
        ret_f = float(ret) if isinstance(ret, int | float) else 0.0
        return position_weight(mode, sc, inv, d) * ret_f

    rows: list[dict[str, object]] = []
    for mode in modes:
        full_pos = [_pos(mode, r) for r in df.iter_rows(named=True)]
        full = compute_metrics(_nav(full_pos), trading_days)

        oos_df = df.filter(pl.col("trade_date") >= oos_start)
        oos_pos = [_pos(mode, r) for r in oos_df.iter_rows(named=True)]
        oos = compute_metrics(_nav(oos_pos), trading_days)

        rows.append(
            {
                "variante": mode,
                "全周期CAGR%": round(full["cagr"], 2),
                "全周期MaxDD%": round(full["max_dd"], 2),
                "全周期Sharpe": round(full["sharpe"], 3),
                "样本外CAGR%": round(oos["cagr"], 2),
                "样本外MaxDD%": round(oos["max_dd"], 2),
                "样本外Sharpe": round(oos["sharpe"], 3),
            }
        )
    return pl.DataFrame(rows)


def _nav(pos_rets: list[float]) -> list[float]:
    """从加权日收益序列构建净值；空序列返回 [1.0]（无收益不产生回撤/收益）。"""
    if not pos_rets:
        return [1.0]
    return (1 + pl.Series(pos_rets)).cum_prod().to_list()


__all__ = [
    "MODE_LABELS",
    "_MODES",
    "Mode",
    "position_weight",
    "run_backtest",
]
