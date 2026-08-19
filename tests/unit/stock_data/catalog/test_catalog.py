"""DataCatalog 单元测试：覆盖读取、过滤、去重、单位校验与 schema 容错。"""

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from stock_core.exceptions import DataValidationError
from stock_data.catalog import DataCatalog, load_dataset_compat


def _make_bar_file(tmp_path: Path, dataset: str, market: str, year: int, month: int) -> Path:
    """构造一个行情分区文件。"""
    partition = tmp_path / f"tushare/market={market}/{dataset}/year={year:04d}/month={month:02d}"
    partition.mkdir(parents=True, exist_ok=True)
    path = partition / "data.parquet"
    df = pl.DataFrame(
        {
            "symbol": ["AAA", "BBB", "AAA"],
            "trade_date": [
                date(year, month, 1),
                date(year, month, 1),
                date(year, month, 2),
            ],
            "open": [10.0, 20.0, 11.0],
            "high": [11.0, 21.0, 12.0],
            "low": [9.0, 19.0, 10.0],
            "close": [10.5, 20.5, 11.5],
            "volume": [1000.0, 2000.0, 1500.0],
            "amount": [105000.0, 410000.0, 172500.0],
            "market": [market, market, market],
            "exchange": ["SSE", "SSE", "SSE"],
            "currency": ["CNY", "CNY", "CNY"],
            "adjustment": ["raw", "raw", "raw"],
            "schema_version": ["v2", "v2", "v2"],
            "data_source": ["tushare", "tushare", "tushare"],
            "updated_at": [None, None, None],
        }
    )
    df.write_parquet(path)
    return path


def test_load_bars_reads_single_symbol(tmp_path: Path) -> None:
    """按单标的读取 K 线，应只返回该标的并按日期升序。"""
    _make_bar_file(tmp_path, "stock_daily_bar", "CN", 2026, 8)
    catalog = DataCatalog(data_source="tushare", storage_dir=tmp_path)
    df = catalog.load_bars(symbol="AAA", start_date=date(2026, 8, 1), end_date=date(2026, 8, 31))
    assert not df.is_empty()
    assert set(df["symbol"].unique().to_list()) == {"AAA"}
    assert df["trade_date"].to_list() == sorted(df["trade_date"].to_list())


def test_load_bars_filters_date_range(tmp_path: Path) -> None:
    """日期范围过滤：只返回范围内的交易日。"""
    _make_bar_file(tmp_path, "stock_daily_bar", "CN", 2026, 8)
    catalog = DataCatalog(data_source="tushare", storage_dir=tmp_path)
    df = catalog.load_bars(symbol="AAA", start_date=date(2026, 8, 2), end_date=date(2026, 8, 2))
    assert len(df) == 1
    assert df["trade_date"][0] == date(2026, 8, 2)


def test_load_bars_filters_adjustment(tmp_path: Path) -> None:
    """adjustment 过滤：只保留指定复权类型。"""
    _make_bar_file(tmp_path, "stock_daily_bar", "CN", 2026, 8)
    catalog = DataCatalog(data_source="tushare", storage_dir=tmp_path)
    df = catalog.load_bars(symbol="AAA", adjustment="normal")
    assert df.is_empty()  # 构造数据全是 raw，normal 应无结果
    df2 = catalog.load_bars(symbol="AAA", adjustment="raw")
    assert len(df2) == 2


def test_load_dataset_renames_ts_code(tmp_path: Path) -> None:
    """非行情数据集：ts_code 应归一为 symbol。"""
    partition = tmp_path / "tushare/market=CN/stock_basic"
    partition.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "ts_code": ["AAA", "BBB"],
            "name": ["甲", "乙"],
            "data_source": ["tushare", "tushare"],
        }
    ).write_parquet(partition / "data.parquet")
    catalog = DataCatalog(data_source="tushare", storage_dir=tmp_path)
    df = catalog.load_dataset("stock_basic")
    assert "symbol" in df.columns
    assert "ts_code" not in df.columns
    assert set(df["symbol"].to_list()) == {"AAA", "BBB"}


def test_load_dataset_normalizes_legacy_index_valuation(tmp_path: Path) -> None:
    partition = tmp_path / "yfinance/market=US/index_valuation"
    partition.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "symbol": ["SPY"],
            "trade_date": [date(2026, 8, 14)],
            "trailing_pe": [20.0],
            "forward_pe": [19.0],
            "price_to_book": [2.0],
            "price_to_sales": [3.0],
            "dividend_yield": [1.2],
            "market_cap": [None],
            "total_assets": [500.0],
            "data_source": ["yfinance"],
        }
    ).write_parquet(partition / "data.parquet")

    catalog = DataCatalog(data_source="yfinance", storage_dir=tmp_path)
    df = catalog.load_dataset("index_valuation")

    assert df["market_cap"].to_list() == [500.0]
    assert "total_assets" not in df.columns

    projected = catalog.load_dataset("index_valuation", columns=["market_cap"])
    assert projected.columns == ["market_cap"]
    assert projected["market_cap"].to_list() == [500.0]


def test_skips_bak_files(tmp_path: Path) -> None:
    """.bak / .tmp 文件应被跳过，不影响可用数据集列表。"""
    _make_bar_file(tmp_path, "stock_daily_bar", "CN", 2026, 8)
    partition = tmp_path / "tushare/market=CN/stock_daily_bar/year=2026/month=08"
    pl.DataFrame({"symbol": ["XXX"], "trade_date": [date(2026, 8, 1)]}).write_parquet(
        partition / "data.bak.parquet"
    )
    catalog = DataCatalog(data_source="tushare", storage_dir=tmp_path)
    files = catalog._parquet_files(dataset="stock_daily_bar")
    assert all(not f.name.endswith(".bak.parquet") for f in files)
    assert len(files) == 1


def test_partition_pruning_only_reads_range(tmp_path: Path) -> None:
    """Hive 年月分区裁剪：只读取与请求范围相交的月份文件。"""
    _make_bar_file(tmp_path, "stock_daily_bar", "CN", 2026, 7)
    _make_bar_file(tmp_path, "stock_daily_bar", "CN", 2026, 8)
    catalog = DataCatalog(data_source="tushare", storage_dir=tmp_path)
    df = catalog.load_bars(symbol="AAA", start_date=date(2026, 8, 1), end_date=date(2026, 8, 31))
    # 只应读到 08 月的数据
    assert not df.is_empty()
    assert df["trade_date"].min() >= date(2026, 8, 1)
    assert df["trade_date"].max() <= date(2026, 8, 31)


def test_dedup_by_primary_key(tmp_path: Path) -> None:
    """同一 (market, symbol, trade_date) 去重，保留最新。"""
    partition = tmp_path / "tushare/market=CN/stock_daily_bar/year=2026/month=08"
    partition.mkdir(parents=True, exist_ok=True)
    dup = pl.DataFrame(
        {
            "symbol": ["AAA", "AAA"],
            "trade_date": [date(2026, 8, 1), date(2026, 8, 1)],
            "open": [10.0, 10.0],
            "high": [11.0, 11.0],
            "low": [9.0, 9.0],
            "close": [10.5, 11.0],
            "volume": [1000.0, 1000.0],
            "amount": [105000.0, 110000.0],
            "market": ["CN", "CN"],
            "exchange": ["SSE", "SSE"],
            "currency": ["CNY", "CNY"],
            "adjustment": ["raw", "raw"],
            "schema_version": ["v2", "v2"],
            "data_source": ["tushare", "tushare"],
            "updated_at": [None, None],
        }
    )
    dup.write_parquet(partition / "data.parquet")
    catalog = DataCatalog(data_source="tushare", storage_dir=tmp_path)
    df = catalog.load_bars(symbol="AAA")
    assert len(df) == 1  # 重复主键被去重
    assert df["close"][0] == 11.0  # keep="last" 保留后写入的


def test_validate_bars_rejects_bad_ohlc(tmp_path: Path) -> None:
    """OHLC 物理异常应在 validate=True 时抛错。"""
    partition = tmp_path / "tushare/market=CN/stock_daily_bar/year=2026/month=08"
    partition.mkdir(parents=True, exist_ok=True)
    bad = pl.DataFrame(
        {
            "symbol": ["AAA"],
            "trade_date": [date(2026, 8, 1)],
            "open": [10.0],
            "high": [9.0],  # high < open，非法
            "low": [8.0],
            "close": [9.5],
            "volume": [1000.0],
            "amount": [9500.0],
            "market": ["CN"],
            "exchange": ["SSE"],
            "currency": ["CNY"],
            "adjustment": ["raw"],
            "schema_version": ["v2"],
            "data_source": ["tushare"],
            "updated_at": [None],
        }
    )
    bad.write_parquet(partition / "data.parquet")
    catalog = DataCatalog(data_source="tushare", storage_dir=tmp_path)
    with pytest.raises(Exception, match="OHLC"):
        catalog.load_bars(symbol="AAA")


def test_catalog_rejects_legacy_schema_version(tmp_path: Path) -> None:
    partition = tmp_path / "tushare/market=CN/daily_basic/year=2026/month=08"
    partition.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "symbol": ["AAA"],
            "trade_date": [date(2026, 8, 1)],
            "schema_version": ["v1"],
            "data_source": ["tushare"],
        }
    ).write_parquet(partition / "data.parquet")
    catalog = DataCatalog(data_source="tushare", storage_dir=tmp_path)

    with pytest.raises(DataValidationError, match="schema_version"):
        catalog.load_dataset("daily_basic")


def test_describe_lists_datasets(tmp_path: Path) -> None:
    """describe 应列出数据集的 data_source/dataset/files/rows。"""
    _make_bar_file(tmp_path, "stock_daily_bar", "CN", 2026, 8)
    _make_bar_file(tmp_path, "stock_daily_bar", "CN", 2026, 7)
    catalog = DataCatalog(data_source="tushare", storage_dir=tmp_path)
    summary = catalog.describe()
    assert {"data_source", "dataset", "files", "rows"}.issubset(summary.columns)
    row = summary.filter(pl.col("dataset") == "stock_daily_bar")
    assert len(row) == 1
    assert row["files"][0] == 2
    assert row["rows"][0] == 6


def test_updated_at_timezone_tolerance(tmp_path: Path) -> None:
    """updated_at 带/不带时区混存时，读取不应报 SchemaError。"""
    partition = tmp_path / "tushare/market=CN/daily_basic/year=2026/month=08"
    partition.mkdir(parents=True, exist_ok=True)
    # 两个文件：一个带 UTC 时区，一个无时区
    import datetime

    tz_aware = pl.DataFrame(
        {
            "symbol": ["AAA"],
            "trade_date": [date(2026, 8, 1)],
            "updated_at": [datetime.datetime(2026, 8, 1, 12, 0, tzinfo=datetime.UTC)],
        }
    )
    tz_naive = pl.DataFrame(
        {
            "symbol": ["BBB"],
            "trade_date": [date(2026, 8, 1)],
            "updated_at": [datetime.datetime(2026, 8, 1, 12, 0)],
        }
    )
    tz_aware.write_parquet(partition / "data_tz.parquet")
    tz_naive.write_parquet(partition / "data_naive.parquet")
    catalog = DataCatalog(data_source="tushare", storage_dir=tmp_path)
    df = catalog.load_dataset("daily_basic")
    assert len(df) == 2  # 时区差异不应导致读取失败


def test_catalog_standardized_methods(tmp_path) -> None:
    partition = tmp_path / "tushare" / "market=CN" / "daily_basic" / "year=2026" / "month=08"
    partition.mkdir(parents=True, exist_ok=True)
    df = pl.DataFrame({"symbol": ["600000.SH"], "trade_date": [date(2026, 8, 14)]})
    df.write_parquet(partition / "data.parquet")

    catalog = DataCatalog(data_source="tushare", storage_dir=tmp_path)

    # 1. get_latest_trade_date with exact name and alias
    latest = catalog.get_latest_trade_date("daily_basic")
    assert latest == date(2026, 8, 14)

    # 2. list_datasets
    datasets = catalog.list_datasets()
    assert "daily_basic" in datasets

    # 3. list_datasets all
    all_datasets = catalog.list_datasets(data_source="all")
    assert "daily_basic" in all_datasets

    # 4. summary
    summary_df = catalog.summary()
    assert len(summary_df) >= 1
    assert "daily_basic" in summary_df["dataset"].to_list()
    daily_basic_summary = summary_df.filter(pl.col("dataset") == "daily_basic")
    assert daily_basic_summary["latest_date"][0] == "2026-08-14"
    assert daily_basic_summary["total_rows"][0] == 1

    # 5. load_bars with alias
    _make_bar_file(tmp_path, "stock_daily_bar", "CN", 2026, 8)
    bars_df = catalog.load_bars(symbol="AAA")
    assert not bars_df.is_empty()
    assert "symbol" in bars_df.columns

    # 6. load_dataset with alias
    basic_df = catalog.load_dataset("daily_basic")
    assert not basic_df.is_empty()


def test_latest_refresh_dates_prefers_updated_at_and_supports_mtime_fallback(
    tmp_path: Path,
) -> None:
    partition = tmp_path / "tushare" / "market=CN" / "stock_basic"
    partition.mkdir(parents=True, exist_ok=True)
    updated = partition / "data.parquet"
    pl.DataFrame(
        {
            "symbol": ["AAA"],
            "updated_at": [datetime(2026, 8, 18, 12, 0, tzinfo=UTC)],
        }
    ).write_parquet(updated)

    catalog = DataCatalog(data_source="tushare", storage_dir=tmp_path)
    assert catalog.latest_refresh_dates("stock_basic") == [date(2026, 8, 18)]

    fallback = tmp_path / "tushare" / "market=CN" / "fund_basic"
    fallback.mkdir(parents=True, exist_ok=True)
    fallback_file = fallback / "data.parquet"
    pl.DataFrame({"symbol": ["AAA"]}).write_parquet(fallback_file)
    fallback_timestamp = datetime(2026, 8, 17, tzinfo=UTC).timestamp()
    import os

    os.utime(fallback_file, (fallback_timestamp, fallback_timestamp))
    assert catalog.latest_refresh_dates("fund_basic") == [date(2026, 8, 17)]


def test_latest_trade_dates_scans_all_markets_in_latest_month(tmp_path: Path) -> None:
    """最新日期不能被同月某个市场文件的较早水位提前截断。"""
    us_partition = tmp_path / "yfinance/market=US/stock_daily_bar/year=2026/month=08"
    global_partition = tmp_path / "yfinance/market=GLOBAL/stock_daily_bar/year=2026/month=08"
    us_partition.mkdir(parents=True, exist_ok=True)
    global_partition.mkdir(parents=True, exist_ok=True)

    pl.DataFrame(
        {
            "symbol": ["AAPL"] * 13,
            "trade_date": [date(2026, 8, day) for day in range(1, 14)],
        }
    ).write_parquet(us_partition / "data.parquet")
    pl.DataFrame(
        {
            "symbol": ["^GSPC"],
            "trade_date": [date(2026, 8, 14)],
        }
    ).write_parquet(global_partition / "data.parquet")

    catalog = DataCatalog(data_source="yfinance", storage_dir=tmp_path)

    assert catalog.get_latest_trade_date("stock_daily_bar") == date(2026, 8, 14)


def test_latest_trade_dates_scans_all_unpartitioned_markets(tmp_path: Path) -> None:
    """未按年月分区的数据集也不能被第一个市场文件截断。"""
    us_dataset = tmp_path / "yfinance/market=US/macro_indicators"
    global_dataset = tmp_path / "yfinance/market=GLOBAL/macro_indicators"
    us_dataset.mkdir(parents=True, exist_ok=True)
    global_dataset.mkdir(parents=True, exist_ok=True)

    pl.DataFrame({"symbol": ["^VIX"], "trade_date": [date(2026, 8, 13)]}).write_parquet(
        us_dataset / "data.parquet"
    )
    pl.DataFrame({"symbol": ["^TNX"], "trade_date": [date(2026, 8, 18)]}).write_parquet(
        global_dataset / "data.parquet"
    )

    catalog = DataCatalog(data_source="yfinance", storage_dir=tmp_path)

    assert catalog.get_latest_trade_date("macro_indicators") == date(2026, 8, 18)


def test_latest_trade_dates_parses_month_only_macro_dataset(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "lixinger/market=CN/cn_m"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({"symbol": ["cn_m", "cn_m"], "month": ["202606", "202607"]}).write_parquet(
        dataset_dir / "data.parquet"
    )

    catalog = DataCatalog(data_source="lixinger", storage_dir=tmp_path)

    assert catalog.latest_trade_dates("cn_m") == [date(2026, 7, 1)]


def test_latest_trade_dates_parses_report_date_dataset(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "tushare/market=CN/report_rc/year=2026/month=08"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {"ts_code": ["600519.SH", "000001.SZ"], "report_date": ["20260814", "20260817"]}
    ).write_parquet(dataset_dir / "data.parquet")

    catalog = DataCatalog(data_source="tushare", storage_dir=tmp_path)

    assert catalog.latest_trade_dates("report_rc") == [date(2026, 8, 17)]


def test_latest_trade_dates_parses_publish_and_quarter_dates(tmp_path: Path) -> None:
    schedule_dir = tmp_path / "tushare/market=CN/cn_schedule"
    schedule_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "month": ["202608", "202611"],
            "publish_date": ["20260815", "20261231"],
            "title": ["A", "B"],
        }
    ).write_parquet(schedule_dir / "data.parquet")

    quarter_dir = tmp_path / "tushare/market=CN/quarterly_data"
    quarter_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({"symbol": ["AAA"], "quarter": ["2026Q2"]}).write_parquet(
        quarter_dir / "data.parquet"
    )

    catalog = DataCatalog(data_source="tushare", storage_dir=tmp_path)

    assert catalog.latest_trade_dates("cn_schedule") == [date(2026, 12, 31)]
    assert catalog.latest_trade_dates("cn_schedule", date_column="month") == [date(2026, 11, 1)]
    assert catalog.latest_trade_dates("quarterly_data") == [date(2026, 4, 1)]


def test_load_dataset_with_columns_projection(tmp_path: Path) -> None:
    """load_dataset 支持列投影，只返回请求的列。"""
    partition = tmp_path / "tushare/market=CN/daily_basic/year=2026/month=08"
    partition.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "symbol": ["AAA", "BBB"],
            "trade_date": [date(2026, 8, 1), date(2026, 8, 1)],
            "pe": [10.5, 20.3],
            "pb": [1.2, 2.1],
            "turnover_rate": [3.5, 4.2],
            "schema_version": ["v2", "v2"],
            "data_source": ["tushare", "tushare"],
        }
    ).write_parquet(partition / "data.parquet")

    catalog = DataCatalog(data_source="tushare", storage_dir=tmp_path)
    df = catalog.load_dataset("daily_basic", columns=["trade_date", "pe", "turnover_rate"])
    assert df.columns == ["trade_date", "pe", "turnover_rate"]
    assert len(df) == 2
    assert sorted(df["pe"].to_list()) == [10.5, 20.3]


def test_load_bars_with_columns_projection_and_filters(tmp_path: Path) -> None:
    """load_bars 支持列投影同时保持 symbol/date 过滤有效性。"""
    _make_bar_file(tmp_path, "stock_daily_bar", "CN", 2026, 8)
    catalog = DataCatalog(data_source="tushare", storage_dir=tmp_path)
    df = catalog.load_bars(
        symbol="AAA",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 1),
        columns=["trade_date", "close", "amount"],
    )
    assert df.columns == ["trade_date", "close", "amount"]
    assert len(df) == 1
    assert df["close"][0] == 10.5


def test_load_dataset_compat_passes_supported_kwargs(tmp_path: Path) -> None:
    """load_dataset_compat 透传 loader 支持的日期参数（无投影时保留全部列）。"""
    _make_bar_file(tmp_path, "stock_daily_bar", "CN", 2026, 8)
    catalog = DataCatalog(data_source="tushare", storage_dir=tmp_path)

    frame = load_dataset_compat(
        catalog,
        "stock_daily_bar",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 1),
    )
    assert len(frame) == 2  # start/end 生效（过滤掉 8/2 数据，保留 8/1 的 AAA 与 BBB 两条）
    assert set(frame["trade_date"].to_list()) == {date(2026, 8, 1)}
    assert "close" in frame.columns
    assert "trade_date" in frame.columns


def test_load_dataset_compat_passes_supported_kwargs_and_projects(tmp_path: Path) -> None:
    """load_dataset_compat 透传 loader 支持的参数并执行列投影。"""
    _make_bar_file(tmp_path, "stock_daily_bar", "CN", 2026, 8)
    catalog = DataCatalog(data_source="tushare", storage_dir=tmp_path)

    frame = load_dataset_compat(
        catalog,
        "stock_daily_bar",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 1),
        columns=["trade_date", "close", "amount"],
    )
    assert frame.columns == ["trade_date", "close", "amount"]
    assert len(frame) == 2  # start/end/columns 均生效
    assert set(frame["trade_date"].to_list()) == {date(2026, 8, 1)}


def test_load_dataset_compat_narrow_signature_loader() -> None:
    """loader 签名不含可选参数时，仅按位置加载并正确投影。"""

    class _Narrow:
        def load_dataset(self, dataset: str) -> pl.DataFrame:
            return pl.DataFrame(
                {
                    "trade_date": [date(2026, 8, 1)],
                    "value": [1.0],
                    "extra": [2.0],
                }
            )

    frame = load_dataset_compat(
        _Narrow(),
        "ds",
        start_date=date(2026, 8, 1),
        columns=["trade_date", "value"],
    )
    assert frame.columns == ["trade_date", "value"]
    assert frame["value"][0] == 1.0


def test_load_dataset_compat_non_dataframe_returns_empty() -> None:
    """loader 返回非 DataFrame 时返回空帧而非崩溃。"""

    class _Bad:
        def load_dataset(self, dataset: str) -> list[object]:
            return [1, 2, 3]

    frame = load_dataset_compat(_Bad(), "ds")
    assert frame.is_empty()
