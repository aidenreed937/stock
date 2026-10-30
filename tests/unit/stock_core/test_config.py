from datetime import date
from pathlib import Path

from stock_core.config.loader import load_data_config, load_watchlist_config
from stock_core.config.settings import Settings
from stock_data.core.settings import DataSettings
from stock_strategy.config import load_strategy_config


def test_settings_default_values() -> None:
    settings = Settings()
    assert settings.app_name == "StockFinanceApp"
    assert settings.environment == "development"
    assert settings.log_level == "INFO"

    data_settings = DataSettings()
    assert data_settings.data_source_mode == "tushare"


def test_data_settings_resolves_lixinger_token_profile() -> None:
    data_settings = DataSettings(
        lixinger_token="legacy-token",
        lixinger_tokens={"primary": "primary-token", "backup": "backup-token"},
        lixinger_profile="backup",
    )

    assert data_settings.effective_lixinger_token == "backup-token"
    assert data_settings.resolve_lixinger_token("primary") == "primary-token"
    assert data_settings.resolve_lixinger_token("missing") == ""


def test_data_settings_loads_lixinger_token_profiles_from_env_file(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        'LIXINGER_TOKENS=\'{"primary":"primary-token","backup":"backup-token"}\'\n'
        "LIXINGER_PROFILE=backup\n",
        encoding="utf-8",
    )

    data_settings = DataSettings(_env_file=env_path)

    assert data_settings.effective_lixinger_token == "backup-token"


def test_data_settings_loads_lixinger_fallback_profiles_from_env_file(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        'LIXINGER_TOKENS=\'{"primary":"primary-token","backup_1":"backup-token-1","backup_2":"backup-token-2"}\'\n'
        "LIXINGER_PROFILE=primary\n"
        'LIXINGER_FALLBACK_PROFILES=\'["backup_1","backup_2"]\'\n',
        encoding="utf-8",
    )

    data_settings = DataSettings(_env_file=env_path)

    assert data_settings.lixinger_fallback_profiles == ["backup_1", "backup_2"]


def test_data_settings_loads_alpha_vantage_api_keys_from_env_file(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        'ALPHA_VANTAGE_API_KEY="key-primary"\n'
        'ALPHA_VANTAGE_API_KEYS=\'["key-primary","key-backup"]\'\n',
        encoding="utf-8",
    )

    data_settings = DataSettings(_env_file=env_path)

    assert data_settings.resolve_alpha_vantage_api_keys() == ("key-primary", "key-backup")


def test_load_strategy_config() -> None:
    config_path = Path("config/strategy/double_sma_rsi.yaml")
    cfg = load_strategy_config(config_path)
    assert cfg.name == "Double_SMA_RSI_Cross"
    assert "300750.SZ" in cfg.universe.all_symbols
    assert "000300.SH" in cfg.universe.all_symbols
    assert cfg.indicators.sma.fast_period == 5
    assert cfg.indicators.rsi.period == 14


def test_load_watchlist_and_data_config() -> None:
    wl = load_watchlist_config()
    assert "300750.SZ" in wl.tushare.stocks
    assert "000300.SH" in wl.tushare.indices
    assert "300750" in wl.lixinger.stocks
    assert "000300" in wl.lixinger.indices
    assert "AAPL" in wl.yfinance.stocks
    assert "^GSPC" in wl.yfinance.indices
    assert "FEDFUNDS" in wl.fred.macro_series

    data_cfg = load_data_config()
    assert data_cfg.default_source_mode == "tushare"
    assert data_cfg.yfinance_financial_probe_interval_days == 7
    assert "300750.SZ" in data_cfg.watchlists.tushare.stocks
    assert "AAPL" in data_cfg.watchlists.yfinance.stocks
    assert data_cfg.backfill.default_start_date == "today-30d"
    assert data_cfg.backfill.default_end_date == "today"
    assert data_cfg.backfill.max_workers == 4


def test_load_data_config_keeps_planner_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "data.yaml"
    config_path.write_text(
        """
data:
  source_endpoint_supports:
    tushare:
      index_dailybasic:
        - "000300.SH"
  endpoint_start_date_overrides:
    tushare:index_dailybasic: "2004-12-31"
""",
        encoding="utf-8",
    )

    data_cfg = load_data_config(config_path)

    assert data_cfg.source_endpoint_supports["tushare"]["index_dailybasic"] == ["000300.SH"]
    assert data_cfg.endpoint_start_date_overrides["tushare:index_dailybasic"] == "2004-12-31"


def test_watchlist_base_dates() -> None:
    from datetime import date

    wl = load_watchlist_config()
    assert wl.tushare.get_base_date("159516.SZ") == date(2023, 7, 27)
    assert wl.tushare.get_base_date("510300.SH") == date(2012, 5, 28)
    assert wl.tushare.get_base_date("513920.SH") == date(2024, 1, 5)
    assert wl.tushare.get_base_date("300750.SZ") == date(2018, 6, 11)
    assert wl.lixinger.get_base_date("300750") == date(2018, 6, 11)
    assert wl.tushare.get_base_date("NON_EXISTENT") is None


def test_lixinger_short_code_base_dates_are_category_specific() -> None:
    wl = load_watchlist_config()

    assert wl.lixinger.get_base_date("000001", "stock") == date(1991, 4, 3)
    assert wl.lixinger.get_base_date("000001", "index") == date(1990, 12, 19)
