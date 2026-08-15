"""历史数据回填任务规划器 (BackfillPlanner)。

统一负责标的池解析、观察池路由、上市基日 (base_date) 对齐与不可变原子任务 (BackfillTask) 编排。
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

from stock.constants import ENDPOINT_START_DATE_OVERRIDES
from stock.data.task_registry import (
    list_available_tasks,
    resolve_task,
)
from stock.exceptions import DataFetchError
from stock.utils.logger import logger


@dataclass(frozen=True)
class BackfillTask:
    """不可变原子回填任务。"""

    data_source: str
    endpoint: str
    symbol: str
    start_date: date
    end_date: date
    fetch_mode: str  # "per_symbol" | "per_day"
    is_single_sync: bool


def _load_curated_symbol_pool(data_source: str, dataset: str) -> list[str]:
    """从本地基础信息数据集加载可用于按标的回填的标准代码。"""
    from stock.data.storage.duckdb_store import DuckDBMarketStore

    frame = DuckDBMarketStore(data_source=data_source).query_dataset(dataset=dataset)
    if frame.is_empty():
        return []
    sym_col = next(
        (c for c in ("symbol", "ts_code", "stockCode", "code") if c in frame.columns), None
    )
    if not sym_col:
        return []
    vals = frame.get_column(sym_col).drop_nulls().to_list()
    return sorted({str(s).strip() for s in vals if str(s).strip()})


def _resolve_required_local_pool(data_source: str, endpoint: str) -> tuple[str, str] | None:
    """从任务元数据解析所需本地基础池及其缺失提示。"""
    try:
        task_spec = resolve_task(data_source, endpoint)
        if task_spec.required_pool == "stock_basic":
            return "stock_basic", "A 股"
        if task_spec.required_pool == "fund_basic":
            return "fund_basic", "基金"
    except Exception:
        pass
    return None


_INDEX_ENDPOINTS = {
    "index_daily",
    "index_dailybasic",
    "index_weight",
    "global_index_daily",
    "index_daily_bar",
    "index_valuation",
    "index_fundamental",
}
_FUND_ENDPOINTS = {"fund_daily", "fund_adj", "fund_share", "etf_share_size"}
_YFINANCE_MACRO_SYMBOLS = ["^TNX", "^IRX", "DX-Y.NYB", "CNH=X", "GC=F", "CL=F", "HG=F", "^VIX"]
_LIXINGER_COMPANY_ENDPOINTS = {
    "company_fundamental",
    "fs_non_financial",
    "fs_bank",
    "fs_security",
    "fs_insurance",
    "pledge_info",
}
_LIXINGER_BATCH_SINGLE_ENDPOINTS = {
    "sw_2021_constituents",
    "sw_2021_fundamental",
    "sw_2021_l2_fundamental",
    "sw_2021_fs_non_financial",
    "sw_2021_fs_bank",
    "sw_2021_fs_security",
    "sw_2021_fs_insurance",
    "national_debt",
    "interest_rates",
    "non_ferrous_metals",
    "crude_oil",
}


def _watchlist_symbols(
    data_source: str,
    endpoint: str,
    data_cfg: Any,
    per_symbol_endpoints: set[str],
) -> list[str]:
    """从配置观察池解析接口的默认标的。"""
    watchlist = getattr(data_cfg.watchlists, data_source, None)
    if data_source == "yfinance" and endpoint == "macro_indicators":
        return _YFINANCE_MACRO_SYMBOLS
    if watchlist is None:
        return []
    if data_source == "fred":
        return list(getattr(watchlist, "macro_series", []) or [])
    if endpoint in _FUND_ENDPOINTS and getattr(watchlist, "funds", None):
        return list(watchlist.funds)
    if endpoint in _INDEX_ENDPOINTS and getattr(watchlist, "indices", None):
        return list(watchlist.indices)
    if getattr(watchlist, "stocks", None):
        return list(watchlist.stocks)
    if hasattr(watchlist, "all_symbols"):
        return list(watchlist.all_symbols)
    return list(watchlist) if isinstance(watchlist, list) else []


def _filter_supported_symbols(
    symbols: list[str], data_source: str, endpoint: str, data_cfg: Any
) -> list[str]:
    """按接口白名单过滤配置观察池。"""
    endpoint_supports = getattr(data_cfg, "source_endpoint_supports", {})
    supports = endpoint_supports.get(data_source, {}).get(endpoint, [])
    if not supports:
        return symbols
    support_set = set(supports)
    return [s for s in symbols if s in support_set]


def _default_symbols_for_endpoint(
    data_source: str,
    endpoint: str,
    data_cfg: Any,
    per_symbol_endpoints: set[str],
    is_watchlist_explicit: bool = False,
) -> list[str]:
    """计算接口的回填目标标的列表。"""
    import stock.data.backfill as bf_mod

    if not is_watchlist_explicit:
        local_pool_meta = _resolve_required_local_pool(data_source, endpoint)
        if local_pool_meta:
            pool_dataset, pool_label = local_pool_meta
            pool_fn = getattr(bf_mod, "_load_curated_symbol_pool", _load_curated_symbol_pool)
            local_symbols = pool_fn(data_source, pool_dataset)
            if not local_symbols:
                raise DataFetchError(
                    f"接口 [{endpoint}] 需要本地 {pool_dataset} {pool_label}标的池，"
                    f"请先完成 {pool_dataset} 回填"
                )
            return local_symbols

    symbols = _watchlist_symbols(data_source, endpoint, data_cfg, per_symbol_endpoints)
    return _filter_supported_symbols(symbols, data_source, endpoint, data_cfg)


def _resolve_target_symbols(
    data_source: str,
    public_name: str,
    symbol: str | None,
    is_per_sym: bool,
    is_single: bool,
    data_cfg: Any,
) -> list[str]:
    """解析当前接口需要遍历的目标标的代码列表。"""
    if symbol and symbol not in ("all", "watchlist"):
        return [s.strip() for s in symbol.split(",") if s.strip()]
    if not is_per_sym:
        # 单表全量同步或全局按日端点，保持单任务模式
        return [""]
    if is_single and not _should_expand_single_sync(data_source, public_name):
        return [""]
    is_watchlist_explicit = symbol == "watchlist"
    targets = _default_symbols_for_endpoint(
        data_source,
        public_name,
        data_cfg,
        {public_name},
        is_watchlist_explicit=is_watchlist_explicit,
    )
    return targets if targets else [""]


def _should_expand_single_sync(data_source: str, endpoint: str) -> bool:
    """判断 per-symbol single-sync 任务是否应按观察池拆成多个原子任务。"""
    if endpoint in _LIXINGER_BATCH_SINGLE_ENDPOINTS:
        return False
    if data_source in {"fred", "yfinance"}:
        return True
    if endpoint in _INDEX_ENDPOINTS or endpoint in _FUND_ENDPOINTS:
        return True
    return data_source == "lixinger" and endpoint in _LIXINGER_COMPANY_ENDPOINTS


class BackfillPlanner:
    """统一回填任务规划器。"""

    @classmethod
    def plan_tasks(
        cls,
        data_source: str,
        endpoints: list[str] | None,
        symbol: str | None,
        start_date: date,
        end_date: date,
        start_specified: bool,
        data_cfg: Any,
    ) -> list[BackfillTask]:
        """根据输入参数解析并生成原子回填任务列表。"""
        if not endpoints:
            targets = list_available_tasks(data_source)
            endpoints = ["stock_daily_bar"] if not targets else targets

        tasks: list[BackfillTask] = []
        src_watchlist = getattr(data_cfg.watchlists, data_source, None) if data_cfg else None

        for raw_ep in endpoints:
            task_spec = resolve_task(data_source, raw_ep)
            public_name = task_spec.task_name
            is_per_sym = task_spec.fetch_mode == "per_symbol"
            is_single = task_spec.is_single_sync

            targets = _resolve_target_symbols(
                data_source, public_name, symbol, is_per_sym, is_single, data_cfg
            )
            min_supported = cls._resolve_min_supported(data_source, public_name, data_cfg)

            for sym in targets:
                task_start = cls._compute_task_start_date(
                    start_date=start_date,
                    start_specified=start_specified,
                    is_per_sym=is_per_sym,
                    is_single=is_single,
                    frequency=task_spec.frequency,
                    sym=sym,
                    src_watchlist=src_watchlist,
                    min_supported=min_supported,
                )
                if task_start > end_date:
                    logger.info(
                        f"标的 [{sym or public_name}] 起始日 [{task_start}] "
                        f"晚于截止日 [{end_date}]，跳过"
                    )
                    continue

                tasks.append(
                    BackfillTask(
                        data_source=data_source,
                        endpoint=public_name,
                        symbol=sym,
                        start_date=task_start,
                        end_date=end_date,
                        fetch_mode="per_symbol" if is_per_sym else task_spec.fetch_mode,
                        is_single_sync=is_single,
                    )
                )
        return tasks

    @staticmethod
    def _resolve_min_supported(data_source: str, public_name: str, data_cfg: Any) -> date | None:
        start_overrides = (
            getattr(data_cfg, "endpoint_start_date_overrides", {}) or ENDPOINT_START_DATE_OVERRIDES
            if data_cfg
            else ENDPOINT_START_DATE_OVERRIDES
        )
        min_str = start_overrides.get(f"{data_source}:{public_name}") or start_overrides.get(
            public_name
        )
        return date.fromisoformat(min_str) if isinstance(min_str, str) else None

    @staticmethod
    def _compute_task_start_date(
        start_date: date,
        start_specified: bool,
        is_per_sym: bool,
        is_single: bool,
        frequency: str,
        sym: str,
        src_watchlist: Any,
        min_supported: date | None,
    ) -> date:
        task_start = start_date
        if not start_specified and (not is_per_sym or is_single or frequency != "daily"):
            task_start = date(1970, 1, 1)

        if sym and src_watchlist and hasattr(src_watchlist, "get_base_date"):
            try:
                base_d = src_watchlist.get_base_date(sym)
                if isinstance(base_d, date) and (not start_specified or base_d > task_start):
                    task_start = base_d
            except Exception as err:
                logger.debug(f"标的 [{sym}] 基准起始日提取异常: {err}")

        if min_supported and task_start < min_supported:
            task_start = min_supported
        return task_start
