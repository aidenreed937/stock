"""YAML 配置文件加载与校验工具。"""

from pathlib import Path

import yaml

from stock.exceptions import DataValidationError
from stock.models.config import StrategyConfig, StrategyConfigFile


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
