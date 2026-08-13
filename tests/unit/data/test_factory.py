from stock.data.factory import create_pipeline
from stock.data.pipeline import MarketDataPipeline


def test_create_pipeline_tushare():
    pipeline = create_pipeline("tushare", "stock_daily_bar")
    assert isinstance(pipeline, MarketDataPipeline)
    assert pipeline.data_source == "tushare"
    assert pipeline.endpoint == "stock_daily_bar"


def test_create_pipeline_yfinance():
    pipeline = create_pipeline("yfinance", "stock_daily_bar")
    assert isinstance(pipeline, MarketDataPipeline)
    assert pipeline.data_source == "yfinance"
    assert pipeline.endpoint == "stock_daily_bar"


def test_create_pipeline_lixinger():
    pipeline = create_pipeline("lixinger", "stock_daily_bar")
    assert isinstance(pipeline, MarketDataPipeline)
    assert pipeline.data_source == "lixinger"


def test_create_pipeline_fred():
    pipeline = create_pipeline("fred", "CPIAUCSL")
    assert isinstance(pipeline, MarketDataPipeline)
    assert pipeline.data_source == "fred"


def test_create_pipeline_mock():
    pipeline = create_pipeline("mock", "daily")
    assert isinstance(pipeline, MarketDataPipeline)
    assert pipeline.data_source == "mock"


def test_create_pipeline_default():
    pipeline = create_pipeline("unknown_source", "daily")
    assert isinstance(pipeline, MarketDataPipeline)
