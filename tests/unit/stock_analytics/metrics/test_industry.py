"""申万一级行业指标计算器测试。"""

from datetime import date, timedelta
from pathlib import Path
from typing import cast

import polars as pl
import pytest

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


def _industry_context() -> MetricContext:
    dates = [date(2026, 1, 5) + timedelta(days=index) for index in range(2)]
    sw_daily = pl.DataFrame(
        {
            "trade_date": [
                dates[0],
                dates[0],
                dates[0],
                dates[1],
                dates[1],
                dates[1],
                dates[0],
            ],
            "symbol": [
                "801010.SI",
                "801020.SI",
                "801030.SI",
                "801010.SI",
                "801020.SI",
                "801030.SI",
                "850361.SI",
            ],
            "name": ["农林牧渔", "采掘", "化工", "农林牧渔", "采掘", "化工", "unmapped"],
            "classification": [
                "SW2021",
                "SW2021",
                "SW2021",
                "SW2021",
                "SW2021",
                "SW2021",
                None,
            ],
            "industry_level": ["L1", "L1", "L1", "L1", "L1", "L1", None],
            "pct_change": [1.0, 2.0, -0.5, 0.5, 1.5, -1.0, 3.0],
            "amount": [1.0e8, 2.0e8, 3.0e8, 4.0e8, 5.0e8, 6.0e8, 9.0e8],
            "pe": [10.0, 15.0, 20.0, 11.0, 16.0, 21.0, 30.0],
            "pb": [1.0, 1.5, 2.0, 1.1, 1.6, 2.1, 3.0],
        }
    )
    catalog = FakeCatalog({"sw_daily": sw_daily}, data_source="tushare")
    return MetricContext(catalog=cast("object", catalog), end_date=dates[-1])


def test_default_registry_contains_industry_metrics() -> None:
    registry = create_default_registry()

    specs = [
        registry.get("sw_industry_pct_change"),
        registry.get("sw_industry_amount_yi"),
        registry.get("sw_industry_pe"),
        registry.get("sw_industry_pb"),
    ]
    assert all(spec.entity_type == EntityType.INDUSTRY for spec in specs)
    assert all(spec.required_datasets == ("sw_daily",) for spec in specs)
    assert all(
        spec.output_columns[:3] == ("trade_date", "industry_code", "industry_name")
        for spec in specs
    )
    assert specs[0].domain == MetricDomain.PERFORMANCE
    assert specs[1].domain == MetricDomain.LIQUIDITY
    assert specs[2].domain == MetricDomain.VALUATION
    assert specs[3].domain == MetricDomain.VALUATION


def test_engine_computes_industry_pct_change_filters_l1() -> None:
    results = MetricEngine().compute(["sw_industry_pct_change"], context=_industry_context())

    frame = results[0].frame
    assert frame.height == 6  # 3 行业 x 2 日期，剔除非 L1 噪声行
    assert "unmapped" not in frame["industry_name"].to_list()
    first_day = frame.filter(pl.col("trade_date") == date(2026, 1, 5)).sort("industry_code")
    assert first_day["sw_industry_pct_change"].to_list() == pytest.approx([1.0, 2.0, -0.5])
    assert first_day["industry_name"].to_list() == ["农林牧渔", "采掘", "化工"]


def test_engine_computes_industry_amount_yi() -> None:
    results = MetricEngine().compute(["sw_industry_amount_yi"], context=_industry_context())

    frame = results[0].frame
    assert set(frame.columns) == {
        "trade_date",
        "industry_code",
        "industry_name",
        "sw_industry_amount_yi",
    }
    first_day = frame.filter(pl.col("trade_date") == date(2026, 1, 5)).sort("industry_code")
    assert first_day["sw_industry_amount_yi"].to_list() == pytest.approx([1.0, 2.0, 3.0])


def test_engine_computes_industry_pe_and_pb() -> None:
    results = MetricEngine().compute(
        ["sw_industry_pe", "sw_industry_pb"], context=_industry_context()
    )

    pe_frame = results[0].frame
    pb_frame = results[1].frame
    second_day = pe_frame.filter(pl.col("trade_date") == date(2026, 1, 6)).sort("industry_code")
    assert second_day["sw_industry_pe"].to_list() == pytest.approx([11.0, 16.0, 21.0])
    assert pb_frame.filter(pl.col("trade_date") == date(2026, 1, 6)).sort("industry_code")[
        "sw_industry_pb"
    ].to_list() == pytest.approx([1.1, 1.6, 2.1])


def test_industry_metric_empty_when_sw_daily_missing() -> None:
    catalog = FakeCatalog({}, data_source="tushare")
    context = MetricContext(catalog=cast("object", catalog), end_date=date(2026, 1, 6))

    results = MetricEngine().compute(["sw_industry_pe"], context=context)

    assert results[0].frame.columns == [
        "trade_date",
        "industry_code",
        "industry_name",
        "sw_industry_pe",
    ]
    assert results[0].frame.is_empty()


def test_industry_metric_empty_when_source_column_missing() -> None:
    sw_daily = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, 5)],
            "symbol": ["801010.SI"],
            "name": ["农林牧渔"],
            "classification": ["SW2021"],
            "industry_level": ["L1"],
            "pct_change": [1.0],
            "amount": [1.0e8],
        }
    )
    catalog = FakeCatalog({"sw_daily": sw_daily}, data_source="tushare")
    context = MetricContext(catalog=cast("object", catalog), end_date=date(2026, 1, 5))

    results = MetricEngine().compute(["sw_industry_pct_change", "sw_industry_pe"], context=context)

    assert results[0].frame["sw_industry_pct_change"].to_list() == pytest.approx([1.0])
    assert results[1].frame.columns == [
        "trade_date",
        "industry_code",
        "industry_name",
        "sw_industry_pe",
    ]
    assert results[1].frame.is_empty()


def test_industry_metric_honors_start_date() -> None:
    context = _industry_context()
    context.start_date = date(2026, 1, 6)

    results = MetricEngine().compute(["sw_industry_pct_change"], context=context)

    frame = results[0].frame
    assert set(frame["trade_date"].unique().to_list()) == {date(2026, 1, 6)}
    assert frame.height == 3
