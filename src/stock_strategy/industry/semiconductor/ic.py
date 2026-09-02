"""半导体腿部 IC 验证（Spearman rank IC）。

对齐 `scripts/semi_structural_ic.py` 口径：
- IC = Spearman(腿分, f60)，f60 = close.shift(-60)/close - 1（60 日前瞻收益）；
- 整体 IC + 年度 IC + 当前截面；
- 常数输入（平台分位）时 IC 无定义返回 None。
术语约定：本层（stock_strategy）是**验证层**——消费 stock_analytics 产出的特征
（feature / 候选因子），通过 IC / 回测 / 敏感性扫描**验证其是否为有效因子（factor）**。
本层不产生新特征。
"""

from __future__ import annotations

import polars as pl
from scipy import stats

_MIN_SAMPLES = 30


def spearman_ic(sub: pl.DataFrame, col: str, min_samples: int = _MIN_SAMPLES) -> float | None:
    """计算单腿 Spearman IC；样本不足/常数输入返回 None。"""
    s = sub.drop_nulls([col, "f60"])
    if len(s) < min_samples or s[col].n_unique() < 2 or s["f60"].n_unique() < 2:
        return None
    return round(float(stats.spearmanr(s[col].to_list(), s["f60"].to_list())[0]), 3)


def attach_f60(frame: pl.DataFrame, fwd: int = 60) -> pl.DataFrame:
    """附加 fwd 日前瞻收益列 f60（默认 60 日）。"""
    return frame.sort("trade_date").with_columns(
        (pl.col("close").shift(-fwd) / pl.col("close") - 1.0).alias("f60")
    )


def yearly_ic(
    frame: pl.DataFrame, cols: list[str], min_samples: int = _MIN_SAMPLES
) -> pl.DataFrame:
    """分年度 IC 表。"""
    rows: list[dict[str, object]] = []
    for year in sorted(frame["trade_date"].dt.year().unique().to_list()):
        sub = frame.filter(pl.col("trade_date").dt.year() == year)
        row: dict[str, object] = {"year": year, "n": len(sub)}
        for col in cols:
            row[col] = spearman_ic(sub, col, min_samples)
        rows.append(row)
    return pl.DataFrame(rows)


def current_cross_section(frame: pl.DataFrame, cols: list[str]) -> pl.DataFrame:
    """最新交易日各腿当前值。"""
    latest_date = frame["trade_date"].max()
    latest = frame.filter(pl.col("trade_date") == latest_date)
    row: dict[str, object] = {"trade_date": latest_date}
    for col in cols:
        row[col] = latest[col].drop_nulls().last()
    return pl.DataFrame([row])


def overall_ic(
    frame: pl.DataFrame, cols: list[str], min_samples: int = _MIN_SAMPLES
) -> dict[str, float | None]:
    """整体 IC。"""
    return {col: spearman_ic(frame, col, min_samples) for col in cols}


__all__ = [
    "attach_f60",
    "current_cross_section",
    "overall_ic",
    "spearman_ic",
    "yearly_ic",
]
