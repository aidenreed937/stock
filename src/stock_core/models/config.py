from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator


def _parse_items_and_dates(items: list[object]) -> tuple[list[str], dict[str, str]]:
    codes: list[str] = []
    dates: dict[str, str] = {}
    for it in items:
        if isinstance(it, dict):
            c, d = str(it.get("code", "")).strip(), it.get("base_date")
        else:
            c, d = str(it).strip(), None
        if c:
            codes.append(c)
            if d:
                dates[c] = str(d).strip()
    return codes, dates


class UniverseConfig(BaseModel):
    """标的范围配置（支持股票、指数与基金解耦）。"""

    stocks: list[str] = Field(default_factory=list, description="股票代码列表")
    indices: list[str] = Field(default_factory=list, description="指数代码列表")
    funds: list[str] = Field(default_factory=list, description="基金代码列表")
    symbols: list[str] = Field(default_factory=list, description="兼容旧配置的单列表")
    base_dates: dict[str, str] = Field(default_factory=dict, description="标的基准起始日期映射")

    @model_validator(mode="before")
    @classmethod
    def extract_nested_universe(cls, data: object) -> dict[str, object]:
        """将多层级嵌套的统一自选池结构扁平提取。"""
        if not isinstance(data, dict):
            return {"stocks": [], "indices": [], "funds": [], "symbols": [], "base_dates": {}}

        raw_pools: dict[str, list[object]] = {
            "stocks": list(data.get("stocks", [])),
            "indices": list(data.get("indices", [])),
            "funds": list(data.get("funds", [])),
            "symbols": list(data.get("symbols", [])),
        }

        for scope in ("a_shares", "global"):
            sub = data.get(scope)
            if isinstance(sub, dict):
                for k in ("stocks", "indices", "funds"):
                    raw_pools[k].extend(sub.get(k, []))

        result: dict[str, object] = {}
        all_dates: dict[str, str] = {}
        for k, items in raw_pools.items():
            codes, dates = _parse_items_and_dates(items)
            result[k] = codes
            all_dates.update(dates)

        result["base_dates"] = all_dates
        return result

    @property
    def all_symbols(self) -> list[str]:
        """合并并去重返回全量标的代码列表。"""
        if self.symbols:
            return self.symbols
        seen: set[str] = set()
        result: list[str] = []
        for item in self.stocks + self.indices + self.funds:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result


class SourceWatchlistConfig(BaseModel):
    """单数据源观察池配置。"""

    stocks: list[str] = Field(default_factory=list)
    indices: list[str] = Field(default_factory=list)
    funds: list[str] = Field(default_factory=list)
    macro_series: list[str] = Field(default_factory=list)
    base_dates: dict[str, str] = Field(
        default_factory=dict, description="标的基准/上市起始日期映射"
    )
    stock_base_dates: dict[str, str] = Field(default_factory=dict)
    index_base_dates: dict[str, str] = Field(default_factory=dict)
    fund_base_dates: dict[str, str] = Field(default_factory=dict)

    def get_base_date(self, symbol: str, asset_type: str | None = None) -> date | None:
        """获取指定标的的起始基准日期，避免无意义的历史空范围请求。"""
        if not symbol:
            return None
        category_maps = {
            "stock": self.stock_base_dates,
            "stocks": self.stock_base_dates,
            "index": self.index_base_dates,
            "indices": self.index_base_dates,
            "fund": self.fund_base_dates,
            "funds": self.fund_base_dates,
        }
        selected = category_maps.get(asset_type or "", {})
        d_str = (
            selected.get(symbol)
            or selected.get(symbol.split(".")[0])
            or self.base_dates.get(symbol)
            or self.base_dates.get(symbol.split(".")[0])
        )
        if not d_str:
            return None
        try:
            clean = d_str.strip().replace("-", "")
            return datetime.strptime(clean, "%Y%m%d").date()
        except Exception:
            return None

    @property
    def all_symbols(self) -> list[str]:
        """按配置顺序去重返回该数据源包含的所有标的代码。"""
        seen: set[str] = set()
        res: list[str] = []
        for s in self.stocks + self.indices + self.funds + self.macro_series:
            if s not in seen:
                seen.add(s)
                res.append(s)
        return res


class WatchlistsConfig(BaseModel):
    """数据源观察池总体配置。"""

    yfinance: SourceWatchlistConfig = Field(default_factory=SourceWatchlistConfig)
    tushare: SourceWatchlistConfig = Field(default_factory=SourceWatchlistConfig)
    lixinger: SourceWatchlistConfig = Field(default_factory=SourceWatchlistConfig)
    fred: SourceWatchlistConfig = Field(default_factory=SourceWatchlistConfig)
    alphavantage: SourceWatchlistConfig = Field(default_factory=SourceWatchlistConfig)


class RateLimitsConfig(BaseModel):
    """数据源限频配置。"""

    tushare_per_min: int = Field(default=180, gt=0, description="TuShare 每分钟最大请求数")
    yfinance_per_min: int = Field(default=40, gt=0, description="YFinance 每分钟最大请求数")
    lixinger_per_min: int = Field(default=30, gt=0, description="理杏仁每分钟最大请求数")
    alpha_vantage_per_min: int = Field(
        default=5, gt=0, description="Alpha Vantage 每分钟最大请求数"
    )


class ConcurrencyConfig(BaseModel):
    """数据源并发数配置。"""

    tushare_max_workers: int = Field(default=4, gt=0, description="TuShare 抓取最大并发线程数")
    lixinger_max_workers: int = Field(default=4, gt=0, description="理杏仁抓取最大并发线程数")
    yfinance_max_workers: int = Field(default=4, gt=0, description="YFinance 抓取最大并发线程数")
    alphavantage_max_workers: int = Field(
        default=1, gt=0, description="Alpha Vantage 抓取最大并发线程数"
    )
    default_max_workers: int = Field(default=4, gt=0, description="默认通用抓取最大并发线程数")


class BackfillDefaultsConfig(BaseModel):
    """历史回填策略默认配置。"""

    default_start_date: str = Field(default="today-30d", description="默认回填起始日期")
    default_end_date: str = Field(default="today", description="默认回填结束日期")
    default_symbol: str = Field(default="all", description="默认回填标的范围")
    force_refresh: bool = Field(default=False, description="是否默认开启强制刷新")
    max_workers: int = Field(default=4, gt=0, description="回填默认并发线程数")


class DataConfig(BaseModel):
    """数据源与基准配置模型。"""

    default_benchmark_index_code: str = Field(
        default="000001", description="交易日历基准指数代码 (上证指数)"
    )
    default_source_mode: str = Field(default="tushare", description="默认主数据源")
    rate_limits: RateLimitsConfig = Field(default_factory=RateLimitsConfig)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    watchlists: WatchlistsConfig = Field(default_factory=WatchlistsConfig)
    backfill: BackfillDefaultsConfig = Field(default_factory=BackfillDefaultsConfig)
    source_endpoint_supports: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    endpoint_start_date_overrides: dict[str, str] = Field(default_factory=dict)


class DataConfigFile(BaseModel):
    """数据 YAML 文件顶层包装模型。"""

    data: DataConfig
