"""ETF/行业轮动动量算子 (Rotation Primitives) 单测。"""

from datetime import date, timedelta

import polars as pl
import pytest

from stock_analytics.primitives.rotation import (
    calculate_momentum_acceleration,
    calculate_rps,
    calculate_weighted_momentum,
)


def _series_with_returns(n_rows: int, last: float, returns_at: dict[int, float]) -> list[float]:
    """构造价格序列，在距末尾 offset 行处插入指定 N 日收益率（百分数）。"""
    prices = [float(i + 1) for i in range(n_rows)]
    prices[-1] = last
    for offset, ret in returns_at.items():
        prices[-1 - offset] = last / (1.0 + ret / 100.0)
    return prices


def _rps_single_date_frame(returns: list[float], n_rows: int = 61) -> pl.DataFrame:
    """构造单个交易日截面的 RPS 测试帧（末行 60 日收益率 = returns[i] 百分数）。"""
    dates = [date(2025, 1, 1) + timedelta(days=i) for i in range(n_rows)]
    rows = []
    for i, ret in enumerate(returns):
        prices = [100.0] * n_rows
        prices[-1] = 100.0 * (1.0 + ret / 100.0)
        rows.extend({"symbol": f"S{i}", "trade_date": d, "close": p} for d, p in zip(dates, prices))
    return pl.DataFrame(rows)


def _rps_two_date_frame(n_symbols: int = 10) -> pl.DataFrame:
    """构造两个交易日截面的 RPS 测试帧（日期 2 的收益率与日期 1 相反）。"""
    dates = [date(2025, 1, 1) + timedelta(days=i) for i in range(62)]
    rows = []
    for i in range(n_symbols):
        ret_first = i * 10.0
        ret_last = (n_symbols - 1 - i) * 10.0
        prices = [100.0] * 62
        prices[-2] = 100.0 * (1.0 + ret_first / 100.0)
        prices[-1] = 100.0 * (1.0 + ret_last / 100.0)
        rows.extend({"symbol": f"S{i}", "trade_date": d, "close": p} for d, p in zip(dates, prices))
    return pl.DataFrame(rows)


def test_calculate_weighted_momentum_matches_manual_weighted_sum() -> None:
    prices = _series_with_returns(121, 100.0, {20: 10.0, 60: 20.0, 120: 30.0})
    frame = pl.DataFrame({"close": prices})
    result = calculate_weighted_momentum(frame)

    # 0.5*10 + 0.3*20 + 0.2*30 = 17
    assert result["weighted_momentum"][-1] == pytest.approx(17.0, abs=1e-6)


def test_calculate_weighted_momentum_normalizes_weights_to_sum_one() -> None:
    prices = _series_with_returns(121, 100.0, {20: 10.0, 60: 20.0, 120: 30.0})
    frame = pl.DataFrame({"close": prices})
    result = calculate_weighted_momentum(frame, weights=(1.0, 1.0, 1.0))

    # 归一化后各权重 1/3 → (10 + 20 + 30) / 3 = 20
    assert result["weighted_momentum"][-1] == pytest.approx(20.0, abs=1e-6)


def test_calculate_weighted_momentum_raises_on_length_mismatch() -> None:
    frame = pl.DataFrame({"close": [1.0, 2.0, 3.0]})
    with pytest.raises(ValueError, match="长度必须一致"):
        calculate_weighted_momentum(frame, windows=(20, 60), weights=(0.5, 0.3, 0.2))


def test_calculate_weighted_momentum_raises_on_non_positive_weights() -> None:
    frame = pl.DataFrame({"close": [1.0, 2.0, 3.0]})
    with pytest.raises(ValueError, match="必须为正"):
        calculate_weighted_momentum(frame, windows=(20, 60), weights=(0.0, 0.0))


def test_calculate_weighted_momentum_computes_per_symbol() -> None:
    prices_a = _series_with_returns(121, 100.0, {20: 10.0, 60: 20.0, 120: 30.0})
    prices_b = [100.0] * 121
    frame = pl.DataFrame({"symbol": ["A"] * 121 + ["B"] * 121, "close": prices_a + prices_b})
    result = calculate_weighted_momentum(frame)

    group_a = result.filter(pl.col("symbol") == "A")
    group_b = result.filter(pl.col("symbol") == "B")
    assert group_a["weighted_momentum"][-1] == pytest.approx(17.0, abs=1e-6)
    assert group_b["weighted_momentum"][-1] == pytest.approx(0.0, abs=1e-6)
    # B 组首行无本标的 20 日历史 → null，证明 shift 限定在 symbol 内
    assert group_b["weighted_momentum"][0] is None


def test_calculate_weighted_momentum_propagates_null_for_insufficient_history() -> None:
    prices = _series_with_returns(119, 100.0, {20: 10.0, 60: 20.0})
    frame = pl.DataFrame({"close": prices})
    result = calculate_weighted_momentum(frame)

    # 119 行 < 120 日回看 → 120 日收益全缺失 → 加权动量整体透传 null
    assert result["weighted_momentum"][-1] is None


def test_calculate_weighted_momentum_returns_frame_unchanged_when_empty_or_missing() -> None:
    empty = pl.DataFrame(schema={"close": pl.Float64})
    assert calculate_weighted_momentum(empty).is_empty()

    frame = pl.DataFrame({"other": [1.0, 2.0]})
    assert calculate_weighted_momentum(frame).columns == ["other"]


def test_calculate_momentum_acceleration_matches_fast_minus_slow() -> None:
    prices = _series_with_returns(121, 100.0, {20: 10.0, 60: 20.0})
    frame = pl.DataFrame({"close": prices})
    result = calculate_momentum_acceleration(frame)

    # R20=10, R60=20 → 加速度 = 10 - 20 = -10（短期动能弱于长期）
    assert result["momentum_acceleration_20_60"][-1] == pytest.approx(-10.0, abs=1e-6)


def test_calculate_momentum_acceleration_sign_follows_fast_minus_slow() -> None:
    prices = _series_with_returns(121, 100.0, {20: 30.0, 60: 10.0})
    frame = pl.DataFrame({"close": prices})
    result = calculate_momentum_acceleration(frame)

    # R20=30, R60=10 → 加速度 = +20（短期动能强于长期，符号为正）
    assert result["momentum_acceleration_20_60"][-1] == pytest.approx(20.0, abs=1e-6)


def test_calculate_momentum_acceleration_computes_per_symbol() -> None:
    prices_a = _series_with_returns(121, 100.0, {20: 10.0, 60: 20.0})
    prices_b = [100.0] * 121
    frame = pl.DataFrame({"symbol": ["A"] * 121 + ["B"] * 121, "close": prices_a + prices_b})
    result = calculate_momentum_acceleration(frame)

    group_a = result.filter(pl.col("symbol") == "A")
    group_b = result.filter(pl.col("symbol") == "B")
    assert group_a["momentum_acceleration_20_60"][-1] == pytest.approx(-10.0, abs=1e-6)
    assert group_b["momentum_acceleration_20_60"][-1] == pytest.approx(0.0, abs=1e-6)
    assert group_b["momentum_acceleration_20_60"][0] is None


def test_calculate_momentum_acceleration_propagates_null_for_insufficient_history() -> None:
    prices = _series_with_returns(59, 100.0, {20: 10.0})
    frame = pl.DataFrame({"close": prices})
    result = calculate_momentum_acceleration(frame)

    # 59 行 < 60 日回看 → 长期收益缺失 → 加速度透传 null
    assert result["momentum_acceleration_20_60"][-1] is None


def test_calculate_momentum_acceleration_returns_frame_unchanged_when_empty_or_missing() -> None:
    empty = pl.DataFrame(schema={"close": pl.Float64})
    assert calculate_momentum_acceleration(empty).is_empty()

    frame = pl.DataFrame({"other": [1.0, 2.0]})
    assert calculate_momentum_acceleration(frame).columns == ["other"]


def test_calculate_rps_ranks_highest_return_to_100() -> None:
    frame = _rps_single_date_frame([i * 10.0 for i in range(10)])
    result = calculate_rps(frame, window=60)

    last_date = result["trade_date"].max()
    last = result.filter(pl.col("trade_date") == last_date).sort("symbol")
    # 收益率 0%~90% → 最小名次分位 10%~100%
    assert last["rps_60d"].to_list() == pytest.approx(
        [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    )
    assert last["rps_60d"][-1] == pytest.approx(100.0)  # 最高收益 → RPS=100
    assert last["rps_60d"][0] == pytest.approx(10.0)  # 最低收益 → 最低分位


def test_calculate_rps_uses_min_rank_for_ties() -> None:
    frame = _rps_single_date_frame([0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 50.0, 70.0, 80.0, 90.0])
    result = calculate_rps(frame, window=60)

    last_date = result["trade_date"].max()
    last = result.filter(pl.col("trade_date") == last_date).sort("symbol")
    # 并列 50% 共享最小名次 6 → RPS=60；最高 90% → 100；最低 0% → 10
    assert last["rps_60d"].to_list() == pytest.approx(
        [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 60.0, 80.0, 90.0, 100.0]
    )


def test_calculate_rps_computes_independently_per_trade_date() -> None:
    frame = _rps_two_date_frame(10)
    result = calculate_rps(frame, window=60)

    dates = result["trade_date"].unique().sort()
    prev_date, last_date = dates[-2], dates[-1]
    prev = result.filter(pl.col("trade_date") == prev_date).sort("symbol")
    last = result.filter(pl.col("trade_date") == last_date).sort("symbol")
    # 日期 1: S_i 收益 i*10% → 升序 RPS
    assert prev["rps_60d"].to_list() == pytest.approx(
        [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    )
    # 日期 2: 收益率反转 → RPS 同样反转，证明各交易日截面独立计算
    assert last["rps_60d"].to_list() == pytest.approx(
        [100.0, 90.0, 80.0, 70.0, 60.0, 50.0, 40.0, 30.0, 20.0, 10.0]
    )


def test_calculate_rps_passes_null_for_missing_return_samples() -> None:
    dates = [date(2025, 1, 1) + timedelta(days=i) for i in range(61)]
    rows = []
    for i in range(10):
        prices = [100.0] * 61
        prices[-1] = 100.0 * (1.0 + i * 10.0 / 100.0)
        rows.extend({"symbol": f"S{i}", "trade_date": d, "close": p} for d, p in zip(dates, prices))
    short_prices = [100.0] * 30
    short_prices[-1] = 105.0
    rows.extend(
        {"symbol": "SHORT", "trade_date": d, "close": p} for d, p in zip(dates[-30:], short_prices)
    )
    frame = pl.DataFrame(rows)
    result = calculate_rps(frame, window=60)

    last_date = result["trade_date"].max()
    last = result.filter(pl.col("trade_date") == last_date).sort("symbol")
    assert last["rps_60d"].to_list()[:10] == pytest.approx(
        [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    )
    assert last["rps_60d"][10] is None  # SHORT 历史不足 60 日 → 收益缺失 → RPS null


def test_calculate_rps_without_symbol_column() -> None:
    dates = [date(2025, 1, 1) + timedelta(days=i) for i in range(61)]
    prices = [100.0] * 61
    prices[-1] = 150.0  # 60 日收益 +50%
    frame = pl.DataFrame({"trade_date": dates, "close": prices})
    result = calculate_rps(frame, window=60)

    # 无 symbol 分支：普通 shift 计算收益；截面仅 1 个样本 → RPS=100
    assert "rps_60d" in result.columns
    assert result["rps_60d"][-1] == pytest.approx(100.0)
    assert result["rps_60d"][0] is None


def test_calculate_rps_returns_frame_unchanged_when_empty_or_missing() -> None:
    empty = pl.DataFrame(schema={"close": pl.Float64, "trade_date": pl.Date})
    assert calculate_rps(empty).is_empty()

    no_group = pl.DataFrame({"symbol": ["A"], "close": [1.0]})
    assert calculate_rps(no_group).columns == ["symbol", "close"]

    no_price = pl.DataFrame({"symbol": ["A"], "trade_date": [date(2025, 1, 1)]})
    assert calculate_rps(no_price).columns == ["symbol", "trade_date"]
