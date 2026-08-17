from stock_data.core.factory import (
    clear_fetcher_cache,
    create_pipeline,
    get_shared_fetcher,
)
from stock_data.pipeline import MarketDataPipeline


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


def test_create_pipeline_alphavantage():
    clear_fetcher_cache()
    pipeline = create_pipeline("alphavantage", "fx_daily")
    assert isinstance(pipeline, MarketDataPipeline)
    assert pipeline.data_source == "alphavantage"
    assert pipeline.endpoint == "fx_daily"


def test_create_pipeline_default():
    clear_fetcher_cache()
    pipeline = create_pipeline("unknown_source", "stock_daily_bar")
    assert isinstance(pipeline, MarketDataPipeline)
    assert pipeline.data_source == "tushare"


def test_shared_fetcher_singleton_and_clear():
    clear_fetcher_cache()
    f1 = get_shared_fetcher("yfinance")
    f2 = get_shared_fetcher("yfinance")
    assert f1 is f2

    p1 = create_pipeline("yfinance", "stock_daily_bar")
    p2 = create_pipeline("yfinance", "stock_daily_bar")
    assert p1.fetcher is p2.fetcher

    clear_fetcher_cache()
    f3 = get_shared_fetcher("yfinance")
    assert f3 is not f1


def test_create_pipeline_custom_fetcher_injection():
    from stock_data.fetcher.tushare.facade import TuShareDataFetcher

    clear_fetcher_cache()
    custom_fetcher = TuShareDataFetcher(token="test_token")
    pipeline = create_pipeline("tushare", "stock_daily_bar", fetcher=custom_fetcher)
    assert pipeline.fetcher is custom_fetcher
