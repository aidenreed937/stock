"""市场温度计派生指标测试。"""

from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

from stock_analytics.pipelines.market_temperature.derived import (
    _amount_top_5pct_daily_frame,
    _external_environment_row,
    _external_macro_rows,
    _external_pressure_rows,
    _financial_statement_rows,
    _forecast_rows,
    _investor_account_frame,
    _investor_account_rows,
    _limit_event_daily_frame,
    _limit_event_rows,
    _option_rows,
    _percentile_temperature,
    _report_revision_rows,
    _return_frame,
    _us_macro_background_rows,
    collect_amount_top_5pct_share_rows,
)


def test_amount_top_5pct_share_uses_ceil_count_and_ratio_unit() -> None:
    frame = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 14)] * 5,
            "amount": [50.0, 20.0, 10.0, 5.0, 1.0],
        }
    )

    rows = collect_amount_top_5pct_share_rows(frame, (date(2026, 8, 14),))
    row = rows[date(2026, 8, 14)]

    assert row["status"] == "ok"
    assert row["dataset"] == "stock_daily_bar"
    assert row["source"] == "stock_daily_bar.amount"
    assert row["unit"] == "ratio"
    assert row["sample_size"] == 5
    assert row["value_float"] == pytest.approx(50 / 86)
    assert "top_count=1" in row["note"]


def test_amount_top_5pct_share_keeps_missing_target_as_insufficient() -> None:
    frame = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 14)],
            "amount": [0.0],
        }
    )

    result = _amount_top_5pct_daily_frame(frame)
    rows = collect_amount_top_5pct_share_rows(result, (date(2026, 8, 15),))

    assert result.is_empty()
    assert rows[date(2026, 8, 15)]["status"] == "insufficient"


from stock_analytics.pipelines.market_temperature.derived_options import (
    build_option_daily_frame,
)
from stock_analytics.pipelines.market_temperature.external_risk_facts import (
    raw_external_change_metric_row,
)


class FakeCatalog:
    data_source = "tushare"
    storage_dir = Path("data/curated")

    def __init__(self, datasets: dict[str, pl.DataFrame]) -> None:
        self.datasets = datasets
        self.load_calls: list[tuple[str, date | None]] = []

    def load_dataset(self, dataset: str, **kwargs: object) -> pl.DataFrame:
        raw_end_date = kwargs.get("end_date")
        end_date = raw_end_date if isinstance(raw_end_date, date) else None
        self.load_calls.append((dataset, end_date))
        return self.datasets.get(dataset, pl.DataFrame())


def test_financial_statement_rows_mark_stale_days() -> None:
    cat = FakeCatalog(
        {
            "sw_2021_fs_non_financial": pl.DataFrame(
                {
                    "trade_date": [date(2026, 3, 31)],
                    "symbol": ["SW1"],
                    "q": [
                        {
                            "ps": {
                                "toi": {"ttm_y2y": 0.10},
                                "np": {"ttm_y2y": 0.20},
                            },
                            "m": {"roe": {"ttm": 0.12}},
                        }
                    ],
                }
            )
        }
    )

    rows = _financial_statement_rows(cat, date(2026, 8, 14))

    assert len(rows) == 3
    for row in rows:
        assert "stale_days=136" in str(row["note"])
        assert "report_date=2026-03-31" in str(row["note"])


def test_forecast_rows_calculates_positive_forecast_share() -> None:
    catalog = FakeCatalog(
        {
            "forecast": pl.DataFrame(
                {
                    "symbol": ["AAA", "BBB", "CCC"],
                    "ann_date": ["20260721", "20260722", "20260723"],
                    "end_date": ["20260630", "20260630", "20260630"],
                    "type": ["预增", "首亏", "略减"],
                    "p_change_min": [None, -10.0, 30.0],
                    "p_change_max": [None, -5.0, 50.0],
                }
            )
        }
    )

    rows = _forecast_rows(
        catalog,
        date(2026, 8, 14),
        (date(2026, 7, 20), date(2026, 8, 14)),
    )

    assert rows[0]["status"] == "ok"
    assert rows[0]["sample_size"] == 3
    assert rows[0]["value_float"] == pytest.approx(66.6666667)


def test_forecast_rows_handles_date_typed_ann_date() -> None:
    catalog = FakeCatalog(
        {
            "forecast": pl.DataFrame(
                {
                    "symbol": ["AAA", "BBB", "CCC"],
                    "ann_date": [date(2026, 7, 21), date(2026, 7, 22), date(2026, 8, 10)],
                    "end_date": [date(2026, 6, 30), date(2026, 6, 30), date(2026, 6, 30)],
                    "type": ["预增", "首亏", "略减"],
                    "p_change_min": [None, -10.0, 30.0],
                    "p_change_max": [None, -5.0, 50.0],
                }
            )
        }
    )

    rows = _forecast_rows(
        catalog,
        date(2026, 8, 14),
        (date(2026, 7, 20), date(2026, 8, 14)),
    )

    assert rows[0]["status"] == "ok"
    assert rows[0]["sample_size"] == 3


def test_report_revision_rows_uses_net_revision_ratio_and_all_comparable_samples() -> None:
    catalog = FakeCatalog(
        {
            "report_rc": pl.DataFrame(
                {
                    "symbol": [
                        "AAA",
                        "AAA",
                        "BBB",
                        "BBB",
                        "CCC",
                        "CCC",
                        "DDD",
                        "DDD",
                        "EEE",
                        "EEE",
                    ],
                    "org_name": [
                        "org1",
                        "org1",
                        "org2",
                        "org2",
                        "org3",
                        "org3",
                        "org4",
                        "org4",
                        "org5",
                        "org5",
                    ],
                    "quarter": ["2026Q2"] * 10,
                    "report_date": [
                        "20260701",
                        "20260721",
                        "20260702",
                        "20260722",
                        "20260703",
                        "20260723",
                        "20260704",
                        "20260724",
                        "20260705",
                        "20260725",
                    ],
                    "np": [100.0, 120.0, 200.0, 150.0, 80.0, 80.0, 50.0, 50.0, 60.0, 90.0],
                }
            )
        }
    )

    rows = _report_revision_rows(
        catalog,
        date(2026, 8, 14),
        (date(2026, 7, 20), date(2026, 8, 14)),
    )

    assert rows[0]["status"] == "ok"
    assert rows[0]["sample_size"] == 5
    assert rows[0]["value_float"] == pytest.approx(60.0)
    assert "unchanged=2" in str(rows[0]["note"])


def test_report_revision_rows_marks_small_comparable_sample_insufficient() -> None:
    catalog = FakeCatalog(
        {
            "report_rc": pl.DataFrame(
                {
                    "symbol": ["AAA", "AAA"],
                    "org_name": ["org1", "org1"],
                    "quarter": ["2026Q2", "2026Q2"],
                    "report_date": ["20260701", "20260721"],
                    "np": [100.0, 120.0],
                }
            )
        }
    )

    row = _report_revision_rows(
        catalog,
        date(2026, 8, 14),
        (date(2026, 7, 20), date(2026, 8, 14)),
    )[0]

    assert row["status"] == "insufficient"
    assert row["sample_size"] == 1
    assert row["value_float"] is None


def test_limit_event_daily_frame_counts_up_down_and_broken_limit() -> None:
    frame = pl.DataFrame(
        {
            "trade_date": [
                date(2026, 1, 1),
                date(2026, 1, 1),
                date(2026, 1, 1),
                date(2026, 1, 1),
            ],
            "limit": ["U", "U", "D", "Z"],
        }
    )

    result = _limit_event_daily_frame(frame).to_dicts()[0]

    assert result["_up_count"] == pytest.approx(2.0)
    assert result["_down_count"] == pytest.approx(1.0)
    assert result["_break_count"] == pytest.approx(1.0)
    assert result["_up_down_ratio"] == pytest.approx(2 / 3)
    assert result["_seal_success_ratio"] == pytest.approx(2 / 3)


def test_limit_event_rows_builds_composite_temperature() -> None:
    catalog = FakeCatalog(
        {
            "limit_list_d": pl.DataFrame(
                {
                    "trade_date": [
                        date(2026, 1, 1),
                        date(2026, 1, 1),
                        date(2026, 1, 2),
                        date(2026, 1, 2),
                        date(2026, 1, 2),
                        date(2026, 1, 3),
                        date(2026, 1, 3),
                        date(2026, 1, 3),
                    ],
                    "limit": ["U", "D", "U", "U", "Z", "U", "U", "U"],
                }
            )
        }
    )

    rows = _limit_event_rows(catalog, date(2026, 1, 3))
    rows_by_metric = {str(row["metric_id"]): row for row in rows}

    assert rows_by_metric["limit_up_count_temperature"]["status"] == "ok"
    assert rows_by_metric["limit_down_count_temperature"]["status"] == "ok"
    assert rows_by_metric["limit_event_temperature"]["status"] == "ok"
    assert rows_by_metric["limit_event_temperature"]["sample_size"] == 4
    assert "up=3; down=0; break=0" in rows_by_metric["limit_event_temperature"]["note"]


def test_option_rows_builds_pcr_observation_temperatures() -> None:
    dates = [date(2026, 1, day) for day in (1, 2, 3)]
    basic = pl.DataFrame(
        {
            "symbol": ["C1", "P1"],
            "call_put": ["C", "P"],
            "s_month": ["202601", "202601"],
        }
    )
    daily = pl.DataFrame(
        {
            "symbol": ["C1", "P1", "C1", "P1", "C1", "P1"],
            "trade_date": [dates[0], dates[0], dates[1], dates[1], dates[2], dates[2]],
            "vol": [100.0, 50.0, 100.0, 100.0, 100.0, 200.0],
            "amount": [100.0, 50.0, 100.0, 100.0, 100.0, 200.0],
            "oi": [1000.0, 800.0, 1000.0, 900.0, 1000.0, 1200.0],
        }
    )
    frame = build_option_daily_frame(daily, basic)

    latest = frame.tail(1).to_dicts()[0]
    assert latest["_put_call_volume_ratio"] == pytest.approx(2.0)
    assert latest["_put_call_oi_ratio"] == pytest.approx(1.2)
    assert latest["_near_month_amount_share"] == pytest.approx(100.0)

    rows = _option_rows(FakeCatalog({"opt_daily": daily, "opt_basic": basic}), dates[-1])
    rows_by_metric = {str(row["metric_id"]): row for row in rows}

    assert rows_by_metric["option_put_call_volume_ratio_temperature"]["status"] == "ok"
    assert rows_by_metric["option_put_call_oi_ratio_temperature"]["status"] == "ok"
    assert rows_by_metric["option_risk_temperature"]["value_float"] == pytest.approx(100.0)
    assert "不是隐含波动率" in rows_by_metric["option_risk_temperature"]["note"]


def test_option_rows_reuses_valid_market_daily_option_features() -> None:
    trade_date = date(2026, 1, 3)
    market_daily = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, 1), trade_date],
            "option_put_call_volume_ratio": [1.0, 2.0],
            "option_put_call_oi_ratio": [0.8, 1.2],
            "option_amount": [100.0, 200.0],
            "option_open_interest": [1000.0, 1200.0],
            "option_near_month_amount_share": [50.0, 100.0],
        }
    )

    class NoRawDataCatalog:
        storage_dir = None

        def load_dataset(self, *_: object, **__: object) -> pl.DataFrame:
            raise AssertionError("有效 market_daily 路径不应读取 opt_daily")

    rows = _option_rows(
        NoRawDataCatalog(),
        trade_date,
        market_daily=market_daily,
        market_daily_option_source_valid=True,
    )

    rows_by_metric = {str(row["metric_id"]): row for row in rows}
    assert rows_by_metric["option_put_call_volume_ratio_temperature"]["status"] == "ok"
    assert rows_by_metric["option_risk_temperature"]["status"] == "ok"


def test_investor_account_rows_use_monthly_new_accounts_percentile() -> None:
    catalog = FakeCatalog(
        {
            "investor_accounts": pl.DataFrame(
                {
                    "trade_date": [
                        date(2026, 1, 31),
                        date(2026, 2, 28),
                        date(2026, 3, 31),
                    ],
                    "nni_m": [100.0, 200.0, 300.0],
                    "n_non_ni_m": [10.0, 20.0, 30.0],
                }
            )
        }
    )

    rows = _investor_account_rows(catalog, date(2026, 3, 31))

    assert rows[0]["metric_id"] == "investor_account_temperature"
    assert rows[0]["status"] == "ok"
    assert rows[0]["value_float"] == pytest.approx(100.0)
    assert rows[0]["sample_size"] == 3
    assert "latest_value=330" in rows[0]["note"]


def test_investor_account_frame_ignores_rows_without_monthly_new_values() -> None:
    frame = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, 31), date(2026, 2, 28)],
            "nni_m": [100.0, None],
            "n_non_ni_m": [10.0, None],
        }
    )

    result = _investor_account_frame(frame)

    assert result.height == 1
    assert result["_new_investor_accounts"][0] == pytest.approx(110.0)


def test_percentile_temperature_supports_inverse_direction() -> None:
    frame = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)],
            "value": [1.0, 2.0, 3.0],
        }
    )

    temperature, latest_value, latest_date, sample_size = _percentile_temperature(
        frame,
        "value",
        date(2026, 1, 3),
        date_col="trade_date",
        inverse=True,
    )

    assert temperature == pytest.approx(0.0)
    assert latest_value == pytest.approx(3.0)
    assert latest_date == date(2026, 1, 3)
    assert sample_size == 3


def test_return_frame_calculates_window_return_for_symbol() -> None:
    dates = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(22)]
    frame = pl.DataFrame(
        {
            "trade_date": [*dates, *dates],
            "symbol": ["^GSPC"] * 22 + ["^IXIC"] * 22,
            "close": [100.0 + offset for offset in range(22)]
            + [200.0 + offset for offset in range(22)],
        }
    )

    result = _return_frame(frame, "^GSPC", 20)
    value = result.filter(pl.col("trade_date") == dates[20])["_return"][0]

    assert value == pytest.approx(0.20)


def test_raw_external_change_metric_preserves_value_and_unit() -> None:
    frame = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 17), date(2026, 8, 18)] * 3,
            "symbol": ["^GSPC", "^GSPC", "^VIX", "^VIX", "^TNX", "^TNX"],
            "close": [100.0, 98.0, 100.0, 104.28, 4.0, 4.2],
        }
    )

    sp500 = raw_external_change_metric_row(
        frame,
        "^GSPC",
        "macro_sp500_1d_return",
        date(2026, 8, 18),
        note="标普500 1日收益",
        unit="return",
    )
    vix = raw_external_change_metric_row(
        frame,
        "^VIX",
        "macro_vix_1d_change",
        date(2026, 8, 18),
        note="VIX 1日相对变化",
        unit="return",
    )
    us_10y = raw_external_change_metric_row(
        frame,
        "^TNX",
        "macro_us_10y_1d_change",
        date(2026, 8, 18),
        note="美债10年期收益率1日变化",
        unit="percentage_point",
        relative=False,
    )

    assert sp500["value_float"] == pytest.approx(-0.02)
    assert sp500["unit"] == "return"
    assert vix["value_float"] == pytest.approx(0.0428)
    assert us_10y["value_float"] == pytest.approx(0.2)
    assert us_10y["unit"] == "percentage_point"


def test_external_environment_row_averages_available_components_only() -> None:
    rows = [
        _component("macro_sp500_20d_return_temperature", 60.0),
        _component("macro_nasdaq_20d_return_temperature", 80.0),
        _component("macro_vix_temperature", 40.0),
        _component("macro_usd_index_20d_change_temperature", 20.0),
        _component("macro_us_10y_temperature", 100.0),
        _component("macro_copper_20d_return_temperature", None, status="insufficient"),
    ]

    row = _external_environment_row(rows, date(2026, 8, 14))

    assert row["status"] == "ok"
    assert row["value_float"] == pytest.approx(60.0)
    assert row["sample_size"] == 5
    assert "macro_copper_20d_return_temperature" in row["note"]


def test_external_pressure_rows_build_pressure_components_and_total() -> None:
    rows = [
        _component("macro_gold_20d_return_pressure", 90.0),
        _component("macro_oil_20d_return_pressure", 80.0),
        _component("macro_vix_temperature", 20.0),
        _component("macro_sp500_20d_return_temperature", 30.0),
        _component("macro_nasdaq_20d_return_temperature", 40.0),
        _component("macro_us_10y_temperature", 30.0),
        _component("macro_fred_cpi_yoy_temperature", 20.0),
        _component("macro_copper_20d_return_temperature", 20.0),
    ]

    pressure_rows = _external_pressure_rows(rows, date(2026, 8, 14))
    rows_by_metric = {str(row["metric_id"]): row for row in pressure_rows}

    assert rows_by_metric["macro_safe_haven_pressure_temperature"]["value_float"] == (
        pytest.approx(75.0)
    )
    assert rows_by_metric["macro_inflation_pressure_temperature"]["value_float"] == (
        pytest.approx(76.6666667)
    )
    assert rows_by_metric["macro_demand_pressure_temperature"]["value_float"] == (
        pytest.approx(57.5)
    )
    assert rows_by_metric["macro_external_pressure_temperature"]["value_float"] == (
        pytest.approx(76.6666667)
    )


def test_external_macro_rows_use_index_daily_bar_for_us_index_returns() -> None:
    dates = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(25)]
    macro_dates = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(25)]
    yfinance_catalog = FakeCatalog(
        {
            "index_daily_bar": pl.DataFrame(
                {
                    "trade_date": [*dates, *dates],
                    "symbol": ["^GSPC"] * 25 + ["^IXIC"] * 25,
                    "close": [100.0 + offset for offset in range(25)]
                    + [200.0 + offset for offset in range(25)],
                }
            ),
            "macro_indicators": pl.DataFrame(
                {
                    "trade_date": [*macro_dates, *macro_dates],
                    "symbol": ["GC=F"] * 25 + ["CL=F"] * 25,
                    "close": [100.0 + offset for offset in range(25)]
                    + [80.0 + offset for offset in range(25)],
                },
                schema={"trade_date": pl.Date, "symbol": pl.Utf8, "close": pl.Float64},
            ),
        }
    )
    alphavantage_catalog = FakeCatalog(
        {
            "macro_indicators": pl.DataFrame(
                {
                    "trade_date": dates,
                    "symbol": ["CNH=X"] * 25,
                    "close": [7.0 - offset * 0.01 for offset in range(25)],
                },
                schema={"trade_date": pl.Date, "symbol": pl.Utf8, "close": pl.Float64},
            ),
        }
    )

    cutoff_date = date(2026, 1, 24)
    rows = _external_macro_rows(
        yfinance_catalog,
        alphavantage_catalog,
        date(2026, 1, 25),
        external_cutoff_date=cutoff_date,
    )
    rows_by_metric = {str(row["metric_id"]): row for row in rows}

    assert rows_by_metric["macro_sp500_20d_return_temperature"]["status"] == "ok"
    assert rows_by_metric["macro_nasdaq_20d_return_temperature"]["status"] == "ok"
    assert rows_by_metric["macro_cnh_20d_change_temperature"]["status"] == "ok"
    assert rows_by_metric["macro_gold_20d_return_pressure"]["status"] == "ok"
    assert rows_by_metric["macro_oil_20d_return_pressure"]["status"] == "ok"
    assert rows_by_metric["macro_external_environment_temperature"]["sample_size"] == 2
    assert {end_date for _, end_date in yfinance_catalog.load_calls} == {cutoff_date}
    assert {end_date for _, end_date in alphavantage_catalog.load_calls} == {cutoff_date}


def test_external_macro_rows_default_cutoff_excludes_same_day_data() -> None:
    as_of_date = date(2026, 1, 25)
    cutoff_date = date(2026, 1, 24)
    frame = pl.DataFrame(
        {
            "symbol": ["^GSPC"],
            "trade_date": [as_of_date],
            "close": [100.0],
            "value": [100.0],
        }
    )
    catalog = FakeCatalog({"macro_indicators": frame, "index_daily_bar": frame})

    _external_macro_rows(catalog, catalog, as_of_date)

    assert catalog.load_calls
    assert {end_date for _, end_date in catalog.load_calls} == {cutoff_date}


def test_us_macro_background_rows_build_fred_observation_metrics() -> None:
    monthly_dates = _month_dates(date(2025, 1, 1), 14)
    quarterly_dates = [date(2025, 1, 1), date(2025, 4, 1), date(2025, 7, 1)]
    quarterly_dates.extend([date(2025, 10, 1), date(2026, 1, 1)])
    frame = pl.DataFrame(
        {
            "trade_date": [
                date(2026, 1, 1),
                date(2026, 1, 2),
                date(2026, 1, 3),
                date(2026, 1, 1),
                date(2026, 1, 2),
                date(2026, 1, 3),
                date(2026, 1, 1),
                date(2026, 1, 2),
                date(2026, 1, 3),
                date(2026, 1, 1),
                date(2026, 1, 2),
                date(2026, 1, 3),
                *monthly_dates,
                *monthly_dates,
                *quarterly_dates,
            ],
            "symbol": [
                "T10Y2Y",
                "T10Y2Y",
                "T10Y2Y",
                "FEDFUNDS",
                "FEDFUNDS",
                "FEDFUNDS",
                "WALCL",
                "WALCL",
                "WALCL",
                "UNRATE",
                "UNRATE",
                "UNRATE",
                *(["CPIAUCSL"] * len(monthly_dates)),
                *(["PAYEMS"] * len(monthly_dates)),
                *(["GDP"] * len(quarterly_dates)),
            ],
            "value": [
                0.1,
                0.2,
                0.3,
                5.50,
                5.25,
                5.00,
                7_000_000.0,
                7_100_000.0,
                7_200_000.0,
                5.0,
                4.8,
                4.6,
                *[100.0 + offset for offset in range(len(monthly_dates))],
                *[1_000.0 + offset * 10.0 for offset in range(len(monthly_dates))],
                100.0,
                101.0,
                102.0,
                103.0,
                105.0,
            ],
        }
    )
    catalog = FakeCatalog({"macro_indicators": frame})

    cutoff_date = date(2026, 1, 31)
    rows = _us_macro_background_rows(
        catalog,
        date(2026, 2, 1),
        external_cutoff_date=cutoff_date,
    )
    rows_by_metric = {str(row["metric_id"]): row for row in rows}

    expected = {
        "macro_fred_t10y2y_temperature",
        "macro_fred_fedfunds_temperature",
        "macro_fred_walcl_temperature",
        "macro_fred_cpi_yoy_temperature",
        "macro_fred_unrate_temperature",
        "macro_fred_payems_yoy_temperature",
        "macro_fred_gdp_yoy_temperature",
    }
    assert set(rows_by_metric) == expected
    assert all(
        rows_by_metric[metric_id]["status"] == "ok"
        for metric_id in expected - {"macro_fred_gdp_yoy_temperature"}
    )
    assert rows_by_metric["macro_fred_gdp_yoy_temperature"]["status"] == "insufficient"
    assert rows_by_metric["macro_fred_cpi_yoy_temperature"]["sample_size"] == 2
    assert rows_by_metric["macro_fred_gdp_yoy_temperature"]["sample_size"] == 1
    assert "月频背景观察" in rows_by_metric["macro_fred_cpi_yoy_temperature"]["note"]
    assert "latest_date=2026-01-01" in rows_by_metric["macro_fred_gdp_yoy_temperature"]["note"]
    assert {end_date for _, end_date in catalog.load_calls} == {cutoff_date}


def _month_dates(start: date, count: int) -> list[date]:
    return [
        date(start.year + (start.month - 1 + offset) // 12, (start.month - 1 + offset) % 12 + 1, 1)
        for offset in range(count)
    ]


def _component(metric_id: str, value: float | None, *, status: str = "ok") -> dict[str, object]:
    return {
        "metric_id": metric_id,
        "status": status,
        "value_float": value,
    }
