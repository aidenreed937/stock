"""垂直产业景气事实表与独立采集器 (Semiconductor/Nev/Solar/Metals/Pharma/Cloud/Machinery/Shipping) 单元测试。"""

from datetime import date
from pathlib import Path

from stock_data.fetcher.industry import (
    CLOUD_CAPEX_SCHEMA,
    CONSTRUCTION_MACHINERY_SCHEMA,
    NEV_MONTHLY_SCHEMA,
    NON_FERROUS_METALS_SCHEMA,
    PHARMA_LICENSE_OUT_SCHEMA,
    SEMICONDUCTOR_SALES_SCHEMA,
    SHIPPING_INDICES_SCHEMA,
    SOLAR_CAPACITY_SCHEMA,
    CloudCapexRecord,
    ConstructionMachineryRecord,
    CustomsTradeRecord,
    NevCollector,
    NevMonthlyRecord,
    NonFerrousCollector,
    NonFerrousMetalsRecord,
    PharmaLicenseOutRecord,
    SemiconductorCollector,
    SemiconductorSalesRecord,
    ShippingIndicesRecord,
    SolarCapacityRecord,
    SolarCollector,
    empty_cloud_capex,
    empty_construction_machinery,
    empty_nev_monthly,
    empty_non_ferrous_metals,
    empty_pharma_license_out,
    empty_semiconductor_sales,
    empty_shipping_indices,
    empty_solar_capacity,
    get_month_end_date,
    read_raw_text,
    records_to_cloud_capex_frame,
    records_to_customs_trade_frame,
    records_to_machinery_frame,
    records_to_metals_frame,
    records_to_nev_frame,
    records_to_pharma_bd_frame,
    records_to_semiconductor_frame,
    records_to_shipping_frame,
    records_to_solar_frame,
    save_curated_fact,
    save_raw_snapshot,
    sync_all_industry_metrics,
)


def test_get_month_end_date() -> None:
    assert get_month_end_date(2026, 2) == date(2026, 2, 28)
    assert get_month_end_date(2024, 2) == date(2024, 2, 29)
    assert get_month_end_date(2026, 6) == date(2026, 6, 30)


def test_semiconductor_frame_conversion() -> None:
    assert empty_semiconductor_sales().schema == SEMICONDUCTOR_SALES_SCHEMA

    records = [
        SemiconductorSalesRecord(
            report_month="2026-05",
            trade_date=date(2026, 5, 31),
            global_sales_usd=48.5,
            china_sales_usd=14.2,
            yoy_growth=0.152,
        ),
        SemiconductorSalesRecord(
            report_month="2026-06",
            trade_date=date(2026, 6, 30),
            global_sales_usd=51.0,
            china_sales_usd=15.0,
            yoy_growth=0.185,
        ),
    ]

    df = records_to_semiconductor_frame(records)
    assert not df.is_empty()
    assert df.height == 2
    assert "global_sales_usd" in df.columns
    assert "china_sales_usd" in df.columns
    assert df["global_sales_usd"][1] == 51.0
    assert df["unit"][0] == "billion_usd"
    assert df["source"][0] == "SIA/WSTS"


def test_nev_monthly_frame_conversion() -> None:
    assert empty_nev_monthly().schema == NEV_MONTHLY_SCHEMA

    records = [
        NevMonthlyRecord(
            report_month="2026-05",
            trade_date=date(2026, 5, 31),
            wholesale_volume_ten_thousand=95.0,
            retail_volume_ten_thousand=89.6,
            export_volume_ten_thousand=14.5,
            penetration_rate=0.485,
            battery_installation_gwh=58.9,
            yoy_growth=0.32,
        ),
        NevMonthlyRecord(
            report_month="2026-06",
            trade_date=date(2026, 6, 30),
            wholesale_volume_ten_thousand=101.0,
            retail_volume_ten_thousand=94.8,
            export_volume_ten_thousand=15.2,
            penetration_rate=0.505,
            battery_installation_gwh=63.4,
            yoy_growth=0.35,
        ),
    ]

    df = records_to_nev_frame(records)
    assert not df.is_empty()
    assert df.height == 2
    assert "wholesale_volume_3mma" in df.columns
    assert "yoy_growth_3mma" in df.columns
    assert df["wholesale_volume_ten_thousand"][1] == 101.0
    assert df["retail_volume_ten_thousand"][1] == 94.8
    assert df["export_volume_ten_thousand"][1] == 15.2
    assert df["battery_installation_gwh"][1] == 63.4
    assert df["penetration_rate"][1] == 0.505
    assert df["unit"][0] == "ten_thousand_units"


def test_nev_collector_from_raw_csv(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw_industry"
    cpca_dir = raw_dir / "cpca"
    cpca_dir.mkdir(parents=True)
    raw_csv = cpca_dir / "nev_monthly_sales.csv"
    raw_csv.write_text(
        "report_month,trade_date,wholesale_volume_ten_thousand,retail_volume_ten_thousand,export_volume_ten_thousand,penetration_rate,battery_installation_gwh,yoy_growth,source,source_url,release_date,data_status,collected_at\n"
        "2026-06,2026-06-30,101.0,94.8,15.2,0.505,63.4,0.35,CPCA,http://www.cpcaauto.com/,2026-07-10,actual,2026-07-10T10:00:00Z\n",
        encoding="utf-8",
    )

    collector = NevCollector(raw_dir=raw_dir)
    records = collector.collect()
    assert len(records) == 1
    rec = records[0]
    assert rec.report_month == "2026-06"
    assert rec.wholesale_volume_ten_thousand == 101.0
    assert rec.retail_volume_ten_thousand == 94.8
    assert rec.export_volume_ten_thousand == 15.2
    assert rec.battery_installation_gwh == 63.4
    assert rec.penetration_rate == 0.505

    df = records_to_nev_frame(records)
    assert not df.is_empty()
    assert df["wholesale_volume_ten_thousand"][0] == 101.0
    assert df["battery_installation_gwh"][0] == 63.4


def test_automotive_bulletin_parsers() -> None:
    from stock_data.fetcher.industry.automotive.crawler import (
        parse_cabia_battery_article,
        parse_cpca_bulletin_article,
    )

    # 1. 验证 CABIA 电池装机通报解析
    cabia_text = (
        "2026年7月，我国动力电池装车量59.8GWh，同比增长18.5%。"
        "其中三元电池装车量18.2GWh，占总装车量30.4%；磷酸铁锂电池装车量41.6GWh，占总装车量69.6%。"
    )
    cabia_res = parse_cabia_battery_article(cabia_text)
    assert cabia_res is not None
    assert cabia_res["report_month"] == "2026-07"
    assert cabia_res["battery_installation_gwh"] == 59.8
    assert cabia_res["yoy_growth"] == 0.185

    # 2. 验证 CPCA 乘联会月报解析
    cpca_text = (
        "2026年7月新能源乘用车批发销量达到95.13万辆，同比增长15.2%；"
        "7月新能源乘用车国内零售销量达到89.2万辆，同比增长14.8%；"
        "7月新能源乘用车出口14.8万辆，同比增长16.5%。新能源车国内零售渗透率达到48.2%。"
    )
    cpca_res = parse_cpca_bulletin_article(cpca_text)
    assert cpca_res is not None
    assert cpca_res["report_month"] == "2026-07"
    assert cpca_res["wholesale_volume_ten_thousand"] == 95.13
    assert cpca_res["retail_volume_ten_thousand"] == 89.2
    assert cpca_res["export_volume_ten_thousand"] == 14.8


def test_solar_capacity_frame_conversion() -> None:
    assert empty_solar_capacity().schema == SOLAR_CAPACITY_SCHEMA

    records = [
        SolarCapacityRecord(
            report_month="2026-05",
            trade_date=date(2026, 5, 31),
            monthly_new_capacity_gw=21.0,
            cumulative_capacity_gw=1247.5,
            yoy_growth=0.15,
        ),
        SolarCapacityRecord(
            report_month="2026-06",
            trade_date=date(2026, 6, 30),
            monthly_new_capacity_gw=24.5,
            cumulative_capacity_gw=1272.0,
            yoy_growth=0.182,
        ),
    ]

    df = records_to_solar_frame(records)
    assert not df.is_empty()
    assert df.height == 2
    assert "monthly_new_capacity_3mma" in df.columns
    assert "yoy_growth_3mma" in df.columns
    assert df["cumulative_capacity_gw"][1] == 1272.0
    assert df["unit"][0] == "gw"


def test_solar_collector_from_raw_csv(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw_industry"
    nea_dir = raw_dir / "energy" / "cn_nea"
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


def test_cloud_capex_frame_conversion() -> None:
    assert empty_cloud_capex().schema == CLOUD_CAPEX_SCHEMA
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
    assert empty_construction_machinery().schema == CONSTRUCTION_MACHINERY_SCHEMA
    records = [
        ConstructionMachineryRecord(
            report_month="2026-05",
            trade_date=date(2026, 5, 31),
            excavator_total_units=18500.0,
            excavator_domestic_units=9500.0,
            excavator_export_units=9000.0,
            komatsu_hours_china=98.5,
            komatsu_hours_yoy=0.045,
            export_ratio=0.486,
        ),
        ConstructionMachineryRecord(
            report_month="2026-06",
            trade_date=date(2026, 6, 30),
            excavator_total_units=19200.0,
            excavator_domestic_units=9800.0,
            excavator_export_units=9400.0,
            komatsu_hours_china=102.0,
            komatsu_hours_yoy=0.062,
            export_ratio=0.490,
        ),
    ]
    df = records_to_machinery_frame(records)
    assert not df.is_empty()
    assert df.height == 2
    assert "excavator_total_3mma" in df.columns
    assert "yoy_growth_3mma" in df.columns
    assert df["excavator_total_units"][1] == 19200.0
    assert df["export_ratio"][0] == 0.486


def test_shipping_indices_frame_conversion() -> None:
    assert empty_shipping_indices().schema == SHIPPING_INDICES_SCHEMA
    records = [
        ShippingIndicesRecord(
            trade_date=date(2026, 6, 29),
            bdi_index=1650.0,
            bdti_index=1020.0,
            bcti_index=780.0,
            scfi_index=1420.0,
        ),
        ShippingIndicesRecord(
            trade_date=date(2026, 6, 30),
            bdi_index=1680.0,
            bdti_index=1035.0,
            bcti_index=795.0,
            scfi_index=1435.0,
        ),
    ]
    df = records_to_shipping_frame(records)
    assert not df.is_empty()
    assert df.height == 2
    assert df["bdi_index"][1] == 1680.0
    assert df["unit"][0] == "index_points"


def test_sync_all_industry_metrics_pipeline(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw_industry"
    curated_dir = tmp_path / "curated_industry"

    (raw_dir / "cpca").mkdir(parents=True)
    (raw_dir / "nea").mkdir(parents=True)
    (raw_dir / "metals").mkdir(parents=True)
    (raw_dir / "pharma").mkdir(parents=True)
    (raw_dir / "cloud_capex").mkdir(parents=True)
    (raw_dir / "machinery").mkdir(parents=True)
    (raw_dir / "shipping").mkdir(parents=True)

    (raw_dir / "cpca" / "nev_monthly_sales.csv").write_text(
        "report_month,trade_date,wholesale_volume_ten_thousand,penetration_rate,yoy_growth,source,source_url,release_date,data_status,collected_at\n"
        "2026-05,2026-05-31,95.0,0.485,0.32,CPCA,,2026-06-10,actual,\n",
        encoding="utf-8",
    )
    (raw_dir / "energy" / "cn_nea").mkdir(parents=True, exist_ok=True)
    (raw_dir / "energy" / "cn_nea" / "solar_capacity.csv").write_text(
        "report_month,trade_date,monthly_new_capacity_gw,cumulative_capacity_gw,yoy_growth,source,source_url,release_date,data_status,collected_at\n"
        "2026-05,2026-05-31,21.0,1247.5,0.15,NEA,,2026-06-22,actual,\n",
        encoding="utf-8",
    )
    (raw_dir / "metals" / "commodity_prices.csv").write_text(
        "report_date,trade_date,lithium_carbonate_price,shfe_copper_price,shfe_aluminum_price,sge_gold_price,copper_inventory_ton,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-05-31,2026-05-31,85000.0,78000.0,20500.0,575.5,125000.0,mixed,AkShare,,2026-05-31,actual,\n",
        encoding="utf-8",
    )
    (raw_dir / "pharma" / "license_out_monthly.csv").write_text(
        "report_month,trade_date,monthly_upfront_million_usd,monthly_total_deal_million_usd,deal_count,upfront_3mma,yoy_growth_3mma,mom_growth_3mma,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-05,2026-05-31,650.0,4500.0,12,,,,million_usd,PharmaCube,,2026-06-15,actual,\n",
        encoding="utf-8",
    )
    (raw_dir / "cloud_capex" / "csp_capex_quarterly.csv").write_text(
        "report_quarter,trade_date,total_capex_billion_usd,msft_capex_billion_usd,goog_capex_billion_usd,meta_capex_billion_usd,amzn_capex_billion_usd,yoy_growth,qoq_growth,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-Q1,2026-03-31,85.0,28.0,18.0,14.0,25.0,,,billion_usd,10-Q,,2026-04-25,actual,\n",
        encoding="utf-8",
    )
    (raw_dir / "machinery" / "excavator_monthly.csv").write_text(
        "report_month,trade_date,excavator_total_units,excavator_domestic_units,excavator_export_units,komatsu_hours_china,komatsu_hours_yoy,export_ratio,excavator_total_3mma,yoy_growth,yoy_growth_3mma,mom_growth_3mma,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-05,2026-05-31,18500.0,9500.0,9000.0,98.5,0.045,0.486,,,,,units/hours,CCMA,,2026-06-08,actual,\n",
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
    assert res.get("pharma_license_out", 0) == 1
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
    parquet_path = tmp_path / "customs_trade.parquet"
    rec1 = CustomsTradeRecord(
        category_key="power_and_new_energy",
        category_name="新能源与电力设备",
        product_key="transformer",
        product_name="变压器",
        hs_code="85042100",
        hs_name="额定容量≤650kVA液体介质变压器",
        report_month="2026-05",
        trade_date=date(2026, 5, 31),
        trade_direction="export",
        export_value_usd=8500000.0,
        export_volume=450.0,
        quantity_unit="units",
        target_l1_code="801730.SI",
        target_l1_name="电力设备",
        target_l2_codes="801737.SI",
        target_l2_names="电网设备",
        release_date=date(2026, 6, 20),
    )
    df1 = records_to_customs_trade_frame([rec1])
    assert (
        save_curated_fact(
            df1, parquet_path, primary_keys=["product_key", "hs_code", "report_month"]
        )
        == 1
    )

    # 增量追加次月新记录推进水位
    rec2 = CustomsTradeRecord(
        category_key="power_and_new_energy",
        category_name="新能源与电力设备",
        product_key="transformer",
        product_name="变压器",
        hs_code="85042100",
        hs_name="额定容量≤650kVA液体介质变压器",
        report_month="2026-06",
        trade_date=date(2026, 6, 30),
        trade_direction="export",
        export_value_usd=9200000.0,
        export_volume=470.0,
        quantity_unit="units",
        target_l1_code="801730.SI",
        target_l1_name="电力设备",
        target_l2_codes="801737.SI",
        target_l2_names="电网设备",
        release_date=date(2026, 7, 20),
    )
    df2 = records_to_customs_trade_frame([rec2])
    assert (
        save_curated_fact(
            df2, parquet_path, primary_keys=["product_key", "hs_code", "report_month"]
        )
        == 2
    )

    # 重复写入相同的次月记录，验证严格幂等去重
    assert (
        save_curated_fact(
            df2, parquet_path, primary_keys=["product_key", "hs_code", "report_month"]
        )
        == 2
    )


def test_save_raw_snapshot_and_read_raw_text_gzip(tmp_path: Path) -> None:
    # 1. 文本普通保存 vs Gzip 压缩保存
    plain_file = save_raw_snapshot("test_source", "data.txt", "hello world", base_dir=tmp_path)
    assert plain_file.exists()
    assert plain_file.name == "data.txt"
    assert read_raw_text(plain_file) == "hello world"

    gz_file_1 = save_raw_snapshot(
        "test_source",
        "data.html",
        "<html>compressed content</html>",
        base_dir=tmp_path,
        compress=True,
    )
    assert gz_file_1.exists()
    assert gz_file_1.name == "data.html.gz"
    assert read_raw_text(gz_file_1) == "<html>compressed content</html>"

    # 2. 传入 dict / list 并自动 Gzip 压缩
    json_gz = save_raw_snapshot(
        "test_source", "data.json.gz", {"key": "value", "items": [1, 2, 3]}, base_dir=tmp_path
    )
    assert json_gz.exists()
    assert '"key": "value"' in read_raw_text(json_gz)


def test_semiconductor_collector_dual_mode_snapshots(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw_industry"
    sia_dir = raw_dir / "sia"
    sia_dir.mkdir(parents=True)

    # 1. 创建一个 .html.gz 文件 (2026-05)
    html_202605 = (
        "<html><body>"
        "WASHINGTON—June 5, 2026—The Semiconductor Industry Association (SIA) today announced "
        "global semiconductor sales were $49.0 billion during the month of May 2026. "
        "Regionally, month-to-month sales increased in China (2.1%). "
        "Sales to China were $14.5 billion in May."
        "</body></html>"
    )
    save_raw_snapshot("sia", "may-2026-chip-sales.html.gz", html_202605, base_dir=raw_dir)

    # 2. 创建一个普通 .html 文件 (2026-06)
    html_202606 = (
        "<html><body>"
        "WASHINGTON—July 6, 2026—The Semiconductor Industry Association (SIA) today announced "
        "global semiconductor sales were $52.0 billion for the month of June 2026. "
        "Regionally, month-to-month sales increased in China (3.2%). "
        "Sales to China were $15.2 billion in June."
        "</body></html>"
    )
    save_raw_snapshot("sia", "june-2026-chip-sales.html", html_202606, base_dir=raw_dir)

    collector = SemiconductorCollector(raw_dir=raw_dir)
    enrichments = collector._fetch_sia_news_enrichments()

    assert "2026-05" in enrichments
    assert "2026-06" in enrichments
    assert enrichments["2026-05"]["china_sales_usd"] == 14.5
    assert enrichments["2026-05"]["china_mom_growth"] == 0.021
    assert enrichments["2026-06"]["china_sales_usd"] == 15.2
    assert enrichments["2026-06"]["china_mom_growth"] == 0.032
