"""YAML 配置文件加载与校验工具。"""

from pathlib import Path

import yaml

from stock_core.exceptions import DataValidationError
from stock_core.models.config import (
    DataConfig,
    DataConfigFile,
    SourceWatchlistConfig,
    WatchlistsConfig,
)


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
        a_funds = [_extract_code(f) for f in a_shares.get("funds", []) if _extract_code(f)]
        lx_stocks = [s.split(".")[0] for s in a_stocks]
        lx_indices = [i.split(".")[0] for i in a_indices]
        g_stocks = [_extract_code(s) for s in global_assets.get("stocks", []) if _extract_code(s)]
        g_indices = [_extract_code(i) for i in global_assets.get("indices", []) if _extract_code(i)]
        macro_series = [str(m).strip() for m in macro if str(m).strip()]

        ts_base_dates: dict[str, str] = {}
        lx_base_dates: dict[str, str] = {}
        lx_stock_base_dates: dict[str, str] = {}
        lx_index_base_dates: dict[str, str] = {}
        lx_fund_base_dates: dict[str, str] = {}
        categorized_items = (
            ("stock", a_shares.get("stocks", [])),
            ("index", a_shares.get("indices", [])),
            ("fund", a_shares.get("funds", [])),
        )
        category_maps = {
            "stock": lx_stock_base_dates,
            "index": lx_index_base_dates,
            "fund": lx_fund_base_dates,
        }
        for category, items in categorized_items:
            for item in items:
                if isinstance(item, dict) and item.get("code") and item.get("base_date"):
                    code = str(item["code"]).strip()
                    d_val = str(item["base_date"]).strip()
                    ts_base_dates[code] = d_val
                    short_code = code.split(".")[0]
                    category_maps[category][short_code] = d_val
                    # 保留单参数调用的兼容语义，重复短代码优先采用股票基准日。
                    lx_base_dates.setdefault(short_code, d_val)

        return WatchlistsConfig(
            tushare=SourceWatchlistConfig(
                stocks=a_stocks, indices=a_indices, funds=a_funds, base_dates=ts_base_dates
            ),
            lixinger=SourceWatchlistConfig(
                stocks=lx_stocks,
                indices=lx_indices,
                funds=a_funds,
                base_dates=lx_base_dates,
                stock_base_dates=lx_stock_base_dates,
                index_base_dates=lx_index_base_dates,
                fund_base_dates=lx_fund_base_dates,
            ),
            yfinance=SourceWatchlistConfig(stocks=g_stocks, indices=g_indices),
            fred=SourceWatchlistConfig(macro_series=macro_series),
            alphavantage=SourceWatchlistConfig(macro_series=["CNH=X"]),
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
