"""Alpha Vantage pipeline and fetcher factories."""

from __future__ import annotations

from typing import TYPE_CHECKING

from stock_data.core.task_registry import resolve_task
from stock_data.fetcher.alphavantage.client import AlphaVantageClient
from stock_data.fetcher.alphavantage.global_fetcher import AlphaVantageDataFetcher

if TYPE_CHECKING:
    from stock_data.pipeline.pipeline import MarketDataPipeline


def create_alphavantage_fetcher(
    api_key: str | None = None,
    proxy: str | None = None,
    rate_limit_per_min: int | None = None,
) -> AlphaVantageDataFetcher:
    client = AlphaVantageClient(
        api_key=api_key,
        proxy=proxy,
        rate_limit_per_min=rate_limit_per_min,
    )
    return AlphaVantageDataFetcher(client=client)


def create_alphavantage_pipeline(
    endpoint: str = "fx_daily",
    fetcher: AlphaVantageDataFetcher | None = None,
) -> MarketDataPipeline:
    from stock_data.pipeline.normalizer.generic_normalizer import GenericNormalizer
    from stock_data.pipeline.pipeline import MarketDataPipeline

    active_fetcher = fetcher or create_alphavantage_fetcher()
    task = resolve_task("alphavantage", endpoint)
    return MarketDataPipeline(
        fetcher=active_fetcher,
        normalizer=GenericNormalizer(),
        data_source="alphavantage",
        endpoint=task.task_name,
    )
