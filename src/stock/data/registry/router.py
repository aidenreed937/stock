"""数据源接口路由与上游市场/数据集解析器。"""


def get_endpoint_market(provider: str, endpoint: str) -> str:
    """根据项目任务名解析上游接口，再获取归属市场。"""
    provider_lower = provider.lower()
    api_name = endpoint
    try:
        from stock.data.task_registry import resolve_task

        api_name = resolve_task(provider_lower, endpoint).api_name
    except ValueError:
        # 迁移旧数据或处理未注册的自定义数据集时，保留原始名称回退路径。
        pass
    if provider_lower == "tushare":
        from stock.data.fetcher.tushare.registry import TUSHARE_API_REGISTRY

        meta = TUSHARE_API_REGISTRY.get(api_name)
        if meta and hasattr(meta, "market"):
            return meta.market
        return "CN"
    if provider_lower == "yfinance":
        from stock.data.fetcher.yfinance.registry import YFINANCE_API_REGISTRY

        meta_yf = YFINANCE_API_REGISTRY.get(api_name)
        if meta_yf and hasattr(meta_yf, "market"):
            return meta_yf.market
        return "US"
    if provider_lower == "lixinger":
        from stock.data.fetcher.lixinger.registry import LIXINGER_API_REGISTRY

        meta_lx = LIXINGER_API_REGISTRY.get(api_name)
        if meta_lx and hasattr(meta_lx, "market"):
            return meta_lx.market
        return "HK" if api_name.startswith("hk") else "CN"
    if provider_lower == "fred":
        from stock.data.fetcher.fred.registry import FRED_API_REGISTRY

        meta_fr = FRED_API_REGISTRY.get(api_name)
        if meta_fr and hasattr(meta_fr, "market"):
            return meta_fr.market
        return "US"
    return "MULTI"


def dataset_for_endpoint(endpoint: str, symbol: str = "", provider: str = "tushare") -> str:
    """返回项目任务对应的唯一数据集目录名。"""
    from stock.data.task_registry import task_dataset

    return task_dataset(provider, endpoint, symbol=symbol)
