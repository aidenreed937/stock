from pathlib import Path

from stock.config.loader import load_strategy_config
from stock.config.settings import Settings


def test_settings_default_values() -> None:
    settings = Settings()
    assert settings.app_name == "StockFinanceApp"
    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.data_source_mode == "tushare"


def test_load_strategy_config() -> None:
    config_path = Path("config/strategy/double_sma_rsi.yaml")
    cfg = load_strategy_config(config_path)
    assert cfg.name == "Double_SMA_RSI_Cross"
    assert len(cfg.universe.all_symbols) > 0
    assert cfg.indicators.sma.fast_period == 5
    assert cfg.indicators.rsi.period == 14
