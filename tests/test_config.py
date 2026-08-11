from stock.config.settings import Settings


def test_settings_default_values() -> None:
    settings = Settings()
    assert settings.app_name == "StockFinanceApp"
    assert settings.environment == "development"
    assert settings.log_level == "INFO"
