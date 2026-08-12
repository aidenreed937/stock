"""策略及业务 YAML 强类型 Pydantic Schema 定义模块。"""

from pydantic import BaseModel, Field


class UniverseConfig(BaseModel):
    """标的范围配置（支持股票与指数解耦）。"""

    stocks: list[str] = Field(default_factory=list, description="股票代码列表")
    indices: list[str] = Field(default_factory=list, description="指数代码列表")
    symbols: list[str] = Field(default_factory=list, description="兼容旧配置的单列表")

    @property
    def all_symbols(self) -> list[str]:
        """合并并去重返回全量标的代码列表。"""
        if self.symbols:
            return self.symbols
        seen: set[str] = set()
        result: list[str] = []
        for item in self.stocks + self.indices:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result


class SourceWatchlistConfig(BaseModel):
    """单数据源观察池配置。"""

    stocks: list[str] = Field(default_factory=list)
    indices: list[str] = Field(default_factory=list)
    macro_series: list[str] = Field(default_factory=list)

    @property
    def all_symbols(self) -> list[str]:
        """按配置顺序去重返回该数据源包含的所有标的代码。"""
        seen: set[str] = set()
        res: list[str] = []
        for s in self.stocks + self.indices + self.macro_series:
            if s not in seen:
                seen.add(s)
                res.append(s)
        return res


class WatchlistsConfig(BaseModel):
    """数据源观察池总体配置。"""

    yfinance: SourceWatchlistConfig = Field(
        default_factory=lambda: SourceWatchlistConfig(
            stocks=["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"],
            indices=["^GSPC", "^IXIC", "^DJI", "^SOX", "^RUT", "^N225", "^KS11", "^HSI", "^TWII"],
        ),
        description="yfinance 重点观察代码列表",
    )
    tushare: SourceWatchlistConfig = Field(
        default_factory=lambda: SourceWatchlistConfig(
            stocks=["600519.SH", "000001.SZ"],
            indices=[
                "000001.SH",
                "399001.SZ",
                "000300.SH",
                "000905.SH",
                "000852.SH",
                "399006.SZ",
                "399102.SZ",
                "000985.CSI",
                "000922.CSI",
                "000688.SH",
            ],
        ),
        description="tushare 重点观察代码列表",
    )
    lixinger: SourceWatchlistConfig = Field(
        default_factory=lambda: SourceWatchlistConfig(
            stocks=["600519", "000001"],
            indices=[],
        ),
        description="理杏仁重点观察代码列表",
    )
    fred: SourceWatchlistConfig = Field(
        default_factory=lambda: SourceWatchlistConfig(
            macro_series=[
                "FEDFUNDS",
                "CPIAUCSL",
                "UNRATE",
                "PAYEMS",
                "GDP",
                "T10Y2Y",
                "WALCL",
            ],
        ),
        description="FRED 重点观察宏观指标列表",
    )


class SMAIndicatorConfig(BaseModel):
    """SMA 均线配置。"""

    fast_period: int = Field(default=5, gt=0, description="快线周期")
    slow_period: int = Field(default=20, gt=0, description="慢线周期")


class RSIIndicatorConfig(BaseModel):
    """RSI 指标配置。"""

    period: int = Field(default=14, gt=0, description="计算周期")
    oversold: float = Field(default=30.0, ge=0.0, le=100.0, description="超卖阈值")
    overbought: float = Field(default=70.0, ge=0.0, le=100.0, description="超买阈值")


class IndicatorsConfig(BaseModel):
    """技术指标组合配置。"""

    sma: SMAIndicatorConfig = Field(default_factory=SMAIndicatorConfig)
    rsi: RSIIndicatorConfig = Field(default_factory=RSIIndicatorConfig)


class RiskManagementConfig(BaseModel):
    """风控管理配置。"""

    max_position_per_symbol: float = Field(
        default=0.2, gt=0.0, le=1.0, description="单标的最大持仓上限比例"
    )
    stop_loss_pct: float = Field(default=0.05, gt=0.0, le=1.0, description="止损比例")
    take_profit_pct: float = Field(default=0.15, gt=0.0, le=1.0, description="止盈比例")


class StrategyConfig(BaseModel):
    """策略总体配置结构模型。"""

    name: str = Field(description="策略名称")
    version: str = Field(default="1.0.0", description="策略版本")
    description: str = Field(default="", description="策略描述")
    universe_config_path: str | None = Field(default=None, description="外部股票池配置文件相对路径")
    risk_config_path: str | None = Field(default=None, description="外部风控配置文件相对路径")
    universe: UniverseConfig = Field(description="股票池配置")
    indicators: IndicatorsConfig = Field(
        default_factory=IndicatorsConfig, description="技术指标配置"
    )
    risk_management: RiskManagementConfig = Field(
        default_factory=RiskManagementConfig, description="风控配置"
    )


class StrategyConfigFile(BaseModel):
    """YAML 文件顶层包装模型。"""

    strategy: StrategyConfig


class RateLimitsConfig(BaseModel):
    """数据源限频配置。"""

    tushare_per_min: int = Field(default=180, gt=0, description="TuShare 每分钟最大请求数")
    yfinance_per_min: int = Field(default=40, gt=0, description="YFinance 每分钟最大请求数")
    lixinger_per_min: int = Field(default=30, gt=0, description="理杏仁每分钟最大请求数")


class ConcurrencyConfig(BaseModel):
    """数据源并发数配置。"""

    tushare_max_workers: int = Field(default=4, gt=0, description="TuShare 抓取最大并发线程数")
    lixinger_max_workers: int = Field(default=4, gt=0, description="理杏仁抓取最大并发线程数")
    yfinance_max_workers: int = Field(default=4, gt=0, description="YFinance 抓取最大并发线程数")
    default_max_workers: int = Field(default=4, gt=0, description="默认通用抓取最大并发线程数")


class EndpointSymbolModesConfig(BaseModel):
    """接口采集模式路由配置。"""

    per_symbol_endpoints: list[str] = Field(
        default_factory=lambda: [
            "index_daily",
            "index_dailybasic",
            "index_weight",
            "global_index_daily",
            "fund_daily",
            "history",
        ],
        description="按标的按时间段采集的接口列表",
    )
    per_day_endpoints: list[str] = Field(
        default_factory=lambda: ["daily", "daily_basic", "moneyflow", "adj_factor"],
        description="按交易日全市场采集的接口列表",
    )


class DataConfig(BaseModel):
    """数据源与基准配置模型。"""

    default_benchmark_index_code: str = Field(
        default="000001", description="交易日历基准指数代码 (上证指数)"
    )
    default_source_mode: str = Field(default="tushare", description="默认主数据源")
    rate_limits: RateLimitsConfig = Field(default_factory=RateLimitsConfig)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    watchlists: WatchlistsConfig = Field(default_factory=WatchlistsConfig)
    endpoint_symbol_modes: EndpointSymbolModesConfig = Field(
        default_factory=EndpointSymbolModesConfig
    )
    source_endpoint_supports: dict[str, dict[str, list[str]]] = Field(default_factory=dict)


class DataConfigFile(BaseModel):
    """数据 YAML 文件顶层包装模型。"""

    data: DataConfig
