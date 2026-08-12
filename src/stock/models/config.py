"""策略及业务 YAML 强类型 Pydantic Schema 定义模块。"""

from pydantic import BaseModel, Field


class UniverseConfig(BaseModel):
    """标的范围配置。"""

    symbols: list[str] = Field(min_length=1, description="股票或标的代码列表")


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


class DataConfig(BaseModel):
    """数据源与基准配置模型。"""

    default_benchmark_index_code: str = Field(
        default="000001", description="交易日历基准指数代码 (上证指数)"
    )
    default_source_mode: str = Field(default="tushare", description="默认主数据源")


class DataConfigFile(BaseModel):
    """数据 YAML 文件顶层包装模型。"""

    data: DataConfig
