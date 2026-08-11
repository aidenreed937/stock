import sys
from pathlib import Path

from loguru import logger

from stock.config.settings import settings

LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level:7}</level> | "
    "<cyan>{name}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)


def setup_logger(log_dir: Path | None = None) -> None:
    """全局统一格式化日志设置"""
    logger.remove()

    # 控制台彩色输出
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format=LOG_FORMAT,
    )

    # 文件化持久日志
    target_dir = log_dir or (settings.data_dir / "logs")
    target_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        target_dir / "app_{time:YYYY-MM-DD}.log",
        rotation="10 MB",
        retention="7 days",
        level="DEBUG",
        encoding="utf-8",
    )


__all__ = ["logger", "setup_logger"]
