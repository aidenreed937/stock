from stock.data.fetcher.fred.client import FredClient
from stock.data.fetcher.fred.global_fetcher import FredDataFetcher


def create_fred_fetcher(proxy: str | None = None) -> FredDataFetcher:
    """创建并初始化 FredDataFetcher 实例。"""
    client = FredClient(proxy=proxy)
    return FredDataFetcher(client=client)
