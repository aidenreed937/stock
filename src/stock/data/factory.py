from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stock.data.pipeline import MarketDataPipeline


def create_pipeline(data_source: str, endpoint: str = "daily") -> "MarketDataPipeline":
    from stock.data.pipeline import MarketDataPipeline
    """根据数据源名称和 API 接口名称统一装配 MarketDataPipeline 实例。

    Args:
        data_source: 数据源标识名称（如 tushare, yfinance, lixinger, fred, mock）。
        endpoint: 接口名称（如 daily, daily_basic）。

    Returns:
        MarketDataPipeline: 配置好的行情数据 ETL 管道。
    """
    data_source_lower = data_source.lower()

    if data_source_lower == "tushare":
        from stock.data.fetcher.tushare.factory import create_tushare_pipeline

        return create_tushare_pipeline(endpoint=endpoint)
    elif data_source_lower == "yfinance":
        from stock.config.settings import settings
        from stock.data.fetcher.yfinance.factory import create_yfinance_pipeline

        yf_endpoint = "history" if endpoint == "daily" else endpoint
        proxy = settings.yfinance_proxy if settings.yfinance_proxy else None
        return create_yfinance_pipeline(endpoint=yf_endpoint, proxy=proxy)
    elif data_source_lower == "lixinger":
        from stock.data.fetcher.lixinger.factory import create_lixinger_pipeline

        return create_lixinger_pipeline(endpoint=endpoint)
    elif data_source_lower == "fred":
        from stock.data.fetcher.fred import create_fred_fetcher

        return MarketDataPipeline(
            fetcher=create_fred_fetcher(), data_source=data_source, endpoint=endpoint
        )
    elif data_source_lower == "mock":
        from stock.data.fetcher.mock import MockDataFetcher

        return MarketDataPipeline(
            fetcher=MockDataFetcher(), data_source=data_source, endpoint=endpoint
        )
    else:
        from stock.data.fetcher.tushare.factory import create_tushare_pipeline

        return create_tushare_pipeline(endpoint=endpoint)
