"""期权 BS-IV Polars 高性能算子与精度对账测试。"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from stock_analytics.marts.option_volatility import (
    _black_scholes_price,
    build_settlement_iv_proxy_mart,
    settlement_implied_volatility,
)
from stock_analytics.plugins import options as options_plugin
from stock_analytics.plugins.options import compute_fast_bs_iv, is_rust_plugin_available


def test_plugin_availability_probe() -> None:
    """测试 Rust 插件探测函数行为正常。"""
    available = is_rust_plugin_available()
    assert isinstance(available, bool)


def test_plugin_discovery_does_not_use_polars_api_as_availability(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """没有动态库时，不能仅因 Polars API 存在就报告插件可用。"""
    monkeypatch.setattr(options_plugin, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(options_plugin.importlib.util, "find_spec", lambda _: None)

    assert options_plugin._find_plugin_path() is None


def test_python_fallback_remains_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """未编译 Rust 插件时仍使用原有 Python 求解器。"""
    monkeypatch.setattr(options_plugin, "_PLUGIN_PATH", None)
    monkeypatch.setattr(options_plugin, "_RUST_AVAILABLE", False)

    settle = _black_scholes_price(1.0, 1.0, 0.25, 0.0, 0.2, "C")
    result = pl.DataFrame(
        {
            "settle": [settle],
            "spot": [1.0],
            "strike": [1.0],
            "time_years": [0.25],
            "rate": [0.0],
            "call_put": ["C"],
        }
    ).with_columns(
        compute_fast_bs_iv(
            pl.col("settle"),
            pl.col("spot"),
            pl.col("strike"),
            pl.col("time_years"),
            pl.col("rate"),
            pl.col("call_put"),
        ).alias("iv")
    )

    assert result["iv"][0] == pytest.approx(0.2, abs=1e-6)


def test_plugin_precision_parity_with_python() -> None:
    """测试算子与 Python 版 settlement_implied_volatility 数值精度 100% 对齐。"""
    if not is_rust_plugin_available():
        pytest.skip("Rust 插件未编译，跳过原生插件精度对账")

    # 覆盖实值、平值、虚值典型 moneyness (0.8 ~ 1.2)
    spots = [2.5, 3.0, 3.5, 10.0]
    moneyness_ratios = [0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15]
    time_years_list = [0.08, 0.25, 0.5, 1.0]
    rates = [0.015, 0.025, 0.05]
    true_vols = [0.15, 0.25, 0.40, 0.65]

    rows = []
    for spot in spots:
        for ratio in moneyness_ratios:
            strike = round(spot * ratio, 2)
            for t in time_years_list:
                for r in rates:
                    for vol in true_vols:
                        for cp in ("C", "P"):
                            settle = _black_scholes_price(spot, strike, t, r, vol, cp)
                            rows.append(
                                {
                                    "spot": spot,
                                    "strike": strike,
                                    "time_years": t,
                                    "rate": r,
                                    "settle": settle,
                                    "call_put": cp,
                                    "true_vol": vol,
                                }
                            )

    df = pl.DataFrame(rows)
    result = df.with_columns(
        compute_fast_bs_iv(
            pl.col("settle"),
            pl.col("spot"),
            pl.col("strike"),
            pl.col("time_years"),
            pl.col("rate"),
            pl.col("call_put"),
        ).alias("calculated_iv")
    )

    # 1. 结算价本身经过浮点计算，低 Vega 场景反解误差会放大；保留原有宽松的恢复门槛。
    valid = result.filter(pl.col("calculated_iv").is_not_null())
    assert len(valid) > 0

    diff = (valid["calculated_iv"] - valid["true_vol"]).abs()
    max_diff = diff.max()
    assert max_diff is not None and max_diff < 1e-4

    # 2. 验证与现有 Python 函数输出镜像一致 (误差 < 1e-6)
    for row in valid.to_dicts():
        py_iv = settlement_implied_volatility(
            row["settle"],
            row["spot"],
            row["strike"],
            row["time_years"],
            row["rate"],
            row["call_put"],
        )
        assert py_iv is not None
        assert abs(row["calculated_iv"] - py_iv) < 1e-6


def test_plugin_boundary_conditions() -> None:
    """测试异常与边界情况（到期日为 0、无效负数、虚值越界等）。"""
    df = pl.DataFrame(
        {
            "settle": [0.0, -1.0, 10.0, 0.5, None, 0.5, 0.5, float("nan"), float("inf")],
            "spot": [3.0, 3.0, 3.0, 3.0, 3.0, None, 3.0, 3.0, 3.0],
            "strike": [3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0],
            "time_years": [0.0, 0.25, 0.25, -0.1, 0.25, 0.25, 0.25, 0.25, 0.25],
            "rate": [0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02],
            "call_put": ["C", "C", "C", "C", "C", "C", "X", "C", "C"],
        }
    )

    result = df.with_columns(
        compute_fast_bs_iv(
            pl.col("settle"),
            pl.col("spot"),
            pl.col("strike"),
            pl.col("time_years"),
            pl.col("rate"),
            pl.col("call_put"),
        ).alias("iv")
    )

    # 边界情况应全部安全返回 null
    assert result["iv"].drop_nulls().is_empty()


def test_build_settlement_iv_proxy_mart_end_to_end() -> None:
    """测试 build_settlement_iv_proxy_mart 接入算子后的端到端构建。"""
    daily = pl.DataFrame(
        {
            "symbol": ["10001001.SH", "10001002.SH"],
            "trade_date": ["2026-08-19", "2026-08-19"],
            "settle": [0.15, 0.12],
        }
    )
    basic = pl.DataFrame(
        {
            "symbol": ["10001001.SH", "10001002.SH"],
            "call_put": ["C", "P"],
            "exercise_price": [3.0, 3.0],
            "maturity_date": ["2026-09-24", "2026-09-24"],
            "opt_code": ["OP510050.SH", "OP510050.SH"],
        }
    )
    underlying = pl.DataFrame(
        {
            "symbol": ["510050.SH"],
            "trade_date": ["2026-08-19"],
            "close": [3.05],
        }
    )
    risk_free = pl.DataFrame(
        {
            "trade_date": ["2026-08-19"],
            "risk_free_rate": [0.02],
        }
    )

    mart = build_settlement_iv_proxy_mart(
        daily=daily,
        basic=basic,
        underlying_prices=underlying,
        risk_free_rates=risk_free,
        underlying_symbols=("510050.SH",),
    )

    assert not mart.is_empty()
    assert "settlement_iv_proxy_median" in mart.columns
    assert "settlement_iv_proxy_call_median" in mart.columns
    assert "settlement_iv_proxy_put_median" in mart.columns
    assert "settlement_iv_proxy_put_call_skew" in mart.columns
    assert mart["trade_date"][0] == date(2026, 8, 19)
    assert mart["underlying_symbol"][0] == "510050.SH"
