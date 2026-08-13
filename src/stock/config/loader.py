"""YAML 配置文件加载与校验工具。"""

from pathlib import Path

import yaml

from stock.exceptions import DataValidationError
from stock.models.config import (
    DataConfig,
    DataConfigFile,
    SourceWatchlistConfig,
    StrategyConfig,
    StrategyConfigFile,
    WatchlistsConfig,
)


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


def _extract_code(item: object) -> str:
    """从字典或纯字符串中提取标的代码。"""
    if isinstance(item, dict):
        return str(item.get("code", "")).strip()
    return str(item).strip()


def load_watchlist_config(
    config_path: Path | str = "config/universe/watchlist.yaml",
) -> WatchlistsConfig:
    """从全系统唯一自选池配置文件加载并生成多数据源专用的 WatchlistsConfig。"""
    path = Path(config_path)
    if not path.exists():
        return WatchlistsConfig()

    try:
        with path.open("r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f)

        u_data = raw_data.get("universe", {}) if raw_data else {}
        a_shares = u_data.get("a_shares", {})
        global_assets = u_data.get("global", {})
        macro = u_data.get("macro", [])

        a_stocks = [_extract_code(s) for s in a_shares.get("stocks", []) if _extract_code(s)]
        a_indices = [_extract_code(i) for i in a_shares.get("indices", []) if _extract_code(i)]
        lx_stocks = [s.split(".")[0] for s in a_stocks]
        lx_indices = [i.split(".")[0] for i in a_indices]
        g_stocks = [_extract_code(s) for s in global_assets.get("stocks", []) if _extract_code(s)]
        g_indices = [_extract_code(i) for i in global_assets.get("indices", []) if _extract_code(i)]
        macro_series = [str(m).strip() for m in macro if str(m).strip()]

        return WatchlistsConfig(
            tushare=SourceWatchlistConfig(stocks=a_stocks, indices=a_indices),
            lixinger=SourceWatchlistConfig(stocks=lx_stocks, indices=lx_indices),
            yfinance=SourceWatchlistConfig(stocks=g_stocks, indices=g_indices),
            fred=SourceWatchlistConfig(macro_series=macro_series),
        )
    except Exception:
        return WatchlistsConfig()


def load_data_config(config_path: Path | str = "config/data.yaml") -> DataConfig:
    """从指定 YAML 文件加载并校验数据业务配置。

    若配置文件中未声明 watchlists，则自动无缝从统一自选池 (config/universe/watchlist.yaml) 注入。
    """
    path = Path(config_path)
    if not path.exists():
        cfg = DataConfig()
        cfg.watchlists = load_watchlist_config()
        return cfg

    try:
        with path.open("r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f)

        if not raw_data or "data" not in raw_data:
            cfg = DataConfig()
            cfg.watchlists = load_watchlist_config()
            return cfg

        data_dict = raw_data["data"]
        if "watchlists" not in data_dict or not data_dict["watchlists"]:
            data_dict["watchlists"] = load_watchlist_config().model_dump()

        raw_data["data"] = data_dict
        validated_file = DataConfigFile(**raw_data)
        return validated_file.data
    except Exception as e:
        raise DataValidationError(f"数据配置文件解析/校验失败 [{path}]: {e}") from e
