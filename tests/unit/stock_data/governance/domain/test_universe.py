from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from stock_data.governance.domain.universe import UniverseFilter


@pytest.fixture
def mock_fetcher():
    fetcher = MagicMock()

    # Mock stock_basic
    df_basic = pd.DataFrame(
        {
            "ts_code": [
                "000001.SZ",
                "000002.SZ",
                "300750.SZ",
                "600519.SH",
                "600000.SH",
                "000010.SZ",
                "000011.SZ",
                "830001.BJ",
            ],
            "name": [
                "平安银行",
                "万科A",
                "宁德时代",
                "贵州茅台",
                "浦发银行",
                "ST测试",
                "次新测试",
                "北交测试",
            ],
            "list_date": [
                "19910403",
                "19910129",
                "20180611",
                "20010827",
                "19991110",
                "19910101",
                "20990101",
                "20200101",
            ],
        }
    )

    # Mock trade_cal
    df_cal = pd.DataFrame({"cal_date": ["20260812"]})

    # Mock daily_basic
    df_daily = pd.DataFrame(
        {
            "ts_code": [
                "000001.SZ",
                "000002.SZ",
                "300750.SZ",
                "600519.SH",
                "600000.SH",
                "000010.SZ",
                "000011.SZ",
                "830001.BJ",
            ],
            "amount": [60000.0, 40000.0, 100000.0, 500000.0, 30000.0, 60000.0, 60000.0, 60000.0],
            "amount_20d": [50000.0, 30000.0, 90000.0, 400000.0, 20000.0, 50000.0, 50000.0, 50000.0],
            "circ_mv": [2e9, 2e9, 10e9, 50e9, 1e9, 2e9, 2e9, 2e9],
            "pb": [1.0, 1.2, 5.0, 6.0, 0.8, 1.0, 1.0, 1.0],
        }
    )

    def side_effect(endpoint, **kwargs):
        if endpoint == "stock_basic":
            return df_basic
        if endpoint == "trade_cal":
            return df_cal
        if endpoint == "daily_basic":
            return df_daily
        return pd.DataFrame()

    fetcher.client.query.side_effect = side_effect
    return fetcher


def test_get_liquid_universe(mock_fetcher):
    filter_engine = UniverseFilter(fetcher=mock_fetcher, use_local=False)

    symbols = filter_engine.get_liquid_universe(
        min_age_days=365, min_daily_amount_thousand=50000.0, exclude_st=True
    )

    assert "000010" not in symbols
    assert "000011" not in symbols
    assert "000002" not in symbols
    assert "830001" not in symbols
    assert "000001" in symbols
    assert "300750" in symbols
    assert "600519" in symbols


def test_get_universe_snapshot_df(mock_fetcher):
    filter_engine = UniverseFilter(fetcher=mock_fetcher, use_local=False)
    snap_df = filter_engine.get_universe_snapshot_df()
    assert not snap_df.empty
    assert "as_of_date" in snap_df.columns
    assert "symbol" in snap_df.columns
    assert "circ_mv" in snap_df.columns


def test_save_universe_snapshot(mock_fetcher, tmp_path: Path):
    filter_engine = UniverseFilter(fetcher=mock_fetcher, use_local=False)
    with patch("stock_data.storage.duckdb_store.DuckDBMarketStore") as mock_store_cls:
        mock_store = MagicMock()
        mock_store.storage_dir = tmp_path
        mock_store_cls.return_value = mock_store

        saved_path = filter_engine.save_universe_snapshot()
        assert saved_path != ""
        assert Path(saved_path).exists()
