"""化工产业 RAW → Curated 离线重放计划（不触发网络采集）。

Curated/RAW 路径取自 :mod:`stock_data.fetcher.industry.chemicals.registry`。
"""

from __future__ import annotations

from typing import Any

from stock_data.fetcher.industry.replay_support import replay_entry

__all__ = ["build_chemicals_replay_plan"]


def build_chemicals_replay_plan() -> dict[str, dict[str, Any]]:
    """构建化工产业的离线重放计划（metric -> 执行计划）。"""
    from stock_data.fetcher.industry.chemicals.collectors.capacity import (
        ChemicalCapacityUtilization10Y,
    )
    from stock_data.fetcher.industry.chemicals.collectors.futures_hold_rank import (
        FuturesHoldRankCollector,
    )
    from stock_data.fetcher.industry.chemicals.collectors.inventory import (
        FuturesInventoryCollector,
    )
    from stock_data.fetcher.industry.chemicals.collectors.market import ChemicalsCollector
    from stock_data.fetcher.industry.chemicals.collectors.monthly_survey import (
        ChemicalMonthlySurveyCollector,
    )
    from stock_data.fetcher.industry.chemicals.collectors.spot_price import (
        load_all_spot_price_snapshots,
    )
    from stock_data.fetcher.industry.chemicals.collectors.spreads import ChemicalSpreadCalculator
    from stock_data.fetcher.industry.chemicals.collectors.weekly_survey import (
        ChemicalWeeklySurveyCollector,
    )
    from stock_data.fetcher.industry.chemicals.paths import ChemicalsRawPaths
    from stock_data.fetcher.industry.chemicals.registry import ENDPOINT_SPECS
    from stock_data.fetcher.industry.chemicals.transforms.capacity import (
        build_capacity_raw_frame,
        build_capacity_utilization_frame,
    )
    from stock_data.fetcher.industry.chemicals.transforms.facts import (
        records_to_chemical_market_frame,
        records_to_raw_chemical_market_frame,
    )
    from stock_data.fetcher.industry.chemicals.transforms.hold_rank import (
        build_hold_rank_curated_frame,
        build_hold_rank_raw_frame,
    )
    from stock_data.fetcher.industry.chemicals.transforms.inventory import (
        build_futures_inventory_curated_frame,
        build_futures_inventory_raw_frame,
    )
    from stock_data.fetcher.industry.chemicals.transforms.monthly_survey import (
        build_monthly_survey_curated_frame,
        build_monthly_survey_raw_frame,
    )
    from stock_data.fetcher.industry.chemicals.transforms.spot_price import (
        records_to_spot_price_curated_frame,
        records_to_spot_price_raw_frame,
    )
    from stock_data.fetcher.industry.chemicals.transforms.spreads import (
        build_spread_curated_frame,
        build_spread_raw_frame,
    )
    from stock_data.fetcher.industry.chemicals.transforms.weekly_survey import (
        build_weekly_survey_curated_frame,
        build_weekly_survey_raw_frame,
    )

    return {
        "chemical_market": replay_entry(
            "chemical_market",
            loader=lambda raw_root: list(
                ChemicalsCollector(raw_dir=raw_root).load_from_raw_csv(
                    ChemicalsRawPaths(raw_root).market_csv
                )
            ),
            to_frame=records_to_chemical_market_frame,
            raw_to_frame=records_to_raw_chemical_market_frame,
            primary_keys=["report_month"],
            specs=ENDPOINT_SPECS,
        ),
        "chemical_spot_price": replay_entry(
            "chemical_spot_price",
            loader=lambda raw_root: list(
                load_all_spot_price_snapshots(ChemicalsRawPaths(raw_root).ppi_dir)
            ),
            to_frame=records_to_spot_price_curated_frame,
            raw_to_frame=records_to_spot_price_raw_frame,
            primary_keys=["symbol", "trade_date"],
            specs=ENDPOINT_SPECS,
        ),
        "chemical_futures_inventory": replay_entry(
            "chemical_futures_inventory",
            loader=lambda raw_root: FuturesInventoryCollector(raw_dir=raw_root).load_from_raw(),
            to_frame=build_futures_inventory_curated_frame,
            raw_to_frame=build_futures_inventory_raw_frame,
            primary_keys=["symbol", "trade_date"],
            specs=ENDPOINT_SPECS,
        ),
        "chemical_weekly_survey": replay_entry(
            "chemical_weekly_survey",
            loader=lambda raw_root: ChemicalWeeklySurveyCollector(raw_dir=raw_root).load_from_raw(),
            to_frame=build_weekly_survey_curated_frame,
            raw_to_frame=build_weekly_survey_raw_frame,
            primary_keys=["product_name", "report_date", "source"],
            specs=ENDPOINT_SPECS,
        ),
        "chemical_monthly_survey": replay_entry(
            "chemical_monthly_survey",
            loader=lambda raw_root: ChemicalMonthlySurveyCollector(
                raw_dir=raw_root
            ).load_from_raw(),
            to_frame=build_monthly_survey_curated_frame,
            raw_to_frame=build_monthly_survey_raw_frame,
            primary_keys=["product_name", "report_month", "source"],
            specs=ENDPOINT_SPECS,
        ),
        "chemical_capacity_utilization_10y": replay_entry(
            "chemical_capacity_utilization_10y",
            loader=lambda raw_root: ChemicalCapacityUtilization10Y(
                raw_dir=raw_root
            ).build_raw_utilization(),
            to_frame=build_capacity_utilization_frame,
            raw_to_frame=build_capacity_raw_frame,
            primary_keys=["product_name", "trade_date"],
            specs=ENDPOINT_SPECS,
        ),
        "chemical_spreads": replay_entry(
            "chemical_spreads",
            loader=lambda raw_root: ChemicalSpreadCalculator(raw_dir=raw_root).build_raw_spreads(),
            to_frame=build_spread_curated_frame,
            raw_to_frame=build_spread_raw_frame,
            primary_keys=["product_name", "trade_date"],
            specs=ENDPOINT_SPECS,
        ),
        "futures_hold_rank": replay_entry(
            "futures_hold_rank",
            loader=lambda raw_root: FuturesHoldRankCollector(raw_dir=raw_root).load_raw_snapshots(),
            to_frame=build_hold_rank_curated_frame,
            raw_to_frame=build_hold_rank_raw_frame,
            primary_keys=["symbol", "trade_date"],
            specs=ENDPOINT_SPECS,
        ),
    }
