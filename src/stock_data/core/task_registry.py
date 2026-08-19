"""项目任务名与数据源 API 名称的显式路由表 (SSOT 统一注册模型)。"""

from dataclasses import dataclass
from typing import Any

from stock_data.core.task_bundles import expand_task_targets as _expand_task_targets
from stock_data.core.task_bundles import list_available_bundles as _list_available_bundles
from stock_data.core.task_bundles import resolve_bundle as _resolve_bundle
from stock_data.core.task_bundles import resolve_bundle_or_alias as _resolve_bundle_or_alias

list_available_bundles = _list_available_bundles
resolve_bundle = _resolve_bundle


@dataclass(frozen=True)
class TaskSpec:
    """一个公开项目任务到一个上游 API 的固定映射与调度行为契约。"""

    task_name: str
    provider: str
    api_name: str
    dataset: str
    frequency: str = "daily"
    quality_profile: str = "generic"
    partitioned: bool = True
    fetch_mode: str = "per_day"  # "per_day" | "per_symbol"
    is_single_sync: bool = False
    required_pool: str | None = None


# 向后兼容保留的集合别名（内部已统一由 TaskSpec 属性驱动）
PER_SYMBOL_DATASETS: frozenset[str] = frozenset(
    {
        "index_daily",
        "index_dailybasic",
        "index_weight",
        "global_index_daily",
        "fund_share",
        "fund_daily",
        "fund_adj",
        "etf_share_size",
        "income",
        "fina_indicator",
        "forecast",
        "express",
        "balancesheet",
        "cashflow",
        "margin_detail",
        "hk_hold",
    }
)

_EXPLICIT_NON_PARTITIONED: frozenset[str] = frozenset(
    {
        "stock_basic",
        "index_basic",
        "index_classify",
        "index_member",
        "fund_basic",
        "trade_cal",
        "cn_cpi",
        "cn_gdp",
        "cn_ppi",
        "cn_pmi",
        "cn_m",
        "sf_month",
        "shibor_lpr",
        "shibor",
        "cn_schedule",
        "fut_index_daily",
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
        "sw_2021_fs_non_financial",
        "sw_2021_fs_bank",
        "sw_2021_fs_security",
        "sw_2021_fs_insurance",
        "company_fundamental",
        "fs_non_financial",
        "fs_bank",
        "fs_security",
        "fs_insurance",
        "pledge_info",
        "national_debt",
        "interest_rates",
        "non_ferrous_metals",
        "crude_oil",
    }
)

_EXPLICIT_SINGLE_SYNC: frozenset[str] = frozenset(
    {
        "moneyflow_hsgt",
        "hsgt_top10",
        "margin",
        "suspend_d",
        "trade_cal",
        "cn_gdp",
        "cn_cpi",
        "cn_ppi",
        "cn_pmi",
        "cn_m",
        "sf_month",
        "shibor_lpr",
        "shibor",
        "cn_schedule",
        "fut_index_daily",
        "stock_basic",
        "index_basic",
        "index_classify",
        "index_member",
        "fund_basic",
        "sw_2021_constituents",
        "sw_2021_fundamental",
        "sw_2021_fs_non_financial",
        "sw_2021_fs_bank",
        "sw_2021_fs_security",
        "sw_2021_fs_insurance",
        "company_fundamental",
        "fs_non_financial",
        "fs_bank",
        "fs_security",
        "fs_insurance",
        "pledge_info",
        "national_debt",
        "interest_rates",
        "non_ferrous_metals",
        "crude_oil",
    }
)


def _make_spec(
    task: str,
    prov: str,
    api: str,
    dataset: str,
    qp: str = "generic",
    fetch_mode: str = "per_day",
    partitioned: bool = True,
    is_single_sync: bool = False,
    required_pool: str | None = None,
    frequency: str = "daily",
) -> TaskSpec:
    return TaskSpec(
        task_name=task,
        provider=prov,
        api_name=api,
        dataset=dataset,
        frequency=frequency,
        quality_profile=qp,
        fetch_mode=fetch_mode,
        partitioned=partitioned,
        is_single_sync=is_single_sync,
        required_pool=required_pool,
    )


_CUSTOM_TASKS: dict[tuple[str, str], TaskSpec] = {
    ("tushare", "stock_daily_bar"): _make_spec(
        "stock_daily_bar",
        "tushare",
        "daily",
        "stock_daily_bar",
        "bar",
        fetch_mode="per_day",
        partitioned=True,
    ),
    ("tushare", "hk_hold"): _make_spec(
        "hk_hold", "tushare", "hk_hold", "hk_hold", fetch_mode="per_day", partitioned=True
    ),
    ("tushare", "report_rc"): _make_spec(
        "report_rc", "tushare", "report_rc", "report_rc", fetch_mode="per_day", partitioned=True
    ),
    ("tushare", "forecast"): _make_spec(
        "forecast",
        "tushare",
        "forecast",
        "forecast",
        fetch_mode="per_day",
        partitioned=True,
        frequency="quarterly",
    ),
    ("tushare", "express"): _make_spec(
        "express",
        "tushare",
        "express",
        "express",
        fetch_mode="per_day",
        partitioned=True,
        frequency="quarterly",
    ),
    ("tushare", "index_daily_bar"): _make_spec(
        "index_daily_bar",
        "tushare",
        "index_daily",
        "index_daily_bar",
        "bar",
        fetch_mode="per_symbol",
        partitioned=False,
        is_single_sync=True,
    ),
    ("yfinance", "macro_indicators"): _make_spec(
        "macro_indicators",
        "yfinance",
        "macro_indicators",
        "macro_indicators",
        "macro",
        fetch_mode="per_symbol",
        partitioned=False,
        is_single_sync=True,
    ),
    ("alphavantage", "fx_daily"): _make_spec(
        "fx_daily",
        "alphavantage",
        "FX_DAILY",
        "macro_indicators",
        "macro",
        fetch_mode="per_symbol",
        partitioned=False,
        is_single_sync=True,
    ),
    ("yfinance", "index_valuation"): _make_spec(
        "index_valuation",
        "yfinance",
        "index_valuation",
        "index_valuation",
        fetch_mode="per_day",
        partitioned=False,
        is_single_sync=True,
    ),
    ("fred", "macro_indicators"): _make_spec(
        "macro_indicators",
        "fred",
        "macro_indicators",
        "macro_indicators",
        fetch_mode="per_symbol",
        partitioned=False,
        is_single_sync=True,
    ),
    ("yfinance", "stock_daily_bar"): _make_spec(
        "stock_daily_bar",
        "yfinance",
        "history",
        "stock_daily_bar",
        "bar",
        fetch_mode="per_symbol",
        partitioned=True,
    ),
    ("yfinance", "index_daily_bar"): _make_spec(
        "index_daily_bar",
        "yfinance",
        "history",
        "index_daily_bar",
        "bar",
        fetch_mode="per_symbol",
        partitioned=False,
    ),
    ("lixinger", "stock_daily_bar"): _make_spec(
        "stock_daily_bar",
        "lixinger",
        "cn/company/candlestick",
        "stock_daily_bar",
        "bar",
        fetch_mode="per_symbol",
        partitioned=False,
    ),
    ("lixinger", "index_daily_bar"): _make_spec(
        "index_daily_bar",
        "lixinger",
        "cn/index/candlestick",
        "index_daily_bar",
        "bar",
        fetch_mode="per_symbol",
        partitioned=False,
    ),
    ("lixinger", "company_fundamental"): _make_spec(
        "company_fundamental",
        "lixinger",
        "cn/company/fundamental/non_financial",
        "company_fundamental",
        fetch_mode="per_symbol",
        partitioned=False,
        is_single_sync=True,
    ),
    ("lixinger", "index_fundamental"): _make_spec(
        "index_fundamental",
        "lixinger",
        "cn/index/fundamental",
        "index_fundamental",
        fetch_mode="per_symbol",
        partitioned=False,
        is_single_sync=True,
    ),
    ("lixinger", "sw_2021_fundamental"): _make_spec(
        "sw_2021_fundamental",
        "lixinger",
        "cn/industry/fundamental/sw_2021",
        "sw_2021_fundamental",
        fetch_mode="per_symbol",
        partitioned=False,
        is_single_sync=True,
    ),
    ("lixinger", "sw_2021_l2_fundamental"): _make_spec(
        "sw_2021_l2_fundamental",
        "lixinger",
        "cn/industry/fundamental/sw_2021",
        "sw_2021_l2_fundamental",
        fetch_mode="per_symbol",
        partitioned=False,
        is_single_sync=True,
    ),
    ("lixinger", "sw_2021_constituents"): _make_spec(
        "sw_2021_constituents",
        "lixinger",
        "cn/industry/constituents/sw_2021",
        "sw_2021_constituents",
        fetch_mode="per_symbol",
        partitioned=False,
        is_single_sync=True,
    ),
    ("lixinger", "sw_2021_fs_non_financial"): _make_spec(
        "sw_2021_fs_non_financial",
        "lixinger",
        "cn/industry/fs/sw_2021/non_financial",
        "sw_2021_fs_non_financial",
        fetch_mode="per_symbol",
        partitioned=False,
        is_single_sync=True,
    ),
    ("lixinger", "sw_2021_fs_bank"): _make_spec(
        "sw_2021_fs_bank",
        "lixinger",
        "cn/industry/fs/sw_2021/bank",
        "sw_2021_fs_bank",
        fetch_mode="per_symbol",
        partitioned=False,
        is_single_sync=True,
    ),
    ("lixinger", "sw_2021_fs_security"): _make_spec(
        "sw_2021_fs_security",
        "lixinger",
        "cn/industry/fs/sw_2021/security",
        "sw_2021_fs_security",
        fetch_mode="per_symbol",
        partitioned=False,
        is_single_sync=True,
    ),
    ("lixinger", "sw_2021_fs_insurance"): _make_spec(
        "sw_2021_fs_insurance",
        "lixinger",
        "cn/industry/fs/sw_2021/insurance",
        "sw_2021_fs_insurance",
        fetch_mode="per_symbol",
        partitioned=False,
        is_single_sync=True,
    ),
    ("lixinger", "fs_non_financial"): _make_spec(
        "fs_non_financial",
        "lixinger",
        "cn/company/fs/non_financial",
        "fs_non_financial",
        fetch_mode="per_symbol",
        partitioned=False,
        is_single_sync=True,
    ),
    ("lixinger", "fs_bank"): _make_spec(
        "fs_bank",
        "lixinger",
        "cn/company/fs/bank",
        "fs_bank",
        fetch_mode="per_symbol",
        partitioned=False,
        is_single_sync=True,
    ),
    ("lixinger", "fs_security"): _make_spec(
        "fs_security",
        "lixinger",
        "cn/company/fs/security",
        "fs_security",
        fetch_mode="per_symbol",
        partitioned=False,
        is_single_sync=True,
    ),
    ("lixinger", "fs_insurance"): _make_spec(
        "fs_insurance",
        "lixinger",
        "cn/company/fs/insurance",
        "fs_insurance",
        fetch_mode="per_symbol",
        partitioned=False,
        is_single_sync=True,
    ),
    ("lixinger", "pledge_info"): _make_spec(
        "pledge_info",
        "lixinger",
        "cn/company/hot/ple",
        "pledge_info",
        fetch_mode="per_symbol",
        partitioned=False,
        is_single_sync=True,
    ),
    ("lixinger", "national_debt"): _make_spec(
        "national_debt",
        "lixinger",
        "macro/national-debt",
        "national_debt",
        fetch_mode="per_symbol",
        partitioned=False,
        is_single_sync=True,
    ),
    ("lixinger", "interest_rates"): _make_spec(
        "interest_rates",
        "lixinger",
        "macro/interest-rates",
        "interest_rates",
        fetch_mode="per_symbol",
        partitioned=False,
        is_single_sync=True,
    ),
    ("lixinger", "non_ferrous_metals"): _make_spec(
        "non_ferrous_metals",
        "lixinger",
        "macro/non-ferrous-metals",
        "non_ferrous_metals",
        fetch_mode="per_symbol",
        partitioned=False,
        is_single_sync=True,
    ),
    ("lixinger", "crude_oil"): _make_spec(
        "crude_oil",
        "lixinger",
        "macro/crude-oil",
        "crude_oil",
        fetch_mode="per_symbol",
        partitioned=False,
        is_single_sync=True,
    ),
    ("lixinger", "investor_accounts"): TaskSpec(
        task_name="investor_accounts",
        provider="lixinger",
        api_name="macro/investor",
        dataset="investor_accounts",
        frequency="monthly",
        fetch_mode="per_day",
        partitioned=False,
        is_single_sync=True,
    ),
    ("lixinger", "cn_m"): TaskSpec(
        task_name="cn_m",
        provider="lixinger",
        api_name="macro/money-supply",
        dataset="cn_m",
        frequency="monthly",
        quality_profile="macro_monthly",
        fetch_mode="per_day",
        partitioned=False,
        is_single_sync=True,
    ),
    ("lixinger", "sf_month"): TaskSpec(
        task_name="sf_month",
        provider="lixinger",
        api_name="macro/social-financing",
        dataset="sf_month",
        frequency="monthly",
        quality_profile="macro_monthly",
        fetch_mode="per_day",
        partitioned=False,
        is_single_sync=True,
    ),
}
_ALIASES: dict[tuple[str, str], str] = {
    ("tushare", "daily"): "stock_daily_bar",
    ("tushare", "daily_bar"): "stock_daily_bar",
    ("tushare", "index_daily"): "index_daily_bar",
    ("yfinance", "history"): "stock_daily_bar",
    ("alphavantage", "FX_DAILY"): "fx_daily",
    ("alphavantage", "macro_indicators"): "fx_daily",
    ("fred", "history"): "macro_indicators",
    ("lixinger", "cn/company/candlestick"): "stock_daily_bar",
    ("lixinger", "cn/index/candlestick"): "index_daily_bar",
    ("lixinger", "cn/company/fundamental/non_financial"): "company_fundamental",
    ("lixinger", "cn/index/fundamental"): "index_fundamental",
    ("lixinger", "cn/industry/fundamental/sw_2021"): "sw_2021_fundamental",
    ("lixinger", "cn/industry/constituents/sw_2021"): "sw_2021_constituents",
    ("lixinger", "cn/company/fs/non_financial"): "fs_non_financial",
    ("lixinger", "cn/company/hot/ple"): "pledge_info",
    ("lixinger", "macro/national-debt"): "national_debt",
    ("lixinger", "macro/interest-rates"): "interest_rates",
    ("lixinger", "macro/non-ferrous-metals"): "non_ferrous_metals",
    ("lixinger", "macro/crude-oil"): "crude_oil",
    ("lixinger", "macro/investor"): "investor_accounts",
    ("lixinger", "macro/money-supply"): "cn_m",
    ("lixinger", "macro/social-financing"): "sf_month",
}

_DISABLED_TASKS = {"bak_daily", "stk_account"}
_EXPLICIT_ONLY_TASKS = {("fred", "macro_indicators")}


def expand_task_targets(provider: str, endpoints: list[str] | None = None) -> list[str]:
    """展开任务包，并保留任务注册表的别名规范化行为。"""
    if not endpoints:
        return list_available_tasks(provider)
    return _expand_task_targets(provider, endpoints, _ALIASES)


def _provider_registry(provider: str) -> dict[str, Any]:
    """按需加载 Provider 注册表，避免任务模块与各 Fetcher 形成循环依赖。"""
    registry_imports = {
        "tushare": ("stock_data.fetcher.tushare.registry", "TUSHARE_API_REGISTRY"),
        "yfinance": ("stock_data.fetcher.yfinance.registry", "YFINANCE_API_REGISTRY"),
        "lixinger": ("stock_data.fetcher.lixinger.registry", "LIXINGER_API_REGISTRY"),
        "fred": ("stock_data.fetcher.fred.registry", "FRED_API_REGISTRY"),
        "alphavantage": ("stock_data.fetcher.alphavantage.registry", "ALPHAVANTAGE_API_REGISTRY"),
    }
    module_path, registry_name = registry_imports.get(provider, ("", ""))
    if not module_path:
        return {}
    module = __import__(module_path, fromlist=[registry_name])
    return getattr(module, registry_name)  # type: ignore[no-any-return]


def _derive_task_spec(provider_name: str, requested: str, meta: Any) -> TaskSpec:
    """根据接口的 group、frequency 等原生元数据，通过约定优于配置自动推导调度与存储策略。"""
    raw_api_name = getattr(meta, "api_name", None) or getattr(meta, "series_id", requested)
    api_name = str(raw_api_name)
    group = str(getattr(meta, "group", ""))
    frequency = str(getattr(meta, "frequency", "daily"))
    qp = str(getattr(meta, "quality_profile", "generic"))

    # 1. 推导 fetch_mode 与 required_pool
    if provider_name in ("fred", "yfinance"):
        fetch_mode = "per_symbol"
        required_pool = None
    elif group in ("financial_statements", "financial_indicator") or requested in (
        "income",
        "fina_indicator",
        "forecast",
        "express",
        "balancesheet",
        "cashflow",
        "margin_detail",
        "hk_hold",
    ):
        fetch_mode = "per_symbol"
        required_pool = "stock_basic"
    elif group == "fund_share" or requested == "fund_share":
        fetch_mode = "per_symbol"
        required_pool = "fund_basic"
    elif requested in (
        "index_daily",
        "index_dailybasic",
        "index_weight",
        "global_index_daily",
        "fund_daily",
        "fund_adj",
        "etf_share_size",
    ):
        fetch_mode = "per_symbol"
        required_pool = None
    else:
        fetch_mode = getattr(meta, "fetch_mode", "per_day")
        required_pool = None

    # 2. 推导 partitioned (是否采用 Hive 年月分桶)
    if (
        provider_name in ("fred", "lixinger")
        or requested in _EXPLICIT_NON_PARTITIONED
        or group in ("macro_data", "basic_info")
        or (frequency in ("static", "event") and requested not in ("suspend_d", "index_weight"))
    ):
        partitioned = False
    else:
        partitioned = True

    # 3. 推导 is_single_sync (是否单表/宏观全量一次性同步)
    if (
        requested in _EXPLICIT_SINGLE_SYNC
        or group in ("macro_data", "basic_info")
        or (
            frequency in ("monthly", "quarterly", "event", "static")
            and group
            not in ("financial_statements", "financial_indicator", "market_data", "fund_market")
            and requested
            not in ("income", "fina_indicator", "forecast", "express", "balancesheet", "cashflow")
        )
    ):
        is_single_sync = True
    else:
        is_single_sync = False

    return TaskSpec(
        task_name=requested,
        provider=provider_name,
        api_name=api_name,
        dataset="macro_indicators" if provider_name == "fred" else requested,
        frequency=frequency,
        quality_profile=qp,
        fetch_mode=fetch_mode,
        partitioned=partitioned,
        is_single_sync=is_single_sync,
        required_pool=required_pool,
    )


def resolve_task(provider: str, task_name: str, symbol: str = "") -> TaskSpec:
    """解析公开任务名，并返回其唯一上游 API 路由及完整调度契约。"""
    provider_name = provider.lower()
    requested = task_name.strip()
    if requested in _DISABLED_TASKS:
        raise ValueError(f"项目任务 [{provider_name}/{task_name}] 已停用；请使用 stock_daily_bar。")
    if _resolve_bundle_or_alias(provider_name, requested) is not None:
        raise ValueError(
            f"[{provider_name}/{task_name}] 是任务包，不是原子任务；"
            "请先通过 expand_task_targets 展开。"
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
        # 允许扩展 Provider 使用同名任务/API；长路径必须显式注册。
        return TaskSpec(
            task_name=requested,
            provider=provider_name,
            api_name=requested,
            dataset=requested,
        )

    return _derive_task_spec(provider_name, requested, meta)


def is_per_symbol_task(provider: str, task_name: str) -> bool:
    """判断指定数据源与任务是否属于按标的代码拉取模式 (per_symbol)。"""
    try:
        return resolve_task(provider, task_name).fetch_mode == "per_symbol"
    except Exception:
        return provider.lower() in ("fred", "yfinance")


def is_task_partitioned(provider: str, task_or_dataset: str) -> bool:
    """判断指定数据源与数据集/任务是否采用 Hive 年月时间分桶存储。"""
    try:
        return resolve_task(provider, task_or_dataset).partitioned
    except Exception:
        return provider.lower() not in ("fred", "lixinger")


def resolve_public_task(provider: str, task_name: str, symbol: str = "") -> TaskSpec:
    """解析 CLI/配置公开任务名，拒绝上游接口别名和路径。"""
    provider_name = provider.lower()
    requested = task_name.strip()
    if requested in _DISABLED_TASKS:
        raise ValueError(f"项目任务 [{provider_name}/{task_name}] 已停用；请使用 stock_daily_bar。")
    if _resolve_bundle_or_alias(provider_name, requested) is not None:
        raise ValueError(
            f"[{provider_name}/{task_name}] 是任务包，不是公开原子任务；请在调度入口中展开。"
        )
    if (provider_name, requested) in _ALIASES or "/" in requested:
        raise ValueError(f"[{provider_name}/{task_name}] 不是项目任务名；请使用已注册的短任务名。")
    if (provider_name, requested) not in _CUSTOM_TASKS and requested not in _provider_registry(
        provider_name
    ):
        raise ValueError(
            f"[{provider_name}/{task_name}] 不是已注册的项目任务名；"
            "请使用项目任务注册表中的短任务名。"
        )
    return resolve_task(provider_name, requested, symbol=symbol)


def expand_public_task_targets(provider: str, endpoints: list[str] | None = None) -> list[str]:
    provider_name = provider.lower()
    if not endpoints:
        return list_available_tasks(provider_name)
    candidates = [
        candidate
        for endpoint in endpoints
        if (requested := endpoint.strip())
        for candidate in (
            expand_task_targets(provider_name, [requested])
            if _resolve_bundle_or_alias(provider_name, requested) is not None
            else [requested]
        )
    ]
    return list(dict.fromkeys(resolve_public_task(provider_name, c).task_name for c in candidates))


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
    alias_names = {alias for alias_provider, alias in _ALIASES if alias_provider == prov}

    for p, t in _CUSTOM_TASKS:
        if (
            p == prov
            and (p, t) not in _EXPLICIT_ONLY_TASKS
            and t not in _DISABLED_TASKS
            and t not in alias_names
            and t not in tasks
        ):
            tasks.append(t)

    registry = _provider_registry(prov)
    for name in registry:
        if (
            name not in _DISABLED_TASKS
            and name not in alias_names
            and name not in tasks
            and "/" not in name
        ):
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
        from stock_data.fetcher.tushare.registry import TUSHARE_API_REGISTRY

        meta = TUSHARE_API_REGISTRY.get(api_name)
        if meta and hasattr(meta, "market"):
            return str(meta.market)
        return "CN"
    if provider_lower == "yfinance":
        from stock_data.fetcher.yfinance.registry import YFINANCE_API_REGISTRY

        meta_yf = YFINANCE_API_REGISTRY.get(api_name)
        if meta_yf and hasattr(meta_yf, "market"):
            return str(meta_yf.market)
        return "US"
    if provider_lower == "lixinger":
        from stock_data.fetcher.lixinger.registry import LIXINGER_API_REGISTRY

        meta_lx = LIXINGER_API_REGISTRY.get(api_name)
        if meta_lx and hasattr(meta_lx, "market"):
            return str(meta_lx.market)
        return "HK" if api_name.startswith("hk") else "CN"
    if provider_lower == "fred":
        from stock_data.fetcher.fred.registry import FRED_API_REGISTRY

        meta_fr = FRED_API_REGISTRY.get(api_name)
        if meta_fr and hasattr(meta_fr, "market"):
            return str(meta_fr.market)
        return "US"
    if provider_lower == "alphavantage":
        meta = _provider_registry(provider_lower).get(api_name)
        return str(getattr(meta, "market", "GLOBAL"))
    return "MULTI"


def dataset_for_endpoint(endpoint: str, symbol: str = "", provider: str = "tushare") -> str:
    """返回项目任务对应的唯一数据集目录名。"""
    return task_dataset(provider, endpoint, symbol=symbol)
