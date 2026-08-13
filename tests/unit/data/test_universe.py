import pytest
import pandas as pd
from unittest.mock import MagicMock

from stock.data.universe import UniverseFilter


@pytest.fixture
def mock_fetcher():
    fetcher = MagicMock()

    # Mock stock_basic
    df_basic = pd.DataFrame({
        "ts_code": ["000001.SZ", "000002.SZ", "300750.SZ", "600519.SH", "600000.SH", "000010.SZ", "000011.SZ"],
        "name": ["平安银行", "万科A", "宁德时代", "贵州茅台", "浦发银行", "ST测试", "次新测试"],
        "list_date": ["19910403", "19910129", "20180611", "20010827", "19991110", "19910101", "20990101"],
    })

    # Mock trade_cal
    df_cal = pd.DataFrame({
        "cal_date": ["20260812"]
    })

    # Mock daily_basic
    # 000001.SZ: 60000 千元 (6000万, >5000万, 保留)
    # 000002.SZ: 40000 千元 (4000万, <5000万, 剔除)
    # 300750.SZ: 100000 千元 (1亿, >5000万, 保留)
    # 600519.SH: 500000 千元 (5亿, >5000万, 保留)
    # 600000.SH: 30000 千元 (3000万, <5000万, 剔除)
    df_daily = pd.DataFrame({
        "ts_code": ["000001.SZ", "000002.SZ", "300750.SZ", "600519.SH", "600000.SH", "000010.SZ", "000011.SZ"],
        "amount": [60000.0, 40000.0, 100000.0, 500000.0, 30000.0, 60000.0, 60000.0]
    })

    def side_effect(endpoint, **kwargs):
        if endpoint == "stock_basic":
            return df_basic
        elif endpoint == "trade_cal":
            return df_cal
        elif endpoint == "daily_basic":
            return df_daily
        return pd.DataFrame()

    fetcher.client.query.side_effect = side_effect
    return fetcher


def test_get_liquid_universe(mock_fetcher):
    filter_engine = UniverseFilter(fetcher=mock_fetcher, use_local=False)

    symbols = filter_engine.get_liquid_universe(
        min_age_days=365,
        min_daily_amount_thousand=50000.0,
        exclude_st=True
    )

    # 预期结果:
    # 000010 (ST测试) 会被剔除
    # 000011 (次新测试) 会被剔除 (2099 年上市)
    # 000002 (万科A) 会被剔除 (< 5000 万)
    # 600000 (浦发银行) 会被剔除 (< 5000 万)
    # 剩下的应该是 000001, 300750, 600519
    assert len(symbols) == 3
    assert set(symbols) == {"000001", "300750", "600519"}

    # 验证是否去除了后缀
    assert all("." not in s for s in symbols)


def test_load_filter_rules(mock_fetcher, tmp_path):
    rule_file = tmp_path / "custom_rules.yaml"
    rule_file.write_text(
        "filter_rules:\n  exclude_st: false\n  min_age_days: 10\n  min_daily_amount_thousand: 10000.0\n",
        encoding="utf-8",
    )
    filter_engine = UniverseFilter(fetcher=mock_fetcher, use_local=False)
    rules = filter_engine.load_filter_rules(str(rule_file))
    assert rules["exclude_st"] is False
    assert rules["min_age_days"] == 10
    assert rules["min_daily_amount_thousand"] == 10000.0


def test_get_universe_snapshot_df(mock_fetcher, tmp_path):
    rule_file = tmp_path / "test_rules.yaml"
    rule_file.write_text(
        "filter_rules:\n  exclude_st: true\n  min_age_days: 365\n  min_daily_amount_thousand: 50000.0\n",
        encoding="utf-8",
    )
    filter_engine = UniverseFilter(fetcher=mock_fetcher, use_local=False)
def test_load_filter_rules_missing_file(mock_fetcher):
    filter_engine = UniverseFilter(fetcher=mock_fetcher, use_local=False)
    rules = filter_engine.load_filter_rules("non_existent_file.yaml")
    assert rules == {}


def test_get_liquid_universe_use_local(monkeypatch):
    import polars as pl
    from datetime import date

    mock_store = MagicMock()
    df_bar_pl = pl.DataFrame({
        "ts_code": ["000001.SZ", "000002.SZ"],
        "trade_date": [date(2026, 8, 12), date(2026, 8, 12)],
        "amount": [60000.0, 40000.0],
    })
    df_db_pl = pl.DataFrame({
        "ts_code": ["000001.SZ", "000002.SZ"],
        "trade_date": [date(2026, 8, 12), date(2026, 8, 12)],
        "circ_mv": [1e10, 1e10],
        "pb": [1.0, 1.0],
    })
    df_basic = pd.DataFrame({
        "ts_code": ["000001.SZ", "000002.SZ"],
        "name": ["平安银行", "万科A"],
        "list_date": ["19910403", "19910129"],
    })

    df_basic_pl = pl.from_pandas(df_basic)

    def mock_query_dataset(dataset, **kwargs):
        if dataset == "stock_basic":
            return df_basic_pl
        elif dataset == "stock_daily_bar":
            return df_bar_pl
        elif dataset == "daily_basic":
            return df_db_pl
        return pl.DataFrame()

    mock_store.query_dataset.side_effect = mock_query_dataset
    mock_fetcher = MagicMock()
    mock_fetcher.client.query.return_value = df_basic

    monkeypatch.setattr(
        "stock.data.storage.duckdb_store.DuckDBMarketStore", lambda data_source: mock_store
    )

    filter_engine = UniverseFilter(fetcher=mock_fetcher, use_local=True)
    symbols = filter_engine.get_liquid_universe(
        min_age_days=365,
        min_daily_amount_thousand=50000.0,
        exclude_st=True,
    )
    assert symbols == ["000001"]
