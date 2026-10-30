"""化工产业分层包导出契约测试。"""


def test_chemicals_domain_package_exposes_layered_modules() -> None:
    from stock_data.fetcher.industry.chemicals import (
        ChemicalCapacityUtilization10Y,
        ChemicalsCollector,
        ChemicalSpreadCalculator,
        ChemicalsRawPaths,
        ChemicalWeeklySurveyCollector,
        FuturesHoldRankCollector,
        FuturesInventoryCollector,
        FuturesPriceCollector,
        records_to_chemical_market_frame,
    )
    from stock_data.fetcher.industry.chemicals.collectors import (
        ChemicalsCollector as LayeredChemicalsCollector,
    )
    from stock_data.fetcher.industry.chemicals.collectors import (
        FuturesPriceCollector as LayeredFuturesPriceCollector,
    )
    from stock_data.fetcher.industry.chemicals.schemas import (
        CHEMICAL_FUTURES_DAILY_RAW_SCHEMA,
        CHEMICAL_FUTURES_DAILY_SCHEMA,
        CHEMICAL_MARKET_RAW_SCHEMA,
        CHEMICAL_MARKET_SCHEMA,
    )
    from stock_data.fetcher.industry.chemicals.transforms import (
        build_futures_price_curated_frame,
        build_spread_curated_frame,
    )
    from stock_data.fetcher.industry.chemicals.transforms import (
        records_to_chemical_market_frame as layered_market_transform,
    )

    assert ChemicalsCollector is LayeredChemicalsCollector
    assert FuturesPriceCollector is LayeredFuturesPriceCollector
    assert ChemicalCapacityUtilization10Y.__module__.endswith(".collectors.capacity")
    assert ChemicalSpreadCalculator.__module__.endswith(".collectors.spreads")
    assert ChemicalWeeklySurveyCollector.__module__.endswith(".collectors.weekly_survey")
    assert FuturesHoldRankCollector.__module__.endswith(".collectors.futures_hold_rank")
    assert FuturesInventoryCollector.__module__.endswith(".collectors.inventory")
    assert FuturesPriceCollector.__module__.endswith(".collectors.futures_price")
    assert ChemicalsRawPaths.__module__.endswith(".paths")
    assert records_to_chemical_market_frame.__module__.endswith(".transforms.facts")
    assert records_to_chemical_market_frame is layered_market_transform
    assert build_spread_curated_frame.__module__.endswith(".transforms.spreads")
    assert build_futures_price_curated_frame.__module__.endswith(".transforms.futures_price")
    assert "trade_date" in CHEMICAL_MARKET_SCHEMA
    assert "raw_content_sha256" in CHEMICAL_MARKET_RAW_SCHEMA
    assert "close" in CHEMICAL_FUTURES_DAILY_SCHEMA
    assert "close_raw" in CHEMICAL_FUTURES_DAILY_RAW_SCHEMA
