"""项目任务名与数据源 API 名称的显式路由表。"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TaskSpec:
    """一个公开项目任务到一个上游 API 的固定映射。"""

    task_name: str
    provider: str
    api_name: str
    dataset: str
    frequency: str = "daily"
    quality_profile: str = "generic"
    partitioned: bool = True
    fetch_mode: str = "per_day"


def is_per_symbol_task(provider: str, task_name: str) -> bool:
    """判断指定数据源与任务是否属于按标的代码拉取模式 (per_symbol)。

    按标的拉取模式支持单次抓取整段历史范围，而按交易日拉取模式 (per_day) 则按天并发拉取全市场。
    """
    prov = provider.lower()
    name = task_name.strip()

    if prov in ("fred", "yfinance"):
        return True

    per_symbol_datasets = {
        "index_daily",
        "index_dailybasic",
        "index_weight",
        "global_index_daily",
        "fund_share",
        "income",
        "fina_indicator",
        "margin_detail",
        "hk_hold",
    }
    if name in per_symbol_datasets:
        return True

    try:
        task = resolve_task(prov, name)
        if task.dataset in per_symbol_datasets or task.task_name in per_symbol_datasets:
            return True
        return task.fetch_mode == "per_symbol"
    except Exception:
        return False


def is_task_partitioned(provider: str, task_or_dataset: str) -> bool:
    """判断指定数据源与数据集/任务是否采用 Hive 年月时间分桶存储。

    非分区数据集（如静态基本信息表、宏观单次快照等）直接存储于 ``dataset/data.parquet``。
    """
    prov = provider.lower()
    name = task_or_dataset.strip()

    # 全局免分区分桶数据源
    if prov in ("fred", "lixinger"):
        return False

    # 显式免分区的低频/静态/单表数据集集合
    non_part_datasets = {
        "stock_basic",
        "index_basic",
        "index_classify",
        "index_member",
        "fund_basic",
        "cn_cpi",
        "cn_gdp",
        "cn_ppi",
        "cn_pmi",
        "cn_m",
        "sf_month",
        "shibor_lpr",
        "margin",
        "moneyflow_hsgt",
        "hsgt_top10",
        "index_daily_bar",
        "global_index_daily",
        "financials",
        "balance_sheet",
        "cashflow",
        "dividends",
        "splits",
        "index_valuation",
        "macro_indicators",
        "index_fundamental",
        "sw_2021_constituents",
        "sw_2021_fundamental",
        "company_fundamental",
        "fs_non_financial",
        "pledge_info",
    }
    if name in non_part_datasets:
        return False

    try:
        task = resolve_task(prov, name)
        if task.dataset in non_part_datasets:
            return False
        if task.frequency in ("static", "event") and task.dataset not in ("suspend_d", "index_weight"):
            return False
        return task.partitioned
    except Exception:
        return True


_CUSTOM_TASKS: dict[tuple[str, str], TaskSpec] = {
    ("mock", "stock_daily_bar"): TaskSpec(
        task_name="stock_daily_bar",
        provider="mock",
        api_name="daily",
        dataset="stock_daily_bar",
        quality_profile="bar",
    ),
    ("tushare", "stock_daily_bar"): TaskSpec(
        task_name="stock_daily_bar",
        provider="tushare",
        api_name="daily",
        dataset="stock_daily_bar",
        quality_profile="bar",
    ),
    ("tushare", "index_daily_bar"): TaskSpec(
        task_name="index_daily_bar",
        provider="tushare",
        api_name="index_daily",
        dataset="index_daily_bar",
        quality_profile="bar",
    ),
    ("yfinance", "macro_indicators"): TaskSpec(
        task_name="macro_indicators",
        provider="yfinance",
        api_name="macro_indicators",
        dataset="macro_indicators",
    ),
    ("fred", "macro_indicators"): TaskSpec(
        task_name="macro_indicators",
        provider="fred",
        api_name="macro_indicators",
        dataset="macro_indicators",
    ),
    ("yfinance", "stock_daily_bar"): TaskSpec(
        task_name="stock_daily_bar",
        provider="yfinance",
        api_name="history",
        dataset="stock_daily_bar",
        quality_profile="bar",
    ),
    ("yfinance", "index_daily_bar"): TaskSpec(
        task_name="index_daily_bar",
        provider="yfinance",
        api_name="history",
        dataset="index_daily_bar",
        quality_profile="bar",
    ),
    ("lixinger", "stock_daily_bar"): TaskSpec(
        task_name="stock_daily_bar",
        provider="lixinger",
        api_name="cn/company/candlestick",
        dataset="stock_daily_bar",
        quality_profile="bar",
    ),
    ("lixinger", "index_daily_bar"): TaskSpec(
        task_name="index_daily_bar",
        provider="lixinger",
        api_name="cn/index/candlestick",
        dataset="index_daily_bar",
        quality_profile="bar",
    ),
    ("lixinger", "company_fundamental"): TaskSpec(
        task_name="company_fundamental",
        provider="lixinger",
        api_name="cn/company/fundamental/non_financial",
        dataset="company_fundamental",
    ),
    ("lixinger", "index_fundamental"): TaskSpec(
        task_name="index_fundamental",
        provider="lixinger",
        api_name="cn/index/fundamental",
        dataset="index_fundamental",
    ),
    ("lixinger", "sw_2021_fundamental"): TaskSpec(
        task_name="sw_2021_fundamental",
        provider="lixinger",
        api_name="cn/industry/fundamental/sw_2021",
        dataset="sw_2021_fundamental",
    ),
    ("lixinger", "sw_2021_constituents"): TaskSpec(
        task_name="sw_2021_constituents",
        provider="lixinger",
        api_name="cn/industry/constituents/sw_2021",
        dataset="sw_2021_constituents",
    ),
    ("lixinger", "fs_non_financial"): TaskSpec(
        task_name="fs_non_financial",
        provider="lixinger",
        api_name="cn/company/fs/non_financial",
        dataset="fs_non_financial",
    ),
    ("lixinger", "pledge_info"): TaskSpec(
        task_name="pledge_info",
        provider="lixinger",
        api_name="cn/company/hot/ple",
        dataset="pledge_info",
    ),
}

_ALIASES: dict[tuple[str, str], str] = {
    ("mock", "daily"): "stock_daily_bar",
    ("mock", "daily_bar"): "stock_daily_bar",
    ("tushare", "daily"): "stock_daily_bar",
    ("tushare", "daily_bar"): "stock_daily_bar",
    ("yfinance", "history"): "stock_daily_bar",
    ("fred", "history"): "macro_indicators",
    ("lixinger", "cn/company/candlestick"): "stock_daily_bar",
    ("lixinger", "cn/index/candlestick"): "index_daily_bar",
    ("lixinger", "cn/company/fundamental/non_financial"): "company_fundamental",
    ("lixinger", "cn/index/fundamental"): "index_fundamental",
    ("lixinger", "cn/industry/fundamental/sw_2021"): "sw_2021_fundamental",
    ("lixinger", "cn/industry/constituents/sw_2021"): "sw_2021_constituents",
    ("lixinger", "cn/company/fs/non_financial"): "fs_non_financial",
    ("lixinger", "cn/company/hot/ple"): "pledge_info",
}

_DISABLED_TASKS = {"bak_daily"}


def _provider_registry(provider: str) -> dict[str, Any]:
    """按需加载 Provider 注册表，避免任务模块与各 Fetcher 形成循环依赖。"""
    if provider == "tushare":
        from stock.data.fetcher.tushare.registry import TUSHARE_API_REGISTRY

        return TUSHARE_API_REGISTRY
    if provider == "yfinance":
        from stock.data.fetcher.yfinance.registry import YFINANCE_API_REGISTRY

        return YFINANCE_API_REGISTRY
    if provider == "lixinger":
        from stock.data.fetcher.lixinger.registry import LIXINGER_API_REGISTRY

        return LIXINGER_API_REGISTRY
    if provider == "fred":
        from stock.data.fetcher.fred.registry import FRED_API_REGISTRY

        return FRED_API_REGISTRY
    return {}


def resolve_task(provider: str, task_name: str, symbol: str = "") -> TaskSpec:
    """解析公开任务名，并返回其唯一上游 API 路由。"""
    provider_name = provider.lower()
    requested = task_name.strip()
    if requested in _DISABLED_TASKS:
        raise ValueError(
            f"项目任务 [{provider_name}/{task_name}] 已停用；请使用 stock_daily_bar。"
        )
    if (provider_name, requested) in _ALIASES:
        requested = _ALIASES[(provider_name, requested)]

    custom = _CUSTOM_TASKS.get((provider_name, requested))
    if custom is not None:
        return custom

    registry = _provider_registry(provider_name)
    meta = registry.get(requested)
    if meta is None:
        if "/" in requested:
            raise ValueError(
                f"未知项目任务 [{provider_name}/{task_name}]。"
                "请使用项目任务名，不要直接传入上游接口路径。"
            )
        # 允许 Mock 和扩展 Provider 使用同名任务/API；长路径必须显式注册。
        return TaskSpec(
            task_name=requested,
            provider=provider_name,
            api_name=requested,
            dataset=requested,
        )

    raw_api_name = getattr(meta, "api_name", None) or getattr(meta, "series_id", requested)
    api_name = str(raw_api_name)
    return TaskSpec(
        task_name=requested,
        provider=provider_name,
        api_name=api_name,
        dataset=requested,
        frequency=getattr(meta, "frequency", "daily"),
        quality_profile=getattr(meta, "quality_profile", "generic"),
    )


def resolve_public_task(provider: str, task_name: str, symbol: str = "") -> TaskSpec:
    """解析 CLI/配置公开任务名，拒绝上游接口别名和路径。"""
    provider_name = provider.lower()
    requested = task_name.strip()
    if requested in _DISABLED_TASKS:
        raise ValueError(
            f"项目任务 [{provider_name}/{task_name}] 已停用；请使用 stock_daily_bar。"
        )
    if (provider_name, requested) in _ALIASES or "/" in requested:
        raise ValueError(
            f"[{provider_name}/{task_name}] 不是项目任务名；请使用已注册的短任务名。"
        )
    if (provider_name, requested) not in _CUSTOM_TASKS and requested not in _provider_registry(
        provider_name
    ):
        raise ValueError(
            f"[{provider_name}/{task_name}] 不是已注册的项目任务名；"
            "请使用项目任务注册表中的短任务名。"
        )
    return resolve_task(provider_name, requested, symbol=symbol)


def task_api_name(provider: str, task_name: str, symbol: str = "") -> str:
    """返回任务对应的真实上游 API 名称。"""
    return resolve_task(provider, task_name, symbol=symbol).api_name


def task_dataset(provider: str, task_name: str, symbol: str = "") -> str:
    """返回任务对应的唯一落盘数据集目录名。"""
    return resolve_task(provider, task_name, symbol=symbol).dataset


def is_bar_task(provider: str, task_name: str, symbol: str = "") -> bool:
    """判断任务是否使用行情 K 线清洗与契约。"""
    return resolve_task(provider, task_name, symbol=symbol).quality_profile == "bar"


def list_available_tasks(provider: str) -> list[str]:
    """返回指定数据源下所有已注册且未停用的公开任务名称列表。"""
    prov = provider.lower()
    tasks: list[str] = []

    for p, t in _CUSTOM_TASKS:
        if p == prov and t not in _DISABLED_TASKS and t not in tasks:
            tasks.append(t)

    registry = _provider_registry(prov)
    for name in registry:
        if name not in _DISABLED_TASKS and name not in tasks and "/" not in name:
            tasks.append(name)

    return tasks


def get_endpoint_market(provider: str, endpoint: str) -> str:
    """根据项目任务名解析上游接口，再获取归属市场。"""
    provider_lower = provider.lower()
    api_name = endpoint
    try:
        api_name = resolve_task(provider_lower, endpoint).api_name
    except ValueError:
        pass
    if provider_lower == "tushare":
        from stock.data.fetcher.tushare.registry import TUSHARE_API_REGISTRY

        meta = TUSHARE_API_REGISTRY.get(api_name)
        if meta and hasattr(meta, "market"):
            return str(meta.market)
        return "CN"
    if provider_lower == "yfinance":
        from stock.data.fetcher.yfinance.registry import YFINANCE_API_REGISTRY

        meta_yf = YFINANCE_API_REGISTRY.get(api_name)
        if meta_yf and hasattr(meta_yf, "market"):
            return str(meta_yf.market)
        return "US"
    if provider_lower == "lixinger":
        from stock.data.fetcher.lixinger.registry import LIXINGER_API_REGISTRY

        meta_lx = LIXINGER_API_REGISTRY.get(api_name)
        if meta_lx and hasattr(meta_lx, "market"):
            return str(meta_lx.market)
        return "HK" if api_name.startswith("hk") else "CN"
    if provider_lower == "fred":
        from stock.data.fetcher.fred.registry import FRED_API_REGISTRY

        meta_fr = FRED_API_REGISTRY.get(api_name)
        if meta_fr and hasattr(meta_fr, "market"):
            return str(meta_fr.market)
        return "US"
    return "MULTI"


def dataset_for_endpoint(endpoint: str, symbol: str = "", provider: str = "tushare") -> str:
    """返回项目任务对应的唯一数据集目录名。"""
    return task_dataset(provider, endpoint, symbol=symbol)
