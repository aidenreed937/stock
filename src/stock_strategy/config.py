"""策略与风控强类型配置模型与 YAML 加载器。"""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from stock_core.exceptions import DataValidationError
from stock_core.models.config import UniverseConfig


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


def load_strategy_config(config_path: Path | str) -> StrategyConfig:
    """从指定 YAML 文件安全加载并校验策略配置（支持级联引入子配置文件）。

    Args:
        config_path: 配置文件路径。

    Returns:
        StrategyConfig: 校验通过的策略强类型配置对象。

    Raises:
        FileNotFoundError: 配置文件不存在。
        DataValidationError: YAML 解析失败或 Schema 校验不匹配。
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"策略配置文件不存在: {path}")

    try:
        with path.open("r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f)

        if not raw_data or "strategy" not in raw_data:
            raise DataValidationError("YAML 文件缺少顶层 'strategy' 键")

        strategy_data = raw_data["strategy"]

        # 1. 级联解析股票池配置 (Universe)
        u_path_str = strategy_data.get("universe_config_path")
        if u_path_str:
            u_path = (path.parent / u_path_str).resolve()
            if not u_path.exists():
                raise FileNotFoundError(f"级联引用的股票池配置文件不存在: {u_path}")
            with u_path.open("r", encoding="utf-8") as f:
                u_data = yaml.safe_load(f)
            if u_data and "universe" in u_data:
                strategy_data["universe"] = u_data["universe"]

        # 2. 级联解析风控配置 (Risk Management)
        r_path_str = strategy_data.get("risk_config_path")
        if r_path_str:
            r_path = (path.parent / r_path_str).resolve()
            if not r_path.exists():
                raise FileNotFoundError(f"级联引用的风控配置文件不存在: {r_path}")
            with r_path.open("r", encoding="utf-8") as f:
                r_data = yaml.safe_load(f)
            if r_data and "risk_management" in r_data:
                strategy_data["risk_management"] = r_data["risk_management"]

        # 回写数据供 Pydantic 校验
        raw_data["strategy"] = strategy_data

        validated_file = StrategyConfigFile(**raw_data)
        return validated_file.strategy
    except Exception as e:
        raise DataValidationError(f"策略配置文件解析/校验失败 [{path}]: {e}") from e
