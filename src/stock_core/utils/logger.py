"""全局日志配置模块，基于 Loguru 实现控制台高亮与分模块持久化落盘。"""

import sys
from pathlib import Path

from loguru import logger

from stock_core.config.settings import settings

LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level:7}</level> | "
    "<cyan>{name}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)

FILE_LOG_FORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:7} | {name}:{line} - {message}"


def setup_logger(log_dir: Path | None = None) -> None:
    """初始化并全局配置 Loguru 日志通道 (包含控制台、全量 App、Error 专用通道与 ETL 管道通道)。

    Args:
        log_dir: 日志落盘根目录，若为 None 则默认使用 settings.data_dir / "logs"。
    """
    logger.remove()

    target_dir = log_dir or (settings.data_dir / "logs")

    app_dir = target_dir / "app"
    error_dir = target_dir / "error"
    etl_dir = target_dir / "etl"
    strategy_dir = target_dir / "strategy"

    for d in (app_dir, error_dir, etl_dir, strategy_dir):
        d.mkdir(parents=True, exist_ok=True)

    retention_str = f"{settings.log_retention_days} days"
    rotation_str = settings.log_rotation_size

    # 1. 控制台 Stream 输出
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format=LOG_FORMAT,
    )

    # 2. 全量 App 日志文件 (data/logs/app/app_{YYYY-MM-DD}.log)
    logger.add(
        app_dir / "app_{time:YYYY-MM-DD}.log",
        rotation=rotation_str,
        retention=retention_str,
        level="DEBUG",
        format=FILE_LOG_FORMAT,
        encoding="utf-8",
    )

    # 3. 独立 Error / Warning 故障告警通道 (data/logs/error/error_{YYYY-MM-DD}.log)
    logger.add(
        error_dir / "error_{time:YYYY-MM-DD}.log",
        rotation=rotation_str,
        retention=retention_str,
        level="WARNING",
        format=FILE_LOG_FORMAT,
        encoding="utf-8",
    )

    # 4. 数据 ETL 与 Fetcher 专用通道 (data/logs/etl/etl_{YYYY-MM-DD}.log)
    logger.add(
        etl_dir / "etl_{time:YYYY-MM-DD}.log",
        rotation=rotation_str,
        retention=retention_str,
        level="DEBUG",
        filter=lambda record: bool(record["name"] and "stock_data" in record["name"]),
        format=FILE_LOG_FORMAT,
        encoding="utf-8",
    )

    # 5. 策略与量化指标专用通道 (data/logs/strategy/strategy_{YYYY-MM-DD}.log)
    logger.add(
        strategy_dir / "strategy_{time:YYYY-MM-DD}.log",
        rotation=rotation_str,
        retention=retention_str,
        level="DEBUG",
        filter=lambda record: bool(
            record["name"]
            and any(mod in record["name"] for mod in ("stock_strategy", "stock_analytics"))
        ),
        format=FILE_LOG_FORMAT,
        encoding="utf-8",
    )


__all__ = ["logger", "setup_logger"]
