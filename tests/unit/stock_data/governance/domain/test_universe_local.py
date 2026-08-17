from pathlib import Path

import polars as pl
import pytest

from stock_core.exceptions import DataFetchError
from stock_data.core.settings import data_settings
from stock_data.governance.domain.universe import UniverseFilter


def test_universe_filter_local_mode_success(tmp_path: Path, monkeypatch) -> None:
    # 1. 写入 stock_basic
    df_basic = pl.DataFrame(
        {
            "ts_code": ["000001.SZ", "600519.SH", "000002.SZ"],
            "symbol": ["000001", "600519", "000002"],
            "name": ["平安银行", "贵州茅台", "万科A"],
            "list_date": ["19910403", "20010827", "19910129"],
            "data_source": ["tushare"] * 3,
            "market": ["CN"] * 3,
        }
    )
    p_basic = tmp_path / "tushare" / "market=CN" / "stock_basic" / "data.parquet"
    p_basic.parent.mkdir(parents=True, exist_ok=True)
    df_basic.write_parquet(p_basic)

    # 2. 写入 stock_daily_bar (至少 20 天数据)
    dates = [f"202401{i:02d}" for i in range(1, 25)]
    records = []
    for d in dates:
        for code in ["000001.SZ", "600519.SH", "000002.SZ"]:
            records.append(
                {
                    "symbol": code,
                    "trade_date": d,
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.0,
                    "close": 10.5,
                    "volume": 1000.0,
                    "amount": 50000.0
                    if code == "000001.SZ"
                    else (100000.0 if code == "600519.SH" else 5000.0),
                    "data_source": "tushare",
                    "market": "CN",
                    "exchange": "SZSE" if code.endswith(".SZ") else "SSE",
                    "currency": "CNY",
                    "adjustment": "raw",
                    "schema_version": "v2",
                }
            )
    df_bar = pl.DataFrame(records)
    p_bar = (
        tmp_path
        / "tushare"
        / "market=CN"
        / "stock_daily_bar"
        / "year=2024"
        / "month=01"
        / "data.parquet"
    )
    p_bar.parent.mkdir(parents=True, exist_ok=True)
    df_bar.write_parquet(p_bar)

    # 3. 写入 daily_basic
    df_db = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "600519.SH", "000002.SZ"],
            "trade_date": ["20240124"] * 3,
            "circ_mv": [2e9, 20e9, 1e9],
            "pb": [1.1, 5.5, 0.9],
            "data_source": ["tushare"] * 3,
            "market": ["CN"] * 3,
        }
    )
    p_db = (
        tmp_path
        / "tushare"
        / "market=CN"
        / "daily_basic"
        / "year=2024"
        / "month=01"
        / "data.parquet"
    )
    p_db.parent.mkdir(parents=True, exist_ok=True)
    df_db.write_parquet(p_db)

    # 4. 模拟 settings.curated_data_dir 指向 tmp_path
    monkeypatch.setattr(data_settings, "curated_data_dir", tmp_path)

    filter_engine = UniverseFilter(use_local=True)
    liquid_symbols = filter_engine.get_liquid_universe(
        min_age_days=365,
        min_daily_amount_thousand=30000.0,
        exclude_st=True,
    )
    assert "000001" in liquid_symbols
    assert "600519" in liquid_symbols
    assert "000002" not in liquid_symbols  # 成交额 5000 < 30000 淘汰


def test_universe_filter_local_mode_missing_archive_raises(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(data_settings, "curated_data_dir", tmp_path)
    filter_engine = UniverseFilter(use_local=True)
    with pytest.raises(DataFetchError, match="缺失 stock_basic"):
        filter_engine.get_liquid_universe()
