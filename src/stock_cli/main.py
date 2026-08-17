from datetime import date, timedelta
from pathlib import Path

import polars as pl

from stock_core.config.loader import load_data_config, load_strategy_config
from stock_core.config.settings import settings
from stock_core.utils.logger import logger, setup_logger
from stock_data.factory import create_pipeline
from stock_strategy.runner import StrategyRunner


def _parse_config_date(value: str, today: date) -> date | None:
    d_clean = value.strip().lower()
    if not d_clean:
        return None
    if d_clean == "today":
        return today
    if d_clean.startswith("today-"):
        offset = d_clean.removeprefix("today-").removesuffix("d")
        return today - timedelta(days=int(offset)) if offset.isdigit() else None
    return date.fromisoformat(d_clean)


def main() -> None:
    """应用程序主入口点，执行 YAML 配置驱动的全流程示范。"""
    # 1. 初始化设置与日志
    settings.setup_directories()
    setup_logger()

    logger.info(f"启动 {settings.app_name} [环境: {settings.environment}]")

    # 2. 从 YAML 配置文件加载策略参数 (消除硬编码)
    config_path = Path("config/strategy/double_sma_rsi.yaml")
    strategy_cfg = load_strategy_config(config_path)
    data_cfg = load_data_config()
    logger.info(f"成功加载策略配置: [{strategy_cfg.name}] v{strategy_cfg.version}")

    # 3. 使用 ETL 管道执行完整数据入库流 (Extract -> Clean -> Normalize -> Load)
    today = date.today()
    end_date = _parse_config_date(data_cfg.backfill.default_end_date, today) or today
    start_date = _parse_config_date(data_cfg.backfill.default_start_date, today) or (
        end_date - timedelta(days=30)
    )

    pipeline = create_pipeline(data_cfg.default_source_mode, endpoint="stock_daily_bar")
    frames = [
        pipeline.sync_daily_bars(symbol, start_date, end_date)
        for symbol in strategy_cfg.universe.all_symbols
    ]
    bars_df = pl.concat(frames, how="diagonal_relaxed")

    # 4. 执行 DuckDB SQL 面板检索与策略信号生成
    store = pipeline.store
    query_res = store.query_history(
        endpoint="stock_daily_bar", symbols=strategy_cfg.universe.all_symbols
    )
    logger.info(f"DuckDB SQL 查询结果: 共 {len(query_res)} 条缓存记录")

    # 5. 技术指标计算 (由 YAML 配置参数驱动)
    report = StrategyRunner(strategy_cfg, pipeline.data_source).run(bars_df)
    logger.info(f"研究信号报告: {report.to_dict()}")

    logger.info("金融脚手架全流程示范运行完毕！")


if __name__ == "__main__":
    main()
