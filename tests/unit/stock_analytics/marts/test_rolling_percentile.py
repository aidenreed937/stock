"""共享滚动分位数工具测试。"""

from datetime import date

import numpy as np
import polars as pl

from stock_analytics.marts.shared.rolling_percentile import (
    MIN_WINDOW_SAMPLE_RATIO,
    _rolling_rank_min_percentile,
    add_rolling_percentiles,
)


def _brute_percentile(values: np.ndarray, window: int) -> np.ndarray:
    """朴素实现（与 specs 相同的 min-rank 口径），供对照。"""
    out: list[float] = []
    for i in range(len(values)):
        current = values[i]
        if np.isnan(current):
            out.append(np.nan)
            continue
        window_values = values[max(0, i - window + 1) : i + 1]
        valid = [v for v in window_values if not np.isnan(v)]
        count = len(valid)
        if count < max(1, int(window * MIN_WINDOW_SAMPLE_RATIO)):
            out.append(np.nan)
            continue
        lower_count = sum(1 for v in valid if v <= current)
        out.append((lower_count - 1) / (count - 1) * 100.0 if count > 1 else 50.0)
    return np.array(out)


def test_rolling_percentile_matches_brute_force() -> None:
    """随机序列对照朴素实现，验证 min-rank 口径一致。"""
    rng = np.random.default_rng(7)
    values = rng.normal(50.0, 20.0, 80)
    values[rng.choice(80, 8, replace=False)] = np.nan
    for window in (5, 10, 30):
        fast = _rolling_rank_min_percentile(values, window=window)
        slow = _brute_percentile(values, window=window)
        assert np.allclose(fast, slow, equal_nan=True)


def test_rolling_percentile_current_null_returns_null() -> None:
    """当前值为缺失时返回缺失，而不是被当作最小值。"""
    values = np.array([10.0, 20.0, np.nan])
    out = _rolling_rank_min_percentile(values, window=5)
    assert np.isnan(out[2])


def test_rolling_percentile_start_index_skips_history() -> None:
    """增量语义：start_index 之前保持 NaN，之后计算。"""
    values = np.arange(1.0, 12.0, 1.0)
    out = _rolling_rank_min_percentile(values, window=5, start_index=8)
    assert np.all(np.isnan(out[:8]))
    assert not np.isnan(out[8])
    assert np.isclose(out[-1], 100.0)


def test_add_rolling_percentiles_grouped_and_cutoff() -> None:
    """按组添加分位，cutoff 前保持缺失；样本满足窗口门槛时产出分位。"""
    dates = [date(2020, 1, d) for d in range(1, 21)]
    frame = pl.DataFrame(
        {
            "industry_code": ["A"] * 20 + ["B"] * 20,
            "trade_date": dates + dates,
            "pe": list(range(1, 21)) + list(range(21, 41)),
        }
    )
    result = add_rolling_percentiles(
        frame,
        key="industry_code",
        date_column="trade_date",
        value_columns=["pe"],
        window_5y=10,
        window_10y=10,
        cutoff_date=date(2020, 1, 15),
    )
    assert "pe_percentile_5y" in result.columns
    assert "pe_percentile_10y" in result.columns
    a = result.filter(pl.col("industry_code") == "A").sort("trade_date")
    assert a["pe_percentile_5y"][:14].null_count() == 14
    # idx15 起窗口=10 且样本=10，满足 80% 门槛（8），应产出分位
    assert a["pe_percentile_5y"][14:].null_count() == 0
    assert np.isclose(a["pe_percentile_5y"][-1], 100.0)  # 单调序列末值为 100


def test_add_rolling_percentiles_empty_group_keeps_schema() -> None:
    """cutoff 后无目标行的分组仍应补齐分位列，保证 concat schema 一致。"""
    frame = pl.DataFrame(
        {
            "industry_code": ["A", "B"],
            "trade_date": [date(2020, 1, 1), date(2020, 1, 2)],
            "pe": [10.0, 20.0],
        }
    )
    result = add_rolling_percentiles(
        frame,
        key="industry_code",
        date_column="trade_date",
        value_columns=["pe"],
        cutoff_date=date(2020, 6, 1),
    )
    assert result.height == 2
    assert result["pe_percentile_5y"].null_count() == 2
    assert result["pe_percentile_10y"].null_count() == 2
