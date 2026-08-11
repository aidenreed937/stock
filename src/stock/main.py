from datetime import date, timedelta
from pathlib import Path

from stock.analytics.indicators import calculate_rsi, calculate_sma
from stock.config.loader import load_strategy_config
from stock.config.settings import settings
from stock.data.fetcher.example import MockDataFetcher
from stock.data.storage.duckdb_store import DuckDBMarketStore
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
    config_path = Path("config/strategy_example.yaml")
    strategy_cfg = load_strategy_config(config_path)
    logger.info(f"成功加载策略配置: [{strategy_cfg.name}] v{strategy_cfg.version}")

    # 3. 抓取行情数据 (使用配置中定义的首个标的与指标参数)
    symbol = strategy_cfg.universe.symbols[0]
    end_date = date.today()
    start_date = end_date - timedelta(days=DEFAULT_LOOKBACK_DAYS)

    fetcher = MockDataFetcher()
    logger.info(f"正在获取标的 [{symbol}] 在 {start_date} 至 {end_date} 的行情数据...")
    bars_df = fetcher.fetch_daily_bars_df(symbol, start_date, end_date)

    logger.info(f"获取成功，共 {len(bars_df)} 条日 K 记录。表头预览:\n{bars_df.head(3)}")

    # 4. 数据保存至 DuckDB / Parquet 存储层 (自动注入 settings 默认路径)
    store = DuckDBMarketStore()
    store.save_daily_bars(symbol, bars_df)

    # 5. 使用 DuckDB SQL 查询回检
    query_res = store.query_daily_bars(symbol)
    logger.info(f"DuckDB SQL 查询结果: 共 {len(query_res)} 条缓存记录")

    # 6. 技术指标计算 (由 YAML 配置参数驱动)
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
