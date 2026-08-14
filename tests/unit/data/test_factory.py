from stock.data.factory import (
    clear_fetcher_cache,
    create_pipeline,
    get_shared_fetcher,
)
from stock.data.fetcher.mock import MockDataFetcher
from stock.data.pipeline import MarketDataPipeline


def test_create_pipeline_tushare():
    clear_fetcher_cache()
    pipeline = create_pipeline("tushare", "stock_daily_bar")
    assert isinstance(pipeline, MarketDataPipeline)
    assert pipeline.data_source == "tushare"
    assert pipeline.endpoint == "stock_daily_bar"


def test_create_pipeline_yfinance():
    clear_fetcher_cache()
    pipeline = create_pipeline("yfinance", "stock_daily_bar")
    assert isinstance(pipeline, MarketDataPipeline)
    assert pipeline.data_source == "yfinance"
    assert pipeline.endpoint == "stock_daily_bar"


def test_create_pipeline_lixinger():
    clear_fetcher_cache()
    pipeline = create_pipeline("lixinger", "stock_daily_bar")
    assert isinstance(pipeline, MarketDataPipeline)
    assert pipeline.data_source == "lixinger"


def test_create_pipeline_fred():
    clear_fetcher_cache()
    pipeline = create_pipeline("fred", "CPIAUCSL")
    assert isinstance(pipeline, MarketDataPipeline)
    assert pipeline.data_source == "fred"


def test_create_pipeline_mock():
    clear_fetcher_cache()
    pipeline = create_pipeline("mock", "daily")
    assert isinstance(pipeline, MarketDataPipeline)
    assert pipeline.data_source == "mock"


def test_create_pipeline_default():
    clear_fetcher_cache()
    pipeline = create_pipeline("unknown_source", "daily")
    assert isinstance(pipeline, MarketDataPipeline)


def test_shared_fetcher_singleton_and_clear():
    clear_fetcher_cache()
    f1 = get_shared_fetcher("mock")
    f2 = get_shared_fetcher("mock")
    assert f1 is f2

    p1 = create_pipeline("mock", "daily")
    p2 = create_pipeline("mock", "daily")
    assert p1.fetcher is p2.fetcher

    clear_fetcher_cache()
    f3 = get_shared_fetcher("mock")
    assert f3 is not f1


def test_create_pipeline_custom_fetcher_injection():
    clear_fetcher_cache()
    custom_fetcher = MockDataFetcher()
    pipeline = create_pipeline("mock", "daily", fetcher=custom_fetcher)
    assert pipeline.fetcher is custom_fetcher
