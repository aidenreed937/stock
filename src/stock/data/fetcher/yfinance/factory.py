from stock.data.cleaner.bar_cleaner import BarDataCleaner
from stock.data.fetcher.yfinance.client import YFinanceClient
from stock.data.fetcher.yfinance.global_fetcher import YFinanceDataFetcher
from stock.data.pipeline import MarketDataPipeline


def create_yfinance_pipeline(
    proxy: str | None = None, endpoint: str = "stock_daily_bar"
) -> MarketDataPipeline:
    """创建并装配好 YFinance 数据源的 MarketDataPipeline 实例。

    Args:
        proxy: HTTP/HTTPS 代理配置。
        endpoint: 接口标识名称。
    """
    client = YFinanceClient(proxy=proxy)
    fetcher = YFinanceDataFetcher(client=client)
    from stock.data.task_registry import resolve_task

    task = resolve_task("yfinance", endpoint)
    cleaner = BarDataCleaner() if task.quality_profile == "bar" else None
    return MarketDataPipeline(
        fetcher=fetcher,
        cleaner=cleaner,
        data_source="yfinance",
        endpoint=task.task_name,
    )
