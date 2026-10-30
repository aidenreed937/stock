"""宏观风控因子时序 Rank IC 验证单元测试。

覆盖：
- 单调同向 → 正 IC；
- 常数因子 → IC 为 None（fail-closed）；
- 样本不足（< min_samples）→ IC 为 None；
- 整体 / 年度 / 当前时窗三口径输出结构正确；
- 置换检验：单调因子显著、随机因子不显著、常数因子 fail-closed。
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import polars as pl

from stock_strategy.macro.ic import (
    overall_ic,
    permutation_ic,
    trailing_ic,
    yearly_ic,
)
from stock_strategy.macro.ic_config import (
    _CORE_FACTOR_COLS,
    load_ic_config,
)


def _series_panel(rows: int = 400) -> pl.DataFrame:
    """构造单序列测试面板：close 加速增长 → 前瞻收益随 index 递增。

    ``close = exp(c·i²)`` ⇒ 任意 h 日前瞻收益 ``exp(c·h(2i+h))-1`` 随 i 单调递增；
    因子 ``overheat_index = i``（单调增）→ 正 IC，``panic_index = -i``（单调减）→ 负 IC。
    """
    c = 1e-5
    start = date(2022, 1, 3)
    dates = [start + timedelta(days=i) for i in range(rows)]
    return pl.DataFrame(
        {
            "trade_date": dates,
            "overheat_index": [float(i) for i in range(rows)],  # 单调增因子
            "panic_index": [float(rows - i) for i in range(rows)],  # 单调减因子
            "close": [1000.0 * math.exp(c * i * i) for i in range(rows)],
        }
    )


def _attach_returns(frame: pl.DataFrame) -> pl.DataFrame:
    from stock_analytics.primitives import add_forward_returns

    return add_forward_returns(frame, horizons=(5, 20), price_col="close")


def test_overall_ic_positive_and_negative() -> None:
    """单调正相关 → 正 IC；单调负相关 → 负 IC。"""
    frame = _attach_returns(_series_panel())
    overall = overall_ic(frame, ("overheat_index", "panic_index"), (5, 20), min_samples=5)
    d = {(r["factor"], r["horizon"]): r["ic"] for r in overall.to_dicts()}
    assert d[("overheat_index", 5)] > 0.0  # 单调增 close + 单调增因子 -> 正 IC
    assert d[("panic_index", 5)] < 0.0  # 单调减因子 -> 负 IC


def test_constant_factor_ic_none() -> None:
    """常数因子 → 秩相关无定义，IC 为 None（fail-closed）。"""
    frame = _attach_returns(_series_panel().with_columns(pl.lit(50.0).alias("const_factor")))
    overall = overall_ic(frame, ("const_factor",), (5,), min_samples=5)
    assert overall.to_dicts()[0]["ic"] is None


def test_min_samples_insufficient_ic_none() -> None:
    """有效样本 < min_samples → IC 为 None。"""
    frame = _attach_returns(_series_panel(rows=10))
    overall = overall_ic(frame, ("overheat_index",), (5,), min_samples=50)
    # 仅 ~5 个有效样本（尾 5 行 fwd 缺失）
    assert overall.to_dicts()[0]["ic"] is None


def test_yearly_and_trailing_structure() -> None:
    """年度 IC 与当前时窗 IC 输出结构正确且含值。"""
    frame = _attach_returns(_series_panel(rows=400))
    yearly = yearly_ic(frame, ("overheat_index",), (5, 20), min_samples=5)
    assert {"year", "factor", "horizon", "ic", "n"}.issubset(yearly.columns)
    assert yearly["ic"].drop_nulls().len() > 0

    trail = trailing_ic(frame, ("overheat_index",), (5,), min_samples=5, window=100)
    assert "ic" in trail.columns and trail["ic"].drop_nulls().len() > 0


def test_load_ic_config_defaults() -> None:
    """默认配置：核心因子数 / 窗口 / min_samples 合理性。"""
    cfg = load_ic_config()  # 当前库内无 ic 段，回退默认
    assert len(cfg.factors) == len(_CORE_FACTOR_COLS)
    assert cfg.horizons == (5, 20, 60)
    assert cfg.min_samples == 30


def test_unknown_factor_column_fail_closed() -> None:
    """请求不存在的因子列 → 计算跳过，不抛异常，合法列正常输出。"""
    frame = _attach_returns(_series_panel())
    overall = overall_ic(frame, ("missing_col", "overheat_index"), (5,), min_samples=5)
    factors_present = {r["factor"] for r in overall.to_dicts()}
    assert factors_present == {"overheat_index"}
    assert overall.to_dicts()[0]["ic"] is not None


def test_load_ic_config_single_factors_populated() -> None:
    """配置了 23 个单因子 score 列 + 2 个连续确认强度列（共 25）。"""
    cfg = load_ic_config()
    assert len(cfg.single_factors) == 25
    assert "erp_score" in cfg.single_factors
    assert "smart_money_pct" in cfg.single_factors  # score_column 机制的特殊列名
    # 「连续维持 N 天」确认强度列与对应单因子并列参与单因子独立 IC 验证
    assert "insider_net_score_consec" in cfg.single_factors
    assert "smart_money_pct_consec" in cfg.single_factors


def test_build_ic_panel_skips_missing_single_factor_cols(monkeypatch, tmp_path) -> None:
    """单因子列缺失时 fail-closed 跳过，仅保留产物中实际存在的列。"""
    from datetime import date

    import polars as pl

    import stock_strategy.macro.ic as ic_mod

    frame = pl.DataFrame(
        {
            "trade_date": [date(2023, 1, 3), date(2023, 1, 4)],
            "erp_score": [10.0, 20.0],
        }
    )
    monkeypatch.setattr(ic_mod, "load_latest_risk_factors", lambda *a, **k: (None, frame, None))

    class _FakeCat:
        def load_bars(self, **k):
            return pl.DataFrame(
                {
                    "trade_date": [date(2023, 1, 3), date(2023, 1, 4)],
                    "close": [100.0, 101.0],
                }
            )

    panel = ic_mod.build_ic_panel(
        catalog=_FakeCat(),
        risk_root="x",
        factor_cols=("erp_score", "missing_score"),
    )
    assert "erp_score" in panel.columns
    assert "missing_score" not in panel.columns
    assert "fwd_ret_5d" in panel.columns


def test_permutation_ic_monotonic_significant() -> None:
    """单调因子 + 单调前瞻收益 → 真实 IC 超出运气区间，p 值小，判显著。"""
    frame = _attach_returns(_series_panel(rows=200))
    perm = permutation_ic(
        frame, ("overheat_index",), (5,), min_samples=5, n_permutations=100, seed=42
    )
    row = perm.to_dicts()[0]
    assert row["ic"] is not None and row["ic"] > 0.0
    assert row["p_value"] is not None and row["p_value"] < 0.05
    # 运气区间（95% 中心区间）应不覆盖真实 IC 的强方向：单调数据零分布集中在 0 附近
    assert row["ci_lo"] is not None and row["ci_hi"] is not None
    assert abs(row["ci_lo"]) < abs(row["ic"]) or abs(row["ci_hi"]) < abs(row["ic"])
    assert row["significant"] is True


def test_permutation_ic_random_factor_not_significant() -> None:
    """随机噪声因子（与前瞻收益无关联）→ p 值大，不判显著。"""
    frame = _attach_returns(_series_panel(rows=200))
    rng = np.random.default_rng(7)
    noise = pl.Series("noise", rng.normal(size=frame.height))
    frame = frame.with_columns(noise)
    perm = permutation_ic(frame, ("noise",), (5,), min_samples=5, n_permutations=100, seed=42)
    row = perm.to_dicts()[0]
    assert row["ic"] is not None
    assert abs(row["ic"]) < 0.2  # 纯噪声 IC 应接近 0
    assert row["p_value"] is not None and row["p_value"] >= 0.05
    assert row["significant"] is False


def test_permutation_ic_constant_factor_fail_closed() -> None:
    """常数因子 → IC 为 None，p 值/区间/显著标记均 None（fail-closed）。"""
    frame = _attach_returns(_series_panel().with_columns(pl.lit(50.0).alias("const_factor")))
    perm = permutation_ic(frame, ("const_factor",), (5,), min_samples=5, n_permutations=50, seed=42)
    row = perm.to_dicts()[0]
    assert row["ic"] is None
    assert row["p_value"] is None
    assert row["ci_lo"] is None
    assert row["ci_hi"] is None
    assert row["significant"] is None


def test_permutation_ic_reproducible_with_seed() -> None:
    """固定 seed → 置换检验 p 值可复现。"""
    frame = _attach_returns(_series_panel(rows=200))
    a = permutation_ic(frame, ("overheat_index",), (5,), min_samples=5, n_permutations=60, seed=42)
    b = permutation_ic(frame, ("overheat_index",), (5,), min_samples=5, n_permutations=60, seed=42)
    assert a.to_dicts() == b.to_dicts()


def test_permutation_ic_structure() -> None:
    """输出列结构：factor / horizon / ic / n / p_value / ci_lo / ci_hi / significant。"""
    frame = _attach_returns(_series_panel(rows=200))
    perm = permutation_ic(
        frame, ("overheat_index",), (5, 20), min_samples=5, n_permutations=40, seed=1
    )
    expected = {
        "factor",
        "horizon",
        "ic",
        "n",
        "p_value",
        "ci_lo",
        "ci_hi",
        "significant",
    }
    assert set(perm.columns) == expected
    assert perm.height == 2  # 1 因子 × 2 窗口


def test_load_ic_config_permutation_defaults() -> None:
    """置换检验参数从配置读取（500 次 / seed 42 / alpha 0.05）。"""
    cfg = load_ic_config()
    assert cfg.n_permutations == 500
    assert cfg.seed == 42
    assert cfg.alpha == 0.05
