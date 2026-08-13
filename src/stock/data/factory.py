from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stock.data.pipeline import MarketDataPipeline


def create_pipeline(data_source: str, endpoint: str = "stock_daily_bar") -> "MarketDataPipeline":
    from stock.data.pipeline import MarketDataPipeline
    """根据数据源名称和项目任务名统一装配 MarketDataPipeline 实例。

    Args:
        data_source: 数据源标识名称（如 tushare, yfinance, lixinger, fred, mock）。
        endpoint: 项目任务名（如 stock_daily_bar、daily_basic）。

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

        proxy = settings.yfinance_proxy if settings.yfinance_proxy else None
        return create_yfinance_pipeline(endpoint=endpoint, proxy=proxy)
    elif data_source_lower == "lixinger":
        from stock.data.fetcher.lixinger.factory import create_lixinger_pipeline

        return create_lixinger_pipeline(endpoint=endpoint)
    elif data_source_lower == "fred":
        from stock.config.settings import settings
        from stock.data.cleaner.generic_cleaner import GenericCleaner
        from stock.data.fetcher.fred import create_fred_fetcher
        from stock.data.normalizer.generic_normalizer import GenericNormalizer

        proxy = getattr(settings, "fred_proxy", None)
        return MarketDataPipeline(
            fetcher=create_fred_fetcher(proxy=proxy),
            cleaner=GenericCleaner(),
            normalizer=GenericNormalizer(),
            data_source=data_source,
            endpoint=endpoint,
        )
    elif data_source_lower == "mock":
        from stock.data.fetcher.mock import MockDataFetcher

        return MarketDataPipeline(
            fetcher=MockDataFetcher(), data_source=data_source, endpoint=endpoint
        )
    else:
        from stock.data.fetcher.tushare.factory import create_tushare_pipeline

        return create_tushare_pipeline(endpoint=endpoint)
