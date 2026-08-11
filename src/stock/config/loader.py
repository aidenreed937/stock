"""YAML 配置文件加载与校验工具。"""

from pathlib import Path

import yaml

from stock.exceptions import DataValidationError
from stock.models.config import StrategyConfig, StrategyConfigFile


def load_strategy_config(config_path: Path | str) -> StrategyConfig:
    """从指定 YAML 文件安全加载并校验策略配置。

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

        validated_file = StrategyConfigFile(**raw_data)
        return validated_file.strategy
    except Exception as e:
        raise DataValidationError(f"策略配置文件解析/校验失败 [{path}]: {e}") from e
