"""Alpha Vantage pipeline and fetcher factories."""

from __future__ import annotations

from stock.data.fetcher.alphavantage.client import AlphaVantageClient
from stock.data.fetcher.alphavantage.global_fetcher import AlphaVantageDataFetcher
from stock.data.normalizer.generic_normalizer import GenericNormalizer
from stock.data.pipeline import MarketDataPipeline
from stock.data.task_registry import resolve_task


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
    active_fetcher = fetcher or create_alphavantage_fetcher()
    task = resolve_task("alphavantage", endpoint)
    return MarketDataPipeline(
        fetcher=active_fetcher,
        normalizer=GenericNormalizer(),
        data_source="alphavantage",
        endpoint=task.task_name,
    )
