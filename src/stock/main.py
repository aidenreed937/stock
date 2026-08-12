from datetime import date, timedelta
from pathlib import Path

from stock.analytics.indicators import calculate_rsi, calculate_sma
from stock.config.loader import load_strategy_config
from stock.config.settings import settings
from stock.data.pipeline import MarketDataPipeline
from stock.utils.logger import logger, setup_logger

# 默认行情回溯天数常量
DEFAULT_LOOKBACK_DAYS: int = 90


def main() -> None:
    """应用程序主入口点，执行 YAML 配置驱动的全流程示范。"""
    # 1. 初始化设置与日志
    settings.setup_directories()
    setup_logger()

    logger.info(f"启动 {settings.app_name} [环境: {settings.environment}]")

    # 2. 从 YAML 配置文件加载策略参数 (消除硬编码)
    config_path = Path("config/strategy/double_sma_rsi.yaml")
    strategy_cfg = load_strategy_config(config_path)
    logger.info(f"成功加载策略配置: [{strategy_cfg.name}] v{strategy_cfg.version}")

    # 3. 使用 ETL 管道执行完整数据入库流 (Extract -> Clean -> Normalize -> Load)
    symbol = strategy_cfg.universe.symbols[0]
    end_date = date.today()
    start_date = end_date - timedelta(days=DEFAULT_LOOKBACK_DAYS)

    if settings.data_source_mode == "mock":
        from stock.data.fetcher.mock import MockDataFetcher

        pipeline = MarketDataPipeline(fetcher=MockDataFetcher())
    elif settings.data_source_mode == "tushare":
        from stock.data.fetcher.tushare.factory import create_tushare_pipeline

        pipeline = create_tushare_pipeline(endpoint="daily")
    elif settings.data_source_mode == "yfinance":
        from stock.data.fetcher.yfinance import YFinanceDataFetcher

        proxy = settings.yfinance_proxy if settings.yfinance_proxy else None
        pipeline = MarketDataPipeline(fetcher=YFinanceDataFetcher(proxy=proxy))
    else:
        raise ValueError(f"不支持的数据源模式: {settings.data_source_mode}")
    bars_df = pipeline.sync_daily_bars(symbol, start_date, end_date)

    # 4. 使用 DuckDB SQL 查询回检
    store = pipeline.store
    query_res = store.query_daily_bars(symbol)
    logger.info(f"DuckDB SQL 查询结果: 共 {len(query_res)} 条缓存记录")

    # 5. 技术指标计算 (由 YAML 配置参数驱动)
    sma_period = strategy_cfg.indicators.sma.fast_period
    rsi_period = strategy_cfg.indicators.rsi.period

    df_with_indicators = calculate_sma(bars_df, window=sma_period)
    df_with_indicators = calculate_rsi(df_with_indicators, window=rsi_period)

    sma_col = f"sma_{sma_period}"
    rsi_col = f"rsi_{rsi_period}"

    logger.info(
        f"指标计算完成 ({sma_col.upper()} & {rsi_col.upper()})。最新行情预览:\n"
        f"{df_with_indicators.select(['trade_date', 'close', sma_col, rsi_col]).tail(5)}"
    )

    logger.info("金融脚手架全流程示范运行完毕！")


if __name__ == "__main__":
    main()
