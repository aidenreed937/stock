"""默认策略研究应用 CLI 兼容入口。"""

from __future__ import annotations

from stock_core.config.settings import settings
from stock_core.utils.logger import logger, setup_logger
from stock_strategy.application import parse_config_date as _parse_config_date
from stock_strategy.application import run_strategy_application

__all__ = ["_parse_config_date", "main"]


def main() -> None:
    """启动策略研究应用并输出结构化信号报告。"""
    setup_logger()
    logger.info(f"启动 {settings.app_name} [环境: {settings.environment}]")
    result = run_strategy_application()
    logger.info(f"研究信号报告: {result.report.to_dict()}")


if __name__ == "__main__":
    main()
