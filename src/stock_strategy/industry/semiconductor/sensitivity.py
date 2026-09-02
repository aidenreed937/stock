"""半导体深研线防守门参数敏感性扫描。

对齐 `scripts/industry_semi_supply_stability.py` 的稳定性验证，补上原脚本缺失的
**降仓权重敏感性**（原 `weight()` 硬编码 0.3，未做网格扫描）：

- `sweep_drawdown_weight`：固定 DOI 阈值，扫降仓权重（单触发降仓系数）→ 全周期/样本外；
- `sweep_doi_threshold`：固定降仓权重，扫 DOI 高堆积阈值（40~90）→ 全周期/样本外/2024 后。

两类扫描复用 `run_backtest`（scissors_inv 组合防守变体，全/OOS 双轨）。
术语约定：本层（stock_strategy）是**验证层**——消费 stock_analytics 产出的特征
（feature / 候选因子），通过 IC / 回测 / 敏感性扫描**验证其是否为有效因子（factor）**。
本层不产生新特征。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date

import polars as pl

from stock_strategy.industry.semiconductor.backtest import (
    run_backtest,
)
from stock_strategy.industry.semiconductor.config import DefenseConfig

_OOS = date(2022, 1, 1)
_POST = date(2024, 1, 1)

# 扫描网格
_DEFAULT_WEIGHTS: tuple[float, ...] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.7)
_DEFAULT_THRESHOLDS: tuple[int, ...] = (40, 50, 60, 70, 80, 90)


def _sweep_rows(
    df: pl.DataFrame,
    *,
    defense_fn: Callable[[float | int], DefenseConfig],
    oos_start: date,
    post_start: date,
    key_label: str,
    keys: Iterable[float | int],
) -> pl.DataFrame:
    """对一组参数各跑一次 scissors_inv 回测，返回全/OOS/2024后指标表。

    ``run_backtest`` 一次调用即返回全周期 + 样本外两套指标；2024 后段单独
    过滤日期后重跑（对齐 stability 脚本 _POST 口径）。
    """
    rows: list[dict[str, object]] = []
    post_df = df.filter(pl.col("trade_date") >= post_start)
    for key in keys:
        defense = defense_fn(key)
        res = run_backtest(
            df,
            modes=("scissors_inv",),
            oos_start=oos_start,
            defense=defense,
        )
        row = res.filter(pl.col("variante") == "scissors_inv").to_dicts()[0]
        res_post = (
            run_backtest(
                post_df,
                modes=("scissors_inv",),
                oos_start=oos_start,
                defense=defense,
            )
            .filter(pl.col("variante") == "scissors_inv")
            .to_dicts()[0]
        )
        rows.append(
            {
                key_label: key,
                "全CAGR%": row["全周期CAGR%"],
                "全MaxDD%": row["全周期MaxDD%"],
                "全Sharpe": row["全周期Sharpe"],
                "外CAGR%": row["样本外CAGR%"],
                "外MaxDD%": row["样本外MaxDD%"],
                "外Sharpe": row["样本外Sharpe"],
                "24+CAGR%": res_post["全周期CAGR%"],
                "24+MaxDD%": res_post["全周期MaxDD%"],
                "24+Sharpe": res_post["全周期Sharpe"],
            }
        )
    return pl.DataFrame(rows)


def sweep_drawdown_weight(
    df: pl.DataFrame,
    *,
    weights: tuple[float, ...] = _DEFAULT_WEIGHTS,
    doi_threshold: float = 70.0,
    oos_start: date = _OOS,
    post_start: date = _POST,
) -> pl.DataFrame:
    """降仓权重敏感性扫描（补齐原 stability 脚本缺失的维度）。"""
    return _sweep_rows(
        df,
        defense_fn=lambda w: DefenseConfig(
            scissors_lt=0.0, doi_ge=doi_threshold, drawdown_weight=float(w)
        ),
        oos_start=oos_start,
        post_start=post_start,
        key_label="weight",
        keys=weights,
    )


def sweep_doi_threshold(
    df: pl.DataFrame,
    *,
    thresholds: tuple[int, ...] = _DEFAULT_THRESHOLDS,
    drawdown_weight: float = 0.3,
    oos_start: date = _OOS,
    post_start: date = _POST,
) -> pl.DataFrame:
    """DOI 高堆积阈值敏感性扫描（对齐 stability 脚本 th=40~90）。"""
    return _sweep_rows(
        df,
        defense_fn=lambda th: DefenseConfig(
            scissors_lt=0.0, doi_ge=float(th), drawdown_weight=drawdown_weight
        ),
        oos_start=oos_start,
        post_start=post_start,
        key_label="th",
        keys=thresholds,
    )


__all__ = [
    "sweep_doi_threshold",
    "sweep_drawdown_weight",
]
