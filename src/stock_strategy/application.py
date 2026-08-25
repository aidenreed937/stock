"""策略研究应用 Facade。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from stock_core.config.loader import load_data_config
from stock_core.utils.logger import logger
from stock_data import create_pipeline, data_settings
from stock_strategy.config import load_strategy_config
from stock_strategy.runner import SignalReport, StrategyRunner

DEFAULT_STRATEGY_CONFIG_PATH = Path("config/strategy/double_sma_rsi.yaml")


@dataclass(frozen=True)
class StrategyApplicationResult:
    """一次策略研究应用运行的结构化结果。"""

    strategy_name: str
    strategy_version: str
    query_rows: int
    report: SignalReport


def parse_config_date(value: str, today: date) -> date | None:
    """解析策略应用使用的数据窗口日期。"""
    clean = value.strip().lower()
    if not clean:
        return None
    if clean == "today":
        return today
    if clean.startswith("today-"):
        offset = clean.removeprefix("today-").removesuffix("d")
        return today - timedelta(days=int(offset)) if offset.isdigit() else None
    return date.fromisoformat(clean)


def run_strategy_application(
    config_path: Path | str = DEFAULT_STRATEGY_CONFIG_PATH,
) -> StrategyApplicationResult:
    """加载配置、准备数据并运行策略研究。"""
    data_settings.setup_directories()
    strategy_config = load_strategy_config(config_path)
    data_config = load_data_config()
    logger.info(f"成功加载策略配置: [{strategy_config.name}] v{strategy_config.version}")

    today = date.today()
    end_date = parse_config_date(data_config.backfill.default_end_date, today) or today
    start_date = parse_config_date(data_config.backfill.default_start_date, today) or (
        end_date - timedelta(days=30)
    )
    pipeline = create_pipeline(data_config.default_source_mode, endpoint="stock_daily_bar")
    frames = [
        pipeline.sync_daily_bars(symbol, start_date, end_date)
        for symbol in strategy_config.universe.all_symbols
    ]
    bars_df = pl.concat(frames, how="diagonal_relaxed")
    query_result = pipeline.store.query_history(
        endpoint="stock_daily_bar",
        symbols=strategy_config.universe.all_symbols,
    )
    logger.info(f"DuckDB SQL 查询结果: 共 {len(query_result)} 条缓存记录")

    report = StrategyRunner(strategy_config, pipeline.data_source).run(bars_df)
    return StrategyApplicationResult(
        strategy_name=strategy_config.name,
        strategy_version=strategy_config.version,
        query_rows=len(query_result),
        report=report,
    )


__all__ = [
    "DEFAULT_STRATEGY_CONFIG_PATH",
    "StrategyApplicationResult",
    "parse_config_date",
    "run_strategy_application",
]
