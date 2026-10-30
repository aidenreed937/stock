"""StorageCompat 单元测试。"""

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from stock_data.storage.compat import StorageCompat


def test_is_artifact_path() -> None:
    assert StorageCompat.is_artifact_path(Path("data.bak.parquet")) is True
    assert StorageCompat.is_artifact_path(Path("data.tmp.parquet")) is True
    assert StorageCompat.is_artifact_path(Path("data.migration.tmp.parquet")) is True
    assert StorageCompat.is_artifact_path(Path("data.parquet")) is False


def test_canonical_dataset_name() -> None:
    assert StorageCompat.canonical_dataset_name("daily") == "stock_daily_bar"
    assert StorageCompat.canonical_dataset_name("daily_bar") == "stock_daily_bar"
    assert StorageCompat.canonical_dataset_name("history") == "stock_daily_bar"
    assert StorageCompat.canonical_dataset_name("daily_basic", "tushare") == "daily_basic"


def test_normalize_identity_columns() -> None:
    df = pl.DataFrame({"ts_code": ["000001.SZ"], "date": ["2026-08-10"], "close": [10.0]})
    normalized = StorageCompat.normalize_identity_columns(df)
    assert "symbol" in normalized.columns
    assert "trade_date" in normalized.columns
    assert "ts_code" not in normalized.columns
    assert "date" not in normalized.columns
    assert normalized["symbol"][0] == "000001.SZ"
    assert normalized["trade_date"][0] == "2026-08-10"


def test_normalize_identity_columns_promotes_qualified_ts_code_over_bare_symbol() -> None:
    """ts_code 是 symbol 的规范化写法时按既有语义提升（stock_basic 场景）。"""
    df = pl.DataFrame({"ts_code": ["000001.SZ", "600000.SH"], "symbol": ["000001", "600000"]})

    normalized = StorageCompat.normalize_identity_columns(df)

    assert normalized["symbol"].to_list() == ["000001.SZ", "600000.SH"]
    assert "ts_code" not in normalized.columns


def test_normalize_identity_columns_keeps_promoting_over_placeholder_symbol() -> None:
    """symbol 为占位符时仍由源端代码覆盖（adj_factor 场景），既有语义不变。"""
    df = pl.DataFrame({"ts_code": ["600000.SH"], "symbol": ["ADJ_FACTOR"]})

    normalized = StorageCompat.normalize_identity_columns(df)

    assert normalized["symbol"].to_list() == ["600000.SH"]
    assert "ts_code" not in normalized.columns


def test_normalize_identity_columns_fills_symbol_from_alias_when_symbol_is_null() -> None:
    df = pl.DataFrame({"ts_code": ["000001.SZ", "000002.SZ"], "symbol": [None, None]})

    normalized = StorageCompat.normalize_identity_columns(df)

    assert normalized["symbol"].to_list() == ["000001.SZ", "000002.SZ"]
    assert "ts_code" not in normalized.columns


def test_count_foreign_identity_alias_rows_flags_second_identifier() -> None:
    """基金代码 vs 被持有股票代码：去掉交易所后缀后仍不同，属「另一标识」。"""
    df = pl.DataFrame({"ts_code": ["159645.SZ", "260116.OF"], "symbol": ["002050.SZ", "600519.SH"]})

    assert StorageCompat.count_foreign_identity_alias_rows(df, "ts_code") == 2


def test_count_foreign_identity_alias_rows_ignores_format_variants_and_nulls() -> None:
    """同一标的的不同写法、以及其中一列为空时不触发告警，避免误报噪声。"""
    same_entity = pl.DataFrame({"ts_code": ["000001.SZ"], "symbol": ["000001"]})
    assert StorageCompat.count_foreign_identity_alias_rows(same_entity, "ts_code") == 0

    null_symbol = pl.DataFrame({"ts_code": ["000001.SZ"], "symbol": [None]})
    assert StorageCompat.count_foreign_identity_alias_rows(null_symbol, "ts_code") == 0


def test_normalize_datetime_columns() -> None:
    now_naive = datetime(2026, 8, 10, 12, 0, 0)
    df = pl.DataFrame({"updated_at": [now_naive]})
    normalized = StorageCompat.normalize_datetime_columns(df)
    assert normalized.schema["updated_at"] == pl.Datetime("us", "UTC")


def test_normalize_date_columns_casts_alphavantage_report_dates() -> None:
    """Alpha Vantage 报表期间列必须落为 pl.Date，而不是原始字符串。"""
    df = pl.DataFrame(
        {
            "fiscal_date_ending": ["2026-06-30"],
            "reported_date": ["2026-08-01"],
            "symbol": ["IBM"],
        }
    )

    normalized = StorageCompat.normalize_date_columns(df)

    assert normalized.schema["fiscal_date_ending"] == pl.Date
    assert normalized.schema["reported_date"] == pl.Date
    assert normalized["fiscal_date_ending"][0].isoformat() == "2026-06-30"


def test_normalize_numeric_columns() -> None:
    df = pl.DataFrame({"rqyl": ["12345.6"], "rzye": ["999.0"], "text_col": ["abc"]})
    normalized = StorageCompat.normalize_numeric_columns(df)
    assert normalized.schema["rqyl"] == pl.Float64
    assert normalized.schema["rzye"] == pl.Float64
    assert normalized.schema["text_col"] == pl.String
    assert normalized["rqyl"][0] == 12345.6


def test_normalize_dataset_schema_types() -> None:
    df = pl.DataFrame(
        {
            "ann_date": ["20260814"],
            "end_date": ["20260630"],
            "diluted_roe": ["12.5"],
            "report_type": ["1"],
        }
    )

    normalized = StorageCompat.post_process_dataset("express", df)

    assert normalized.schema["ann_date"] == pl.Date
    assert normalized.schema["end_date"] == pl.Date
    assert normalized.schema["diluted_roe"] == pl.Float64
    assert normalized.schema["report_type"] == pl.String


def test_normalize_null_numeric_column_to_float() -> None:
    df = pl.DataFrame({"forward_pe": [None], "price_to_sales": [None]})

    normalized = StorageCompat.normalize_numeric_columns(df, "index_valuation")

    assert normalized.schema["forward_pe"] == pl.Float64
    assert normalized.schema["price_to_sales"] == pl.Float64


def test_normalize_financial_cashflow_dates_and_values() -> None:
    df = pl.DataFrame(
        {
            "ann_date": ["20260814"],
            "end_date": ["20260630"],
            "finan_exp": ["12.5"],
            "c_fr_sale_sg": ["100.0"],
            "report_type": ["1"],
        }
    )

    normalized = StorageCompat.post_process_dataset("cashflow", df)

    assert normalized.schema["ann_date"] == pl.Date
    assert normalized.schema["end_date"] == pl.Date
    assert normalized.schema["finan_exp"] == pl.Float64
    assert normalized.schema["c_fr_sale_sg"] == pl.Float64
    assert normalized.schema["report_type"] == pl.String


def test_normalize_additional_business_date_and_numeric_aliases() -> None:
    df = pl.DataFrame(
        {
            "list_date": ["20260101"],
            "pretrade_date": ["20251231"],
            "Date Reported": ["2026-06-30T00:00:00+08:00"],
            "Start Date": ["2026-06-30"],
            "announcement_date": ["2026-06-30"],
            "observation_date": ["2026-06-30"],
            "buy": ["100.0"],
            "5y": ["2.5"],
        }
    )

    normalized = StorageCompat.post_process_dataset("hsgt_top10", df)
    normalized = StorageCompat.post_process_dataset("shibor_lpr", normalized)

    assert normalized.schema["list_date"] == pl.Date
    assert normalized.schema["pretrade_date"] == pl.Date
    assert normalized.schema["Date Reported"] == pl.Date
    assert normalized.schema["Start Date"] == pl.Date
    assert normalized.schema["announcement_date"] == pl.Date
    assert normalized.schema["observation_date"] == pl.Date
    assert normalized.schema["buy"] == pl.Float64
    assert normalized.schema["5y"] == pl.Float64


def test_normalize_nested_columns_encodes_empty_struct_without_reference() -> None:
    df = pl.DataFrame({"symbol": ["600519"], "q": [{}]})

    normalized = StorageCompat.normalize_nested_columns(df)

    assert normalized.schema["q"] == pl.String
    assert normalized["q"].to_list() == ["{}"]


def test_normalize_nested_columns_casts_empty_struct_to_stable_reference() -> None:
    stable = pl.DataFrame({"q": [{"metrics": {"roe": 1.0}}]})
    empty = pl.DataFrame({"q": [{"metrics": {}}]})

    normalized = StorageCompat.normalize_nested_columns(empty, reference_frames=[stable])

    assert normalized.schema["q"] == stable.schema["q"]
    assert normalized["q"].to_list() == [{"metrics": {"roe": None}}]


def test_normalize_lixinger_industry_q_restores_legacy_string_shape() -> None:
    normalized = StorageCompat.normalize_lixinger_industry_financial_q(
        "sw_2021_l3_fs_bank",
        pl.DataFrame({"q": ["{{{0.1,0.2},{0.3,0.4}},{{0.5}}}"]}),
    )

    assert normalized.schema["q"] == pl.Struct(
        {
            "ps": pl.Struct(
                {
                    "toi": pl.Struct({"t": pl.Int64, "c_y2y": pl.Float64, "ttm_y2y": pl.Float64}),
                    "np": pl.Struct({"t": pl.Int64, "c_y2y": pl.Float64, "ttm_y2y": pl.Float64}),
                }
            ),
            "m": pl.Struct({"roe": pl.Struct({"ttm": pl.Float64})}),
        }
    )
    value = normalized["q"].item()
    assert value["ps"]["toi"] == {"t": None, "c_y2y": 0.1, "ttm_y2y": 0.2}
    assert value["ps"]["np"] == {"t": None, "c_y2y": 0.3, "ttm_y2y": 0.4}
    assert value["m"]["roe"] == {"ttm": 0.5}


def test_curated_lixinger_industry_q_derives_missing_ttm_y2y() -> None:
    report_types = [
        "first_quarterly_report",
        "interim_report",
        "third_quarterly_report",
        "annual_report",
    ] * 2
    standard_dates = [
        "2021-03-31",
        "2021-06-30",
        "2021-09-30",
        "2021-12-31",
        "2022-03-31",
        "2022-06-30",
        "2022-09-30",
        "2022-12-31",
    ]
    cumulative = [100, 220, 340, 480, 110, 250, 400, 560]
    frame = pl.DataFrame(
        {
            "symbol": ["110101"] * 8,
            "reportType": report_types,
            "standardDate": standard_dates,
            "q": [
                {
                    "ps": {
                        "toi": {"t": value, "c_y2y": None, "ttm_y2y": None},
                        "np": {"t": value, "c_y2y": None, "ttm_y2y": None},
                    },
                    "m": {"roe": {"ttm": None}},
                }
                for value in cumulative
            ],
        }
    )

    curated = StorageCompat.post_process_dataset("sw_2021_l3_fs_bank", frame)
    toi_derived = curated.select(
        pl.col("q").struct.field("ps").struct.field("toi").struct.field("ttm_y2y_derived")
    ).to_series()
    np_derived = curated.select(
        pl.col("q").struct.field("ps").struct.field("np").struct.field("ttm_y2y_derived")
    ).to_series()

    assert toi_derived[:7].null_count() == 7
    assert toi_derived[7] == pytest.approx(560 / 480 - 1)
    assert np_derived[7] == pytest.approx(560 / 480 - 1)

    raw_compatible = StorageCompat.normalize_lixinger_industry_financial_q(
        "sw_2021_l3_fs_bank", frame
    )
    assert "ttm_y2y_derived" not in {
        field.name for field in raw_compatible.schema["q"].fields[0].dtype.fields
    }


def test_safe_normalize_frame() -> None:
    df = pl.DataFrame(
        {
            "ts_code": ["600519.SH"],
            "date": ["2026-08-14"],
            "rqyl": ["500000.0"],
            "updated_at": [datetime(2026, 8, 14, 15, 0, 0, tzinfo=UTC)],
        }
    )
    safe_df = StorageCompat.safe_normalize_frame(df)
    assert "symbol" in safe_df.columns
    assert "trade_date" in safe_df.columns
    assert safe_df.schema["trade_date"] == pl.Date
    assert safe_df.schema["rqyl"] == pl.Float64
    assert safe_df.schema["updated_at"] == pl.Datetime("us", "UTC")


def test_post_process_moneyflow_hsgt_drops_legacy_symbol() -> None:
    df = pl.DataFrame(
        {
            "symbol": ["moneyflow_hsgt"],
            "trade_date": ["2026-08-14"],
            "north_money": ["1.0"],
            "market": ["US"],
            "currency": ["USD"],
            "exchange": ["US_EXCHANGE"],
        }
    )

    normalized = StorageCompat.post_process_dataset("moneyflow_hsgt", df)

    assert "symbol" not in normalized.columns
    assert normalized.columns == ["trade_date", "north_money", "market", "currency", "exchange"]
    assert normalized["market"].to_list() == ["CN"]
    assert normalized["currency"].to_list() == ["CNY"]
    assert normalized["exchange"].to_list() == ["SOURCE"]


def test_post_process_adds_stable_identity_for_period_macro_dataset() -> None:
    normalized = StorageCompat.post_process_dataset(
        "sf_month", pl.DataFrame({"month": ["202607"], "inc_month": [1.0]})
    )

    assert normalized["symbol"].to_list() == ["sf_month"]


def test_post_process_adds_stable_identity_for_metadata_dataset() -> None:
    for dataset in ("index_classify", "index_member"):
        normalized = StorageCompat.post_process_dataset(
            dataset, pl.DataFrame({"index_code": ["801001.SI"]})
        )

        assert normalized["symbol"].to_list() == [dataset]


def test_post_process_interest_rates_drops_retired_lpr_columns() -> None:
    df = pl.DataFrame(
        {
            "trade_date": ["2026-08-14"],
            "lpr_y1": [3.0],
            "lpr_y5": [3.5],
            "shibor_on": [1.0],
        }
    )

    normalized = StorageCompat.post_process_dataset("interest_rates", df)

    assert normalized.columns == ["trade_date", "shibor_on"]


def test_fred_dataset_aliases_keep_legacy_directories_readable() -> None:
    assert StorageCompat.canonical_dataset_name("FEDFUNDS", "fred") == "macro_indicators"
    assert StorageCompat.dataset_aliases("FEDFUNDS", "fred") == (
        "macro_indicators",
        "fedfunds",
        "FEDFUNDS",
    )
    assert StorageCompat.dataset_symbol_filter("FEDFUNDS", "fred") == "FEDFUNDS"


def test_optional_columns_for_macro_and_commodity_datasets() -> None:
    from stock_data.storage.compat_rules import optional_columns_for_dataset

    assert "cdnaaa_y1" in optional_columns_for_dataset("interest_rates")
    assert "tcm_y10" in optional_columns_for_dataset("national_debt")
    assert "wti_co_sp" in optional_columns_for_dataset("crude_oil")
    assert "l_cu_p" in optional_columns_for_dataset("non_ferrous_metals")
    assert "ps_mc" in optional_columns_for_dataset("pledge_info")


def test_resolve_dedup_keys_prefers_renamed_identity_column() -> None:
    """fund_portfolio 的 ts_code 已改名为 fund_code，去重键不能用 symbol 顶替。

    历史缺陷：ts_code 在 Curated 侧已改名为 fund_code，去重键解析退回候选 symbol，
    而 symbol 是「被持有股票代码」，于是不同基金持有同一股票、同一天公告的记录被折叠，
    341,908 行读成 119,000 行。修复后必须保留 fund_code。
    """
    frame = pl.DataFrame(
        {
            "market": ["CN", "CN"],
            "fund_code": ["005827.OF", "110011.OF"],
            "symbol": ["600519.SH", "600519.SH"],
            "ann_date": [date(2026, 1, 22), date(2026, 1, 22)],
            "end_date": [date(2025, 12, 31), date(2025, 12, 31)],
        }
    )

    keys = StorageCompat.resolve_dedup_keys("fund_portfolio", "tushare", "tushare", frame)

    assert "fund_code" in keys
    assert "symbol" in keys
    # 关键断言：两只基金持有同一只股票不能被折叠
    assert frame.unique(subset=keys, keep="last").height == 2
