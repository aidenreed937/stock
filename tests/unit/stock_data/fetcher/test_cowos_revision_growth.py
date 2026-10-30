from datetime import date

import polars as pl

from stock_data.fetcher.industry.semiconductor.models import CowosCapacityEstimateRecord
from stock_data.fetcher.industry.semiconductor.transforms import (
    build_cowos_capacity_estimates_curated_frame,
)


def test_cowos_growth_uses_only_versions_visible_at_published_date() -> None:
    records = [
        CowosCapacityEstimateRecord(
            symbol="2330.TW",
            report_quarter="2024Q4",
            trade_date=date(2024, 12, 31),
            agency="TrendForce",
            published_date=date(2024, 4, 16),
            monthly_capacity_kwpm=40.0,
        ),
        CowosCapacityEstimateRecord(
            symbol="2330.TW",
            report_quarter="2024Q4",
            trade_date=date(2024, 12, 31),
            agency="TrendForce",
            published_date=date(2024, 12, 13),
            monthly_capacity_kwpm=35.0,
        ),
        CowosCapacityEstimateRecord(
            symbol="2330.TW",
            report_quarter="2025Q4",
            trade_date=date(2025, 12, 31),
            agency="TrendForce",
            published_date=date(2024, 4, 16),
            monthly_capacity_kwpm=75.0,
        ),
        CowosCapacityEstimateRecord(
            symbol="2330.TW",
            report_quarter="2025Q4",
            trade_date=date(2025, 12, 31),
            agency="TrendForce",
            published_date=date(2024, 12, 13),
            monthly_capacity_kwpm=70.0,
        ),
    ]

    curated = build_cowos_capacity_estimates_curated_frame(records)
    rows = curated.filter(pl.col("report_quarter") == "2025Q4").sort("published_date").to_dicts()

    assert rows[0]["capacity_qoq"] == 0.875
    assert rows[0]["capacity_yoy"] == 0.875
    assert rows[1]["capacity_qoq"] == 1.0
    assert rows[1]["capacity_yoy"] == 1.0
