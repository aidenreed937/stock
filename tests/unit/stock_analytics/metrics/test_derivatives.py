"""期权与衍生品指标计算器测试。"""

from datetime import date
from pathlib import Path
from typing import cast

import polars as pl
import pytest

from stock_analytics.marts.option_volatility import _black_scholes_price
from stock_analytics.metrics import MetricContext, MetricEngine, create_default_registry
from stock_analytics.metrics.spec import EntityType, MetricDomain


class FakeCatalog:
    storage_dir = Path("data/curated")

    def __init__(self, datasets: dict[str, pl.DataFrame], data_source: str = "tushare") -> None:
        self.datasets = datasets
        self.data_source = data_source

    def load_dataset(
        self,
        dataset: str,
        *,
        start_date: object = None,
        end_date: object = None,
    ) -> pl.DataFrame:
        return self.datasets.get(dataset, pl.DataFrame())


def _pcr_context() -> MetricContext:
    dates = [date(2026, 1, 5), date(2026, 1, 6)]
    opt_daily = pl.DataFrame(
        {
            "symbol": ["C1", "P1", "C2", "P2"],
            "trade_date": [dates[0], dates[0], dates[1], dates[1]],
            "vol": [100.0, 200.0, 300.0, 150.0],
            "oi": [1000.0, 2000.0, 3000.0, 1500.0],
            "settle": [1.0, 1.0, 1.0, 1.0],
        }
    )
    opt_basic = pl.DataFrame(
        {
            "symbol": ["C1", "P1", "C2", "P2"],
            "call_put": ["C", "P", "C", "P"],
            "exercise_price": [100.0, 100.0, 100.0, 100.0],
            "maturity_date": [date(2026, 2, 5)] * 4,
            "opt_code": ["OP000300.SH"] * 4,
        }
    )
    catalog = FakeCatalog({"opt_daily": opt_daily, "opt_basic": opt_basic}, data_source="tushare")
    return MetricContext(catalog=cast("object", catalog), end_date=dates[-1])


def _iv_context() -> MetricContext:
    trade_date = date(2026, 8, 1)
    maturity = date(2026, 9, 1)
    spot = 100.0
    strike = 100.0
    rate = 0.02
    volatility = 0.2
    time_years = (maturity - trade_date).days / 365.0
    call_settle = _black_scholes_price(spot, strike, time_years, rate, volatility, "C")
    put_settle = _black_scholes_price(spot, strike, time_years, rate, volatility, "P")
    opt_daily = pl.DataFrame(
        {
            "symbol": ["C1", "P1"],
            "trade_date": [trade_date, trade_date],
            "settle": [call_settle, put_settle],
        }
    )
    opt_basic = pl.DataFrame(
        {
            "symbol": ["C1", "P1"],
            "call_put": ["C", "P"],
            "exercise_price": [strike, strike],
            "maturity_date": [maturity, maturity],
            "opt_code": ["OP000300.SH", "OP000300.SH"],
        }
    )
    index_daily = pl.DataFrame(
        {"symbol": ["000300.SH"], "trade_date": [trade_date], "close": [spot]}
    )
    shibor = pl.DataFrame({"trade_date": [trade_date], "3m": [2.0]})
    catalog = FakeCatalog(
        {
            "opt_daily": opt_daily,
            "opt_basic": opt_basic,
            "index_daily": index_daily,
            "shibor": shibor,
        },
        data_source="tushare",
    )
    return MetricContext(catalog=cast("object", catalog), end_date=trade_date)


def test_default_registry_contains_derivatives_metrics() -> None:
    registry = create_default_registry()

    specs = [
        registry.get("option_put_call_volume_ratio"),
        registry.get("option_put_call_oi_ratio"),
        registry.get("option_settlement_iv_proxy_median"),
        registry.get("option_settlement_iv_proxy_put_call_skew"),
    ]
    assert all(spec.domain == MetricDomain.DERIVATIVES for spec in specs)
    assert all(spec.entity_type == EntityType.MARKET for spec in specs)
    assert specs[0].required_datasets == ("opt_daily", "opt_basic")
    assert specs[2].required_datasets == (
        "opt_daily",
        "opt_basic",
        "fund_daily",
        "index_daily",
        "shibor",
    )


def test_engine_computes_pcr_ratios() -> None:
    results = MetricEngine().compute(
        ["option_put_call_volume_ratio", "option_put_call_oi_ratio"],
        context=_pcr_context(),
    )

    assert results[0].frame["option_put_call_volume_ratio"].to_list() == pytest.approx([2.0, 0.5])
    assert results[1].frame["option_put_call_oi_ratio"].to_list() == pytest.approx([2.0, 0.5])


def test_pcr_ratio_is_null_when_no_call_side() -> None:
    opt_daily = pl.DataFrame(
        {
            "symbol": ["P1"],
            "trade_date": [date(2026, 1, 5)],
            "vol": [200.0],
            "oi": [2000.0],
        }
    )
    opt_basic = pl.DataFrame({"symbol": ["P1"], "call_put": ["P"]})
    catalog = FakeCatalog({"opt_daily": opt_daily, "opt_basic": opt_basic}, data_source="tushare")
    context = MetricContext(catalog=cast("object", catalog), end_date=date(2026, 1, 5))

    results = MetricEngine().compute(["option_put_call_volume_ratio"], context=context)

    frame = results[0].frame
    assert len(frame) == 1
    assert frame["option_put_call_volume_ratio"].null_count() == 1


def test_engine_computes_iv_proxy_median_and_skew() -> None:
    results = MetricEngine().compute(
        ["option_settlement_iv_proxy_median", "option_settlement_iv_proxy_put_call_skew"],
        context=_iv_context(),
    )

    assert results[0].frame["option_settlement_iv_proxy_median"].to_list() == pytest.approx(
        [0.2], abs=1e-6
    )
    assert results[1].frame["option_settlement_iv_proxy_put_call_skew"].to_list() == pytest.approx(
        [0.0], abs=1e-6
    )


def test_iv_proxy_empty_when_underlying_missing() -> None:
    context = _iv_context()
    catalog = cast("FakeCatalog", context.catalog)
    catalog.datasets = {
        "opt_daily": catalog.datasets["opt_daily"],
        "opt_basic": catalog.datasets["opt_basic"],
    }

    results = MetricEngine().compute(["option_settlement_iv_proxy_median"], context=context)

    assert results[0].frame.columns == ["trade_date", "option_settlement_iv_proxy_median"]
    assert results[0].frame.is_empty()


def test_derivatives_metric_empty_when_opt_data_missing() -> None:
    catalog = FakeCatalog({}, data_source="tushare")
    context = MetricContext(catalog=cast("object", catalog), end_date=date(2026, 1, 6))

    results = MetricEngine().compute(
        ["option_put_call_volume_ratio", "option_settlement_iv_proxy_median"],
        context=context,
    )

    assert results[0].frame.is_empty()
    assert results[0].frame.columns == ["trade_date", "option_put_call_volume_ratio"]
    assert results[1].frame.is_empty()
    assert results[1].frame.columns == ["trade_date", "option_settlement_iv_proxy_median"]


def test_derivatives_metric_honors_start_date() -> None:
    context = _pcr_context()
    context.start_date = date(2026, 1, 6)

    results = MetricEngine().compute(["option_put_call_volume_ratio"], context=context)

    frame = results[0].frame
    assert frame["trade_date"].to_list() == [date(2026, 1, 6)]
    assert frame["option_put_call_volume_ratio"].to_list() == pytest.approx([0.5])
