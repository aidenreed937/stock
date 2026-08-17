"""setup_logger 单元测试。"""

from stock_core.utils.logger import logger, setup_logger


def test_setup_logger_custom_dir(tmp_path):
    log_dir = tmp_path / "logs"
    setup_logger(log_dir=log_dir)

    logger.info("Test info message")
    logger.warning("Test warning message")

    assert log_dir.exists()
    log_files = list(log_dir.glob("**/*.log"))
    assert len(log_files) >= 1
