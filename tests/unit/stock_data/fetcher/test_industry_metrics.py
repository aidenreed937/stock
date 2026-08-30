"""垂直产业景气事实表与独立采集器 (Semiconductor/Nev/Solar) 单元测试。"""

from datetime import date
from pathlib import Path

from stock_data.fetcher.industry import (
    NEV_MONTHLY_SCHEMA,
    NON_FERROUS_METALS_SCHEMA,
    PHARMA_LICENSE_OUT_SCHEMA,
    SEMICONDUCTOR_SALES_SCHEMA,
    SOLAR_CAPACITY_SCHEMA,
    TRANSFORMER_EXPORT_SCHEMA,
    CloudCapexRecord,
    ConstructionMachineryRecord,
    NevCollector,
    NonFerrousCollector,
    NonFerrousMetalsRecord,
    OpticalModuleExportRecord,
    PharmaBdCollector,
    PharmaLicenseOutRecord,
    SemiconductorSalesRecord,
    ShippingIndicesRecord,
    SolarCollector,
    TransformerCollector,
    TransformerExportRecord,
    empty_nev_monthly,
    empty_non_ferrous_metals,
    empty_pharma_license_out,
    empty_semiconductor_sales,
    empty_solar_capacity,
    empty_transformer_export,
    get_month_end_date,
    records_to_cloud_capex_frame,
    records_to_machinery_frame,
    records_to_metals_frame,
    records_to_nev_frame,
    records_to_optical_frame,
    records_to_pharma_bd_frame,
    records_to_semiconductor_frame,
    records_to_shipping_frame,
    records_to_solar_frame,
    records_to_transformer_frame,
    save_curated_fact,
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


def test_non_ferrous_metals_frame_conversion() -> None:
    assert empty_non_ferrous_metals().schema == NON_FERROUS_METALS_SCHEMA

    records = [
        NonFerrousMetalsRecord(
            report_date="2026-06-30",
            trade_date=date(2026, 6, 30),
            lithium_carbonate_price=85000.0,
            shfe_copper_price=78000.0,
            shfe_aluminum_price=20500.0,
            sge_gold_price=575.5,
            copper_inventory_ton=125000.0,
            source="AkShare",
            source_url="https://akshare.akfamily.xyz/",
            release_date=date(2026, 6, 30),
            data_status="actual",
        )
    ]
    df = records_to_metals_frame(records)
    assert not df.is_empty()
    assert df["shfe_copper_price"][0] == 78000.0
    assert df["lithium_carbonate_price"][0] == 85000.0
    assert df["sge_gold_price"][0] == 575.5
    assert df["copper_inventory_ton"][0] == 125000.0
    assert df["unit"][0] == "mixed"
    assert df["source"][0] == "AkShare"


def test_non_ferrous_collector_and_frame_conversion(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw_industry"
    metals_dir = raw_dir / "metals"
    metals_dir.mkdir(parents=True)
    raw_csv = metals_dir / "commodity_prices.csv"
    raw_csv.write_text(
        "report_date,trade_date,lithium_carbonate_price,shfe_copper_price,shfe_aluminum_price,sge_gold_price,copper_inventory_ton,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-06-30,2026-06-30,86000.0,79000.0,20600.0,580.0,130000.0,mixed,AkShare,,2026-06-30,actual,2026-06-30T16:00:00Z\n",
        encoding="utf-8",
    )

    collector = NonFerrousCollector(raw_dir=raw_dir)
    records = collector.collect()
    assert len(records) == 1
    rec = records[0]
    assert rec.report_date == "2026-06-30"
    assert rec.trade_date == date(2026, 6, 30)
    assert rec.lithium_carbonate_price == 86000.0
    assert rec.shfe_copper_price == 79000.0

    df = records_to_metals_frame(records)
    assert not df.is_empty()
    assert df["shfe_copper_price"][0] == 79000.0


def test_non_ferrous_collector_akshare_mock(monkeypatch: object) -> None:
    import sys
    import types

    import pandas as pd

    # 构造 mock akshare 模块
    mock_ak = types.ModuleType("akshare")
    mock_ak.futures_main_sina = lambda symbol: pd.DataFrame(  # type: ignore[attr-defined]
        [
            {
                "date": "2026-06-30",
                "close": 78500.0 if symbol == "CU0" else (20500.0 if symbol == "AL0" else 85000.0),
            }
        ]
    )
    mock_ak.spot_hist_sge = lambda symbol: pd.DataFrame(  # type: ignore[attr-defined]
        [{"date": "2026-06-30", "close": 575.0}]
    )
    mock_ak.futures_inventory_em = lambda symbol: pd.DataFrame(  # type: ignore[attr-defined]
        [{"日期": "2026-06-30", "库存": 120000.0}]
    )
    sys.modules["akshare"] = mock_ak

    collector = NonFerrousCollector(raw_dir=Path("/non_existent_dir"))
    records = collector.fetch_from_akshare()
    assert len(records) == 1
    rec = records[0]
    assert rec.trade_date == date(2026, 6, 30)
    assert rec.shfe_copper_price == 78500.0
    assert rec.lithium_carbonate_price == 85000.0
    assert rec.sge_gold_price == 575.0
    assert rec.copper_inventory_ton == 120000.0


def test_transformer_export_frame_conversion() -> None:
    assert empty_transformer_export().schema == TRANSFORMER_EXPORT_SCHEMA

    records = [
        TransformerExportRecord(
            report_month="2026-05",
            trade_date=date(2026, 5, 31),
            export_value_million_usd=850.0,
            export_volume_units=450000.0,
        ),
        TransformerExportRecord(
            report_month="2026-06",
            trade_date=date(2026, 6, 30),
            export_value_million_usd=920.0,
            export_volume_units=470000.0,
        ),
    ]
    df = records_to_transformer_frame(records)
    assert not df.is_empty()
    assert df.height == 2
    assert "export_value_3mma" in df.columns
    assert "yoy_growth_3mma" in df.columns
    assert "export_asp_usd" in df.columns
    assert df["export_value_million_usd"][1] == 920.0


def test_pharma_bd_frame_conversion() -> None:
    assert empty_pharma_license_out().schema == PHARMA_LICENSE_OUT_SCHEMA

    records = [
        PharmaLicenseOutRecord(
            report_month="2026-05",
            trade_date=date(2026, 5, 31),
            monthly_upfront_million_usd=650.0,
            monthly_total_deal_million_usd=4500.0,
            deal_count=12,
        ),
        PharmaLicenseOutRecord(
            report_month="2026-06",
            trade_date=date(2026, 6, 30),
            monthly_upfront_million_usd=820.0,
            monthly_total_deal_million_usd=6200.0,
            deal_count=15,
        ),
    ]
    df = records_to_pharma_bd_frame(records)
    assert not df.is_empty()
    assert df.height == 2
    assert "upfront_3mma" in df.columns
    assert "total_deal_3mma" in df.columns
    assert df["monthly_upfront_million_usd"][1] == 820.0
    assert df["deal_count"][1] == 15


def test_transformer_and_pharma_collectors(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw_industry"
    (raw_dir / "customs").mkdir(parents=True)
    (raw_dir / "pharma").mkdir(parents=True)

    (raw_dir / "customs" / "transformer_export.csv").write_text(
        "report_month,trade_date,export_value_million_usd,export_volume_units,export_asp_usd,export_value_3mma,yoy_growth,yoy_growth_3mma,mom_growth_3mma,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-05,2026-05-31,850.0,450000.0,1888.89,,,,,million_usd,GACC,,2026-06-20,actual,\n",
        encoding="utf-8",
    )
    (raw_dir / "pharma" / "license_out_monthly.csv").write_text(
        "report_month,trade_date,monthly_upfront_million_usd,monthly_total_deal_million_usd,deal_count,upfront_3mma,yoy_growth_3mma,mom_growth_3mma,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-05,2026-05-31,650.0,4500.0,12,,,,million_usd,PharmaCube,,2026-06-15,actual,\n",
        encoding="utf-8",
    )

    t_collector = TransformerCollector(raw_dir=raw_dir)
    t_records = t_collector.collect()
    assert len(t_records) == 1
    assert t_records[0].export_value_million_usd == 850.0

    p_collector = PharmaBdCollector(raw_dir=raw_dir)
    p_records = p_collector.collect()
    assert len(p_records) == 1
    assert p_records[0].monthly_upfront_million_usd == 650.0


def test_optical_module_frame_conversion() -> None:
    records = [
        OpticalModuleExportRecord(
            report_month="2026-05",
            trade_date=date(2026, 5, 31),
            export_value_million_usd=1200.0,
            export_volume_ten_thousand=150.0,
            export_asp_usd=800.0,
        ),
        OpticalModuleExportRecord(
            report_month="2026-06",
            trade_date=date(2026, 6, 30),
            export_value_million_usd=1400.0,
            export_volume_ten_thousand=160.0,
            export_asp_usd=875.0,
        ),
    ]
    df = records_to_optical_frame(records)
    assert not df.is_empty()
    assert df.height == 2
    assert "export_value_3mma" in df.columns
    assert "export_asp_usd" in df.columns
    assert df["export_value_million_usd"][0] == 1200.0
    assert df["export_value_3mma"][1] == 1300.0


def test_cloud_capex_frame_conversion() -> None:
    records = [
        CloudCapexRecord(
            report_quarter="2026-Q1",
            trade_date=date(2026, 3, 31),
            total_capex_billion_usd=85.0,
            msft_capex_billion_usd=28.0,
            goog_capex_billion_usd=18.0,
            meta_capex_billion_usd=14.0,
            amzn_capex_billion_usd=25.0,
        ),
        CloudCapexRecord(
            report_quarter="2026-Q2",
            trade_date=date(2026, 6, 30),
            total_capex_billion_usd=95.0,
            msft_capex_billion_usd=31.0,
            goog_capex_billion_usd=20.0,
            meta_capex_billion_usd=16.0,
            amzn_capex_billion_usd=28.0,
        ),
    ]
    df = records_to_cloud_capex_frame(records)
    assert not df.is_empty()
    assert df.height == 2
    assert "total_capex_billion_usd" in df.columns
    assert "qoq_growth" in df.columns
    assert df["total_capex_billion_usd"][1] == 95.0


def test_construction_machinery_frame_conversion() -> None:
    records = [
        ConstructionMachineryRecord(
            report_month="2026-05",
            trade_date=date(2026, 5, 31),
            excavator_total_units=22000.0,
            excavator_domestic_units=11000.0,
            excavator_export_units=11000.0,
            komatsu_hours_china=105.0,
        ),
        ConstructionMachineryRecord(
            report_month="2026-06",
            trade_date=date(2026, 6, 30),
            excavator_total_units=24000.0,
            excavator_domestic_units=12000.0,
            excavator_export_units=12000.0,
            komatsu_hours_china=110.0,
        ),
    ]
    df = records_to_machinery_frame(records)
    assert not df.is_empty()
    assert df.height == 2
    assert "excavator_total_3mma" in df.columns
    assert "export_ratio" in df.columns
    assert df["excavator_total_units"][0] == 22000.0
    assert df["export_ratio"][0] == 0.5


def test_shipping_indices_frame_conversion() -> None:
    records = [
        ShippingIndicesRecord(
            trade_date=date(2026, 8, 27),
            bdi_index=1500.0,
            bdti_index=950.0,
            bcti_index=720.0,
            scfi_index=1350.0,
        ),
        ShippingIndicesRecord(
            trade_date=date(2026, 8, 28),
            bdi_index=1520.0,
            bdti_index=960.0,
            bcti_index=730.0,
            scfi_index=1360.0,
        ),
    ]
    df = records_to_shipping_frame(records)
    assert not df.is_empty()
    assert df.height == 2
    assert "bdi_index" in df.columns
    assert "bdti_index" in df.columns
    assert df["bdi_index"][1] == 1520.0


def test_save_curated_fact_and_sync_pipeline(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw_industry"
    curated_dir = tmp_path / "curated_industry"
    (raw_dir / "cpca").mkdir(parents=True)
    (raw_dir / "nea").mkdir(parents=True)
    (raw_dir / "metals").mkdir(parents=True)
    (raw_dir / "customs").mkdir(parents=True)
    (raw_dir / "pharma").mkdir(parents=True)
    (raw_dir / "cloud_capex").mkdir(parents=True)
    (raw_dir / "machinery").mkdir(parents=True)
    (raw_dir / "shipping").mkdir(parents=True)

    # 准备各模块 RAW CSV
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
    (raw_dir / "metals" / "commodity_prices.csv").write_text(
        "report_date,trade_date,lithium_carbonate_price,shfe_copper_price,shfe_aluminum_price,sge_gold_price,copper_inventory_ton,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-05-31,2026-05-31,85000.0,78000.0,20500.0,570.0,120000.0,mixed,AkShare,,2026-05-31,actual,\n",
        encoding="utf-8",
    )
    (raw_dir / "customs" / "transformer_export.csv").write_text(
        "report_month,trade_date,export_value_million_usd,export_volume_units,export_asp_usd,export_value_3mma,yoy_growth,yoy_growth_3mma,mom_growth_3mma,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-05,2026-05-31,850.0,450000.0,1888.89,,,,,million_usd,GACC,,2026-06-20,actual,\n",
        encoding="utf-8",
    )
    (raw_dir / "customs" / "optical_module_export.csv").write_text(
        "report_month,trade_date,export_value_million_usd,export_volume_ten_thousand,export_asp_usd,export_value_3mma,yoy_growth,yoy_growth_3mma,mom_growth_3mma,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-05,2026-05-31,1200.0,150.0,800.00,,,,,million_usd,GACC,,2026-06-20,actual,\n",
        encoding="utf-8",
    )
    (raw_dir / "pharma" / "license_out_monthly.csv").write_text(
        "report_month,trade_date,monthly_upfront_million_usd,monthly_total_deal_million_usd,deal_count,upfront_3mma,yoy_growth_3mma,mom_growth_3mma,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-05,2026-05-31,650.0,4500.0,12,,,,million_usd,PharmaCube,,2026-06-15,actual,\n",
        encoding="utf-8",
    )
    (raw_dir / "cloud_capex" / "csp_capex_quarterly.csv").write_text(
        "report_quarter,trade_date,total_capex_billion_usd,msft_capex_billion_usd,goog_capex_billion_usd,meta_capex_billion_usd,amzn_capex_billion_usd,yoy_growth,qoq_growth,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-Q1,2026-03-31,85.0,28.0,18.0,14.0,25.0,,,billion_usd,Company Filings,,2026-04-28,actual,\n",
        encoding="utf-8",
    )
    (raw_dir / "machinery" / "excavator_monthly.csv").write_text(
        "report_month,trade_date,excavator_total_units,excavator_domestic_units,excavator_export_units,komatsu_hours_china,komatsu_hours_yoy,export_ratio,excavator_total_3mma,yoy_growth,yoy_growth_3mma,mom_growth_3mma,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-05,2026-05-31,22000.0,11000.0,11000.0,105.0,,0.5000,,,,,units/hours,CCMA/Komatsu,,2026-06-08,actual,\n",
        encoding="utf-8",
    )
    (raw_dir / "shipping" / "freight_indices.csv").write_text(
        "trade_date,bdi_index,bdti_index,bcti_index,scfi_index,bdi_ma200_bias,bdti_ma200_bias,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-05-31,1500.0,950.0,720.0,1350.0,,,index_points,BalticExchange,,2026-05-31,actual,\n",
        encoding="utf-8",
    )

    # 1. 全量同步
    res = sync_all_industry_metrics(raw_dir=raw_dir, curated_dir=curated_dir)
    assert res.get("nev_monthly_sales", 0) == 1
    assert res.get("solar_capacity", 0) == 1
    assert res.get("non_ferrous_metals", 0) == 1
    assert res.get("transformer_export", 0) == 1
    assert res.get("pharma_license_out", 0) == 1
    assert res.get("optical_module_export", 0) == 1
    assert res.get("cloud_capex_quarterly", 0) == 1
    assert res.get("construction_machinery", 0) == 1
    assert res.get("shipping_indices", 0) == 1
    assert (curated_dir / "construction_machinery.parquet").exists()
    assert (curated_dir / "shipping_indices.parquet").exists()

    # 2. 单个 metric 同步
    res_single = sync_all_industry_metrics(
        raw_dir=raw_dir, curated_dir=curated_dir, metrics=["construction_machinery"]
    )
    assert len(res_single) == 1
    assert "construction_machinery" in res_single


def test_watermark_incremental_merge_and_idempotence(tmp_path: Path) -> None:
    parquet_path = tmp_path / "transformer_export.parquet"
    rec1 = TransformerExportRecord(
        report_month="2026-05",
        trade_date=date(2026, 5, 31),
        export_value_million_usd=850.0,
        export_volume_units=450000.0,
        export_asp_usd=1888.89,
        release_date=date(2026, 6, 20),
    )
    df1 = records_to_transformer_frame([rec1])
    assert save_curated_fact(df1, parquet_path, primary_keys=["report_month"]) == 1

    # 增量追加次月新记录推进水位
    rec2 = TransformerExportRecord(
        report_month="2026-06",
        trade_date=date(2026, 6, 30),
        export_value_million_usd=920.0,
        export_volume_units=470000.0,
        export_asp_usd=1957.45,
        release_date=date(2026, 7, 20),
    )
    df2 = records_to_transformer_frame([rec2])
    assert save_curated_fact(df2, parquet_path, primary_keys=["report_month"]) == 2

    # 重复写入相同的次月记录，验证严格幂等去重
    assert save_curated_fact(df2, parquet_path, primary_keys=["report_month"]) == 2
