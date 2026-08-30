"""垂直产业景气事实表与独立采集器 (Semiconductor/Nev/Solar) 单元测试。"""

from datetime import date
from pathlib import Path

from stock_data.fetcher.industry import (
    NEV_MONTHLY_SCHEMA,
    SEMICONDUCTOR_SALES_SCHEMA,
    SOLAR_CAPACITY_SCHEMA,
    NevCollector,
    SemiconductorSalesRecord,
    SolarCollector,
    empty_nev_monthly,
    empty_semiconductor_sales,
    empty_solar_capacity,
    get_month_end_date,
    records_to_nev_frame,
    records_to_semiconductor_frame,
    records_to_solar_frame,
    sync_all_industry_metrics,
)


def test_get_month_end_date() -> None:
    assert get_month_end_date(2026, 2) == date(2026, 2, 28)
    assert get_month_end_date(2024, 2) == date(2024, 2, 29)
    assert get_month_end_date(2026, 6) == date(2026, 6, 30)
    assert get_month_end_date(2026, 7) == date(2026, 7, 31)


def test_semiconductor_sales_frame_conversion() -> None:
    assert empty_semiconductor_sales().schema == SEMICONDUCTOR_SALES_SCHEMA

    records = [
        SemiconductorSalesRecord(
            report_month="2026-05",
            trade_date=date(2026, 5, 31),
            global_sales_usd=120.6,
            china_sales_usd=38.5,
            yoy_growth=1.041,
            mom_growth=0.092,
            source="SIA/WSTS",
            source_url="https://www.semiconductors.org/test/",
            release_date=date(2026, 7, 6),
            data_status="actual",
        )
    ]
    df = records_to_semiconductor_frame(records)
    assert not df.is_empty()
    assert df["global_sales_usd"][0] == 120.6
    assert df["china_sales_usd"][0] == 38.5
    assert df["yoy_growth"][0] == 1.041
    assert df["mom_growth"][0] == 0.092
    assert df["unit"][0] == "billion_usd"
    assert df["source"][0] == "SIA/WSTS"
    assert df["data_status"][0] == "actual"
    assert df["release_date"][0] == date(2026, 7, 6)


def test_semiconductor_collector_article_parsing() -> None:
    mock_article = """
    <html>
        <body>
            <p>WASHINGTON, July 6, 2026—The Semiconductor Industry Association (SIA) today announced global semiconductor sales were $120.6 billion during the month of May 2026, an increase of 9.2% compared to the April 2026 total of $110.5 billion and 104.1% more than the May 2025 total of $59.1 billion.</p>
        </body>
    </html>
    """
    from stock_data.fetcher.industry.semiconductor import parse_sia_china_and_date

    enrich = parse_sia_china_and_date(
        mock_article, source_url="https://www.semiconductors.org/may-2026/"
    )
    assert enrich is not None
    assert enrich["report_month"] == "2026-05"
    assert enrich["release_date"] == date(2026, 7, 6)
    assert enrich["source_url"] == "https://www.semiconductors.org/may-2026/"


def test_nev_collector_and_frame_conversion(tmp_path: Path) -> None:
    assert empty_nev_monthly().schema == NEV_MONTHLY_SCHEMA

    raw_dir = tmp_path / "raw_industry"
    cpca_dir = raw_dir / "cpca"
    cpca_dir.mkdir(parents=True)
    raw_csv = cpca_dir / "nev_monthly_sales.csv"
    raw_csv.write_text(
        "report_month,trade_date,wholesale_volume_ten_thousand,retail_volume_ten_thousand,export_volume_ten_thousand,penetration_rate,battery_installation_gwh,yoy_growth,source,source_url,release_date,data_status,collected_at\n"
        "2026-06,2026-06-30,148.1,100.7,18.5,0.518,48.2,0.285,CPCA,http://www.cpcaauto.com/,2026-07-08,actual,2026-07-08T10:00:00Z\n",
        encoding="utf-8",
    )

    collector = NevCollector(raw_dir=raw_dir)
    records = collector.collect()
    assert len(records) == 1
    rec = records[0]
    assert rec.report_month == "2026-06"
    assert rec.trade_date == date(2026, 6, 30)
    assert rec.wholesale_volume_ten_thousand == 148.1
    assert rec.retail_volume_ten_thousand == 100.7
    assert rec.penetration_rate == 0.518
    assert rec.yoy_growth == 0.285

    df = records_to_nev_frame(records)
    assert not df.is_empty()
    assert df["penetration_rate"][0] == 0.518
    assert df["unit"][0] == "ten_thousand_units"
    assert df["source"][0] == "CPCA"


def test_solar_collector_and_frame_conversion(tmp_path: Path) -> None:
    assert empty_solar_capacity().schema == SOLAR_CAPACITY_SCHEMA

    raw_dir = tmp_path / "raw_industry"
    nea_dir = raw_dir / "nea"
    nea_dir.mkdir(parents=True)
    raw_csv = nea_dir / "solar_capacity.csv"
    raw_csv.write_text(
        "report_month,trade_date,monthly_new_capacity_gw,cumulative_capacity_gw,yoy_growth,source,source_url,release_date,data_status,collected_at\n"
        "2026-06,2026-06-30,24.5,1272.0,0.182,NEA,http://www.nea.gov.cn/,2026-07-22,actual,2026-07-22T10:00:00Z\n",
        encoding="utf-8",
    )

    collector = SolarCollector(raw_dir=raw_dir)
    records = collector.collect()
    assert len(records) == 1
    rec = records[0]
    assert rec.report_month == "2026-06"
    assert rec.trade_date == date(2026, 6, 30)
    assert rec.monthly_new_capacity_gw == 24.5
    assert rec.cumulative_capacity_gw == 1272.0
    assert rec.source == "NEA"

    df = records_to_solar_frame(records)
    assert not df.is_empty()
    assert df["cumulative_capacity_gw"][0] == 1272.0
    assert df["unit"][0] == "gw"
    assert df["source"][0] == "NEA"


def test_save_curated_fact_and_sync_pipeline(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw_industry"
    curated_dir = tmp_path / "curated_industry"
    (raw_dir / "cpca").mkdir(parents=True)
    (raw_dir / "nea").mkdir(parents=True)

    # 准备 CPCA & NEA RAW CSV
    (raw_dir / "cpca" / "nev_monthly_sales.csv").write_text(
        "report_month,trade_date,wholesale_volume_ten_thousand,retail_volume_ten_thousand,export_volume_ten_thousand,penetration_rate,battery_installation_gwh,yoy_growth,source,source_url,release_date,data_status,collected_at\n"
        "2026-05,2026-05-31,130.0,90.0,15.0,0.490,40.0,0.300,CPCA,,2026-06-08,actual,\n",
        encoding="utf-8",
    )
    (raw_dir / "nea" / "solar_capacity.csv").write_text(
        "report_month,trade_date,monthly_new_capacity_gw,cumulative_capacity_gw,yoy_growth,source,source_url,release_date,data_status,collected_at\n"
        "2026-05,2026-05-31,20.0,1247.5,0.150,NEA,,2026-06-20,actual,\n",
        encoding="utf-8",
    )

    res = sync_all_industry_metrics(raw_dir=raw_dir, curated_dir=curated_dir)
    assert res.get("nev_monthly_sales", 0) == 1
    assert res.get("solar_capacity", 0) == 1
    assert (curated_dir / "nev_monthly_sales.parquet").exists()
    assert (curated_dir / "nev_monthly_sales.csv").exists()
    assert (curated_dir / "solar_capacity.parquet").exists()
    assert (curated_dir / "solar_capacity.csv").exists()
