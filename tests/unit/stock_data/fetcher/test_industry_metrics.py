"""垂直产业景气事实表（半导体销售额、新能源车销量、光伏装机）单元测试。"""

from datetime import date

from stock_data.fetcher.industry import (
    NEV_MONTHLY_SCHEMA,
    SEMICONDUCTOR_SALES_SCHEMA,
    SOLAR_CAPACITY_SCHEMA,
    NevMonthlyRecord,
    SemiconductorSalesRecord,
    SolarCapacityRecord,
    empty_nev_monthly,
    empty_semiconductor_sales,
    empty_solar_capacity,
    records_to_nev_frame,
    records_to_semiconductor_frame,
    records_to_solar_frame,
)


def test_semiconductor_sales_frame_conversion() -> None:
    assert empty_semiconductor_sales().schema == SEMICONDUCTOR_SALES_SCHEMA

    records = [
        SemiconductorSalesRecord(
            report_month="2026-06",
            trade_date=date(2026, 6, 30),
            global_sales_usd=50.0,
            americas_sales_usd=15.0,
            china_sales_usd=16.0,
            yoy_growth=0.18,
            mom_growth=0.02,
        )
    ]
    df = records_to_semiconductor_frame(records)
    assert not df.is_empty()
    assert df["global_sales_usd"][0] == 50.0
    assert df["yoy_growth"][0] == 0.18
    assert df["report_month"][0] == "2026-06"


def test_nev_monthly_frame_conversion() -> None:
    assert empty_nev_monthly().schema == NEV_MONTHLY_SCHEMA

    records = [
        NevMonthlyRecord(
            report_month="2026-07",
            trade_date=date(2026, 7, 31),
            wholesale_volume_ten_thousand=100.0,
            retail_volume_ten_thousand=95.0,
            penetration_rate=0.51,
            battery_installation_gwh=45.0,
            yoy_growth=0.30,
        )
    ]
    df = records_to_nev_frame(records)
    assert not df.is_empty()
    assert df["wholesale_volume_ten_thousand"][0] == 100.0
    assert df["penetration_rate"][0] == 0.51


def test_solar_capacity_frame_conversion() -> None:
    assert empty_solar_capacity().schema == SOLAR_CAPACITY_SCHEMA

    records = [
        SolarCapacityRecord(
            report_month="2026-07",
            trade_date=date(2026, 7, 31),
            monthly_new_capacity_gw=20.5,
            cumulative_capacity_gw=750.0,
            yoy_growth=0.25,
        )
    ]
    df = records_to_solar_frame(records)
    assert not df.is_empty()
    assert df["monthly_new_capacity_gw"][0] == 20.5
    assert df["yoy_growth"][0] == 0.25
