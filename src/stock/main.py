from datetime import date, timedelta

from stock.analytics.indicators import calculate_rsi, calculate_sma
from stock.config.settings import settings
from stock.data.fetcher.example import MockDataFetcher
from stock.data.storage.duckdb_store import DuckDBMarketStore
from stock.utils.logger import logger, setup_logger


def main() -> None:
    # 1. 初始化设置与日志
    settings.setup_directories()
    setup_logger()

    logger.info(f"启动 {settings.app_name} [环境: {settings.environment}]")

    # 2. 抓取行情数据 (使用 Mock 数据源示例)
    symbol = "600000.SH"
    end_date = date.today()
    start_date = end_date - timedelta(days=90)

    fetcher = MockDataFetcher()
    logger.info(f"正在获取标的 [{symbol}] 在 {start_date} 至 {end_date} 的行情数据...")
    bars_df = fetcher.fetch_daily_bars_df(symbol, start_date, end_date)

    logger.info(f"获取成功，共 {len(bars_df)} 条日 K 记录。表头预览:\n{bars_df.head(3)}")

    # 3. 数据保存至 DuckDB / Parquet 存储层
    store = DuckDBMarketStore(storage_dir=settings.data_dir / "parquet")
    store.save_daily_bars(symbol, bars_df)

    # 4. 使用 DuckDB 直接 SQL 检索
    query_res = store.query_daily_bars(symbol, min_price=98.0)
    logger.info(f"DuckDB SQL 查询结果（收盘价 >= 98.0）: 共 {len(query_res)} 条")

    # 5. 技术指标计算 (Polars 向量化计算)
    df_with_indicators = calculate_sma(bars_df, window=5)
    df_with_indicators = calculate_rsi(df_with_indicators, window=14)

    logger.info(
        "指标计算完成 (SMA_5 & RSI_14)。最新行情与指标预览:\n"
        f"{df_with_indicators.select(['trade_date', 'close', 'sma_5', 'rsi_14']).tail(5)}"
    )

    logger.info("金融脚手架全流程示范运行完毕！")


if __name__ == "__main__":
    main()
