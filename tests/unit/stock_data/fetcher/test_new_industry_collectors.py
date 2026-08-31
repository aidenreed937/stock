"""新增垂直产业数据采集器与转换模块单元测试。

覆盖:
- semiconductor_lead / TsmcLeadCollector
- chemical_market / ChemicalsCollector
- solar_price_chain / PvPriceChainCollector
- agriculture_pork / AgriculturePorkCollector
- liquor_wholesale / LiquorWholesaleCollector
- sync_all_industry_metrics 统一管道调度
"""

from datetime import date
from pathlib import Path

from stock_data.fetcher.industry import (
    AGRICULTURE_PORK_SCHEMA,
    CHEMICAL_MARKET_SCHEMA,
    COAL_MARKET_SCHEMA,
    CONSUMER_ELECTRONICS_SCHEMA,
    LIQUOR_WHOLESALE_SCHEMA,
    SEMICONDUCTOR_LEAD_SCHEMA,
    SOLAR_PRICE_CHAIN_SCHEMA,
    AgriculturePorkCollector,
    AgriculturePorkRecord,
    ChemicalMarketRecord,
    ChemicalsCollector,
    CoalMarketCollector,
    CoalMarketRecord,
    ConsumerElectronicsCollector,
    ConsumerElectronicsRecord,
    LiquorWholesaleCollector,
    LiquorWholesaleRecord,
    PvPriceChainCollector,
    SemiconductorLeadRecord,
    SolarPriceChainRecord,
    TsmcLeadCollector,
    empty_agriculture_pork,
    empty_chemical_market,
    empty_coal_market,
    empty_consumer_electronics,
    empty_liquor_wholesale,
    empty_semiconductor_lead,
    empty_solar_price_chain,
    records_to_agriculture_pork_frame,
    records_to_chemical_market_frame,
    records_to_coal_market_frame,
    records_to_consumer_electronics_frame,
    records_to_liquor_wholesale_frame,
    records_to_semiconductor_lead_frame,
    records_to_solar_price_chain_frame,
    sync_all_industry_metrics,
)


def test_semiconductor_lead_frame_conversion() -> None:
    assert empty_semiconductor_lead().schema == SEMICONDUCTOR_LEAD_SCHEMA

    records = [
        SemiconductorLeadRecord(
            report_month="2026-05",
            trade_date=date(2026, 5, 31),
            tsmc_revenue_ntd_million=372000.0,
            tsmc_revenue_usd_million=11809.5,
            tsmc_revenue_yoy=0.169,
            tsmc_revenue_mom=0.011,
            dram_dxi_index=48000.0,
            dram_spot_price_usd=4.95,
        ),
        SemiconductorLeadRecord(
            report_month="2026-06",
            trade_date=date(2026, 6, 30),
            tsmc_revenue_ntd_million=360000.0,
            tsmc_revenue_usd_million=11428.6,
            tsmc_revenue_yoy=0.205,
            tsmc_revenue_mom=-0.032,
            dram_dxi_index=49500.0,
            dram_spot_price_usd=4.86,
        ),
    ]

    df = records_to_semiconductor_lead_frame(records)
    assert not df.is_empty()
    assert df.height == 2
    assert "tsmc_revenue_ntd_million" in df.columns
    assert "tsmc_revenue_3mma_usd" in df.columns
    assert df["tsmc_revenue_ntd_million"][0] == 372000.0
    assert df["unit"][0] == "million_ntd/usd"


def test_tsmc_lead_collector_from_raw_csv(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw_industry"
    semi_dir = raw_dir / "semiconductor"
    semi_dir.mkdir(parents=True)
    raw_csv = semi_dir / "tsmc_monthly.csv"
    raw_csv.write_text(
        "report_month,trade_date,tsmc_revenue_ntd_million,tsmc_revenue_usd_million,tsmc_revenue_yoy,tsmc_revenue_mom,dram_dxi_index,dram_spot_price_usd,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-06,2026-06-30,360000.0,11428.6,0.205,-0.032,49500.0,4.86,million_ntd/usd,TSMC,,2026-07-10,actual,2026-07-10T10:00:00Z\n",
        encoding="utf-8",
    )

    collector = TsmcLeadCollector(raw_dir=raw_dir)
    records = collector.collect()
    assert len(records) == 1
    assert records[0].report_month == "2026-06"
    assert records[0].tsmc_revenue_ntd_million == 360000.0
    assert records[0].release_date == date(2026, 7, 10)


def test_chemical_market_frame_conversion() -> None:
    assert empty_chemical_market().schema == CHEMICAL_MARKET_SCHEMA

    records = [
        ChemicalMarketRecord(
            report_month="2026-05",
            trade_date=date(2026, 5, 31),
            mdi_operating_rate=73.5,
            tio2_operating_rate=69.0,
            refrigerant_r32_operating_rate=62.0,
            mdi_gross_spread_cny=9600.0,
            tio2_spread_cny=3950.0,
            refrigerant_r32_price_cny=38500.0,
            chemical_inventory_days=26.5,
        ),
        ChemicalMarketRecord(
            report_month="2026-06",
            trade_date=date(2026, 6, 30),
            mdi_operating_rate=75.0,
            tio2_operating_rate=70.5,
            refrigerant_r32_operating_rate=64.0,
            mdi_gross_spread_cny=9800.0,
            tio2_spread_cny=4000.0,
            refrigerant_r32_price_cny=39000.0,
            chemical_inventory_days=25.8,
        ),
    ]

    df = records_to_chemical_market_frame(records)
    assert not df.is_empty()
    assert df.height == 2
    assert "mdi_operating_rate" in df.columns
    assert "refrigerant_r32_price_cny" in df.columns
    assert df["mdi_operating_rate"][1] == 75.0
    assert df["unit"][0] == "percent/cny_per_ton"


def test_chemicals_collector_from_raw_csv(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw_industry"
    chem_dir = raw_dir / "chemicals"
    chem_dir.mkdir(parents=True)
    raw_csv = chem_dir / "chemical_operating_spreads.csv"
    raw_csv.write_text(
        "report_month,trade_date,mdi_operating_rate,tio2_operating_rate,refrigerant_r32_operating_rate,mdi_gross_spread_cny,tio2_spread_cny,refrigerant_r32_price_cny,chemical_inventory_days,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-06,2026-06-30,75.0,70.5,64.0,9800.0,4000.0,39000.0,25.8,percent/cny_per_ton,Baichuan,,2026-07-05,actual,2026-07-05T10:00:00Z\n",
        encoding="utf-8",
    )

    collector = ChemicalsCollector(raw_dir=raw_dir)
    records = collector.collect()
    assert len(records) == 1
    assert records[0].report_month == "2026-06"
    assert records[0].mdi_operating_rate == 75.0
    assert records[0].refrigerant_r32_price_cny == 39000.0


def test_solar_price_chain_frame_conversion() -> None:
    assert empty_solar_price_chain().schema == SOLAR_PRICE_CHAIN_SCHEMA

    records = [
        SolarPriceChainRecord(
            report_date="2026-06-17",
            trade_date=date(2026, 6, 17),
            polysilicon_price_cny_kg=51.0,
            wafer_price_cny_piece=1.41,
            cell_price_cny_watt=0.354,
            module_price_cny_watt=0.81,
            price_cycle_stage="bottom_rebound",
        ),
        SolarPriceChainRecord(
            report_date="2026-06-24",
            trade_date=date(2026, 6, 24),
            polysilicon_price_cny_kg=51.5,
            wafer_price_cny_piece=1.42,
            cell_price_cny_watt=0.356,
            module_price_cny_watt=0.815,
            price_cycle_stage="bottom_rebound",
        ),
    ]

    df = records_to_solar_price_chain_frame(records)
    assert not df.is_empty()
    assert df.height == 2
    assert "polysilicon_price_cny_kg" in df.columns
    assert "module_price_cny_watt" in df.columns
    assert df["module_price_cny_watt"][1] == 0.815


def test_pv_price_collector_from_raw_csv(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw_industry"
    energy_dir = raw_dir / "energy"
    energy_dir.mkdir(parents=True)
    raw_csv = energy_dir / "pv_price_chain_weekly.csv"
    raw_csv.write_text(
        "report_date,trade_date,polysilicon_price_cny_kg,wafer_price_cny_piece,cell_price_cny_watt,module_price_cny_watt,module_price_yoy,module_price_mom,price_cycle_stage,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-06-24,2026-06-24,51.5,1.42,0.356,0.815,0.05,0.006,bottom_rebound,cny_per_unit,PVInfoLink,,2026-06-24,actual,2026-06-24T10:00:00Z\n",
        encoding="utf-8",
    )

    from unittest.mock import patch

    collector = PvPriceChainCollector(raw_dir=raw_dir)
    with patch.object(collector.crawler, "fetch_live_spot_prices", return_value=None):
        records = collector.collect()
        assert len(records) == 1
        assert records[0].report_date == "2026-06-24"
        assert records[0].polysilicon_price_cny_kg == 51.5
        assert records[0].module_price_cny_watt == 0.815


def test_infolink_spot_price_parser() -> None:
    from stock_data.fetcher.industry.power.pv_price_collector import (
        parse_infolink_spot_price_html,
    )

    sample_html = """
    <div>
        <p>*InfoLink 公示价格时间区间主要为前周周四至本周周三(8.20-8.26)，截至本周三仍在执行和新签订的合约价格范围。</p>
        <table>
            <caption><strong class="h2">多晶硅</strong><small>（kg）</small></caption>
            <tr><th>项目</th><th>高点</th><th>低点</th><th>均价</th></tr>
            <tr><td>多晶硅 致密料 (RMB)</td><td>43.0</td><td>38.0</td><td>40.0</td></tr>
        </table>
        <table>
            <caption><strong class="h2">N型硅片</strong><small> (pc)</small></caption>
            <tr><th>项目</th><th>高点</th><th>低点</th><th>均价</th></tr>
            <tr><td>单晶N型硅片 - 182-183.75mm / 130µm (RMB)</td><td>1.120</td><td>1.100</td><td>1.100</td></tr>
        </table>
        <table>
            <caption><strong class="h2">N型电池片</strong><small> (W)</small></caption>
            <tr><th>项目</th><th>高点</th><th>低点</th><th>均价</th></tr>
            <tr><td>TOPCon电池片 - 182-183.75mm / 25.4%+ (RMB)</td><td>0.340</td><td>0.320</td><td>0.330</td></tr>
        </table>
        <table>
            <caption><strong class="h2">双面双玻N型组件</strong><small>（W）</small></caption>
            <tr><th>项目</th><th>高点</th><th>低点</th><th>均价</th></tr>
            <tr><td>182*182-210mm/210mm 单晶TOPCon组件 (RMB)</td><td>0.780</td><td>0.650</td><td>0.723</td></tr>
        </table>
    </div>
    """
    res = parse_infolink_spot_price_html(sample_html)
    assert res is not None
    assert res["trade_date"] == date(date.today().year, 8, 26)
    assert res["polysilicon_price_cny_kg"] == 40.0
    assert res["wafer_price_cny_piece"] == 1.100
    assert res["cell_price_cny_watt"] == 0.330
    assert res["module_price_cny_watt"] == 0.723


def test_agriculture_pork_frame_conversion() -> None:
    assert empty_agriculture_pork().schema == AGRICULTURE_PORK_SCHEMA

    records = [
        AgriculturePorkRecord(
            report_month="2026-05",
            trade_date=date(2026, 5, 31),
            sow_stock_million_heads=40.6,
            pig_price_cny_per_kg=18.2,
            hog_to_grain_ratio=6.5,
            pig_farming_profit_cny_head=368.0,
        ),
        AgriculturePorkRecord(
            report_month="2026-06",
            trade_date=date(2026, 6, 30),
            sow_stock_million_heads=40.65,
            pig_price_cny_per_kg=18.5,
            hog_to_grain_ratio=6.6,
            pig_farming_profit_cny_head=402.5,
        ),
    ]

    df = records_to_agriculture_pork_frame(records)
    assert not df.is_empty()
    assert df.height == 2
    assert "sow_stock_million_heads" in df.columns
    assert "hog_to_grain_ratio" in df.columns
    assert df["pig_price_cny_per_kg"][1] == 18.5
    assert df["unit"][0] == "million_heads/cny_per_kg"


def test_agriculture_pork_collector_from_raw_csv(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw_industry"
    agri_dir = raw_dir / "agriculture"
    agri_dir.mkdir(parents=True)
    raw_csv = agri_dir / "pork_capacity_monthly.csv"
    raw_csv.write_text(
        "report_month,trade_date,sow_stock_million_heads,sow_stock_yoy,sow_stock_mom,pig_price_cny_per_kg,pig_price_yoy,hog_to_grain_ratio,pig_farming_profit_cny_head,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-06,2026-06-30,40.65,0.018,0.001,18.5,0.12,6.6,402.5,million_heads/cny_per_kg,MARA,,2026-07-18,actual,2026-07-18T10:00:00Z\n",
        encoding="utf-8",
    )

    collector = AgriculturePorkCollector(raw_dir=raw_dir)
    records = collector.collect()
    assert len(records) == 1
    assert records[0].report_month == "2026-06"
    assert records[0].sow_stock_million_heads == 40.65
    assert records[0].hog_to_grain_ratio == 6.6


def test_liquor_wholesale_frame_conversion() -> None:
    assert empty_liquor_wholesale().schema == LIQUOR_WHOLESALE_SCHEMA

    records = [
        LiquorWholesaleRecord(
            report_date="2026-06-19",
            trade_date=date(2026, 6, 19),
            moutai_loose_price_cny=2330.0,
            moutai_boxed_price_cny=2540.0,
            wuliangye_puwu_price_cny=963.0,
            guojiao1573_price_cny=892.0,
        ),
        LiquorWholesaleRecord(
            report_date="2026-06-26",
            trade_date=date(2026, 6, 26),
            moutai_loose_price_cny=2335.0,
            moutai_boxed_price_cny=2545.0,
            wuliangye_puwu_price_cny=963.0,
            guojiao1573_price_cny=892.0,
        ),
    ]

    df = records_to_liquor_wholesale_frame(records)
    assert not df.is_empty()
    assert df.height == 2
    assert "moutai_loose_price_cny" in df.columns
    assert "wuliangye_puwu_price_cny" in df.columns
    assert df["moutai_loose_price_cny"][1] == 2335.0
    assert df["unit"][0] == "cny_per_bottle"


def test_liquor_wholesale_collector_from_raw_csv(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw_industry"
    consumer_dir = raw_dir / "consumer"
    consumer_dir.mkdir(parents=True)
    raw_csv = consumer_dir / "liquor_wholesale_weekly.csv"
    raw_csv.write_text(
        "report_date,trade_date,moutai_loose_price_cny,moutai_boxed_price_cny,wuliangye_puwu_price_cny,guojiao1573_price_cny,moutai_loose_price_yoy,moutai_loose_price_mom,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-06-26,2026-06-26,2335.0,2545.0,963.0,892.0,0.04,0.002,cny_per_bottle,TodayLiquorPrice,,2026-06-26,actual,2026-06-26T10:00:00Z\n",
        encoding="utf-8",
    )

    collector = LiquorWholesaleCollector(raw_dir=raw_dir)
    records = collector.collect()
    assert len(records) == 1
    assert records[0].report_date == "2026-06-26"
    assert records[0].moutai_loose_price_cny == 2335.0
    assert records[0].wuliangye_puwu_price_cny == 963.0


def test_consumer_electronics_frame_conversion() -> None:
    assert empty_consumer_electronics().schema == CONSUMER_ELECTRONICS_SCHEMA

    records = [
        ConsumerElectronicsRecord(
            report_quarter="2026-Q1",
            trade_date=date(2026, 3, 31),
            global_smartphone_shipments_million=325.0,
            china_smartphone_shipments_million=78.5,
            global_pc_shipments_million=73.5,
            ai_phone_penetration_rate=0.27,
            ai_pc_penetration_rate=0.345,
            apple_shipments_million=56.0,
            transsion_shipments_million=36.0,
        ),
        ConsumerElectronicsRecord(
            report_quarter="2026-Q2",
            trade_date=date(2026, 6, 30),
            global_smartphone_shipments_million=330.0,
            china_smartphone_shipments_million=80.0,
            global_pc_shipments_million=75.0,
            ai_phone_penetration_rate=0.29,
            ai_pc_penetration_rate=0.37,
            apple_shipments_million=58.0,
            transsion_shipments_million=37.0,
        ),
    ]

    df = records_to_consumer_electronics_frame(records)
    assert not df.is_empty()
    assert df.height == 2
    assert "global_smartphone_shipments_million" in df.columns
    assert "ai_phone_penetration_rate" in df.columns
    assert df["global_smartphone_shipments_million"][1] == 330.0
    assert df["ai_pc_penetration_rate"][1] == 0.37


def test_consumer_electronics_collector_from_raw_csv(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw_industry"
    elec_dir = raw_dir / "electronics"
    elec_dir.mkdir(parents=True)
    raw_csv = elec_dir / "electronics_shipments_quarterly.csv"
    raw_csv.write_text(
        "report_quarter,trade_date,global_smartphone_shipments_million,china_smartphone_shipments_million,global_pc_shipments_million,ai_phone_penetration_rate,ai_pc_penetration_rate,smartphone_yoy_growth,pc_yoy_growth,apple_shipments_million,transsion_shipments_million,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-Q2,2026-06-30,330.0,80.0,75.0,0.29,0.37,0.045,0.062,58.0,37.0,million_units/percent,IDC,,2026-07-25,actual,2026-07-25T10:00:00Z\n",
        encoding="utf-8",
    )

    collector = ConsumerElectronicsCollector(raw_dir=raw_dir)
    records = collector.collect()
    assert len(records) == 1
    assert records[0].report_quarter == "2026-Q2"
    assert records[0].global_smartphone_shipments_million == 330.0
    assert records[0].ai_phone_penetration_rate == 0.29


def test_coal_market_frame_conversion() -> None:
    assert empty_coal_market().schema == COAL_MARKET_SCHEMA

    records = [
        CoalMarketRecord(
            report_date="2026-06-19",
            trade_date=date(2026, 6, 19),
            q5500_fob_price_cny=838.0,
            coking_coal_price_cny=1660.0,
            power_plant_inventory_million_ton=174.5,
            power_plant_daily_burn_ten_thousand_ton=785.0,
            power_plant_available_days=22.2,
            qinhuangdao_inventory_million_ton=6.15,
        ),
        CoalMarketRecord(
            report_date="2026-06-26",
            trade_date=date(2026, 6, 26),
            q5500_fob_price_cny=842.0,
            coking_coal_price_cny=1665.0,
            power_plant_inventory_million_ton=175.0,
            power_plant_daily_burn_ten_thousand_ton=790.0,
            power_plant_available_days=22.2,
            qinhuangdao_inventory_million_ton=6.20,
        ),
    ]

    df = records_to_coal_market_frame(records)
    assert not df.is_empty()
    assert df.height == 2
    assert "q5500_fob_price_cny" in df.columns
    assert "power_plant_available_days" in df.columns
    assert df["q5500_fob_price_cny"][1] == 842.0
    assert df["power_plant_available_days"][1] == 22.2


def test_coal_market_collector_from_raw_csv(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw_industry"
    coal_dir = raw_dir / "coal"
    coal_dir.mkdir(parents=True)
    raw_csv = coal_dir / "coal_market_weekly.csv"
    raw_csv.write_text(
        "report_date,trade_date,q5500_fob_price_cny,coking_coal_price_cny,power_plant_inventory_million_ton,power_plant_daily_burn_ten_thousand_ton,power_plant_available_days,qinhuangdao_inventory_million_ton,q5500_price_yoy,q5500_price_mom,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-06-26,2026-06-26,842.0,1665.0,175.0,790.0,22.2,6.20,-0.02,0.005,cny_per_ton/million_tons/days,CCTD,,2026-06-26,actual,2026-06-26T10:00:00Z\n",
        encoding="utf-8",
    )

    collector = CoalMarketCollector(raw_dir=raw_dir)
    records = collector.collect()
    assert len(records) == 1
    assert records[0].report_date == "2026-06-26"
    assert records[0].q5500_fob_price_cny == 842.0
    assert records[0].power_plant_available_days == 22.2


def test_sync_all_industry_metrics_with_new_metrics(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw_industry"
    curated_dir = tmp_path / "curated_industry"

    # 1. 准备 mock RAW 数据快照
    (raw_dir / "semiconductor").mkdir(parents=True)
    (raw_dir / "semiconductor" / "tsmc_monthly.csv").write_text(
        "report_month,trade_date,tsmc_revenue_ntd_million,tsmc_revenue_usd_million,tsmc_revenue_yoy,tsmc_revenue_mom,dram_dxi_index,dram_spot_price_usd,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-06,2026-06-30,442680.0,14053.33,0.35,0.05,45000,3.5,million_ntd/usd,TWSE,,2026-07-10,actual,2026-07-10T00:00:00Z\n",
        encoding="utf-8",
    )

    (raw_dir / "chemicals").mkdir(parents=True)
    (raw_dir / "chemicals" / "chemical_operating_spreads.csv").write_text(
        "report_month,trade_date,mdi_operating_rate,tio2_operating_rate,refrigerant_r32_operating_rate,mdi_gross_spread_cny,tio2_spread_cny,refrigerant_r32_price_cny,chemical_inventory_days,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-06,2026-06-30,75.0,70.0,65.0,9600,3950,38500,25.0,percent/cny_per_ton,Baichuan,,2026-07-05,actual,2026-07-05T00:00:00Z\n",
        encoding="utf-8",
    )

    (raw_dir / "energy").mkdir(parents=True)
    (raw_dir / "energy" / "pv_price_chain_weekly.csv").write_text(
        "report_date,trade_date,polysilicon_price_cny_kg,wafer_price_cny_piece,cell_price_cny_watt,module_price_cny_watt,module_price_yoy,module_price_mom,price_cycle_stage,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-08-26,2026-08-26,40.0,1.10,0.33,0.723,0.02,0.001,bottom_rebound,cny_per_unit,InfoLink,,2026-08-26,actual,2026-08-26T00:00:00Z\n",
        encoding="utf-8",
    )
    (raw_dir / "energy" / "coal_market_weekly.csv").write_text(
        "report_date,trade_date,q5500_fob_price_cny,coking_coal_price_cny,power_plant_inventory_million_ton,power_plant_daily_burn_ten_thousand_ton,power_plant_available_days,qinhuangdao_inventory_million_ton,q5500_price_yoy,q5500_price_mom,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-08-28,2026-08-28,840.0,1660.0,180.0,770.0,23.4,6.10,-0.01,0.0,cny_per_ton/million_tons/days,CCTD,,2026-08-28,actual,2026-08-28T00:00:00Z\n",
        encoding="utf-8",
    )

    (raw_dir / "agriculture").mkdir(parents=True)
    (raw_dir / "agriculture" / "pork_capacity_monthly.csv").write_text(
        "report_month,trade_date,sow_stock_million_heads,sow_stock_yoy,sow_stock_mom,pig_price_cny_per_kg,pig_price_yoy,hog_to_grain_ratio,pig_farming_profit_cny_head,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-06,2026-06-30,40.5,0.01,0.001,18.2,0.05,7.3,380.0,million_heads/cny_per_kg,MARA,,2026-07-18,actual,2026-07-18T00:00:00Z\n",
        encoding="utf-8",
    )

    (raw_dir / "consumer").mkdir(parents=True)
    (raw_dir / "consumer" / "liquor_wholesale_weekly.csv").write_text(
        "report_date,trade_date,moutai_loose_price_cny,moutai_boxed_price_cny,wuliangye_puwu_price_cny,guojiao1573_price_cny,moutai_loose_price_yoy,moutai_loose_price_mom,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-08-28,2026-08-28,2310.0,2520.0,945.0,875.0,0.03,0.005,cny_per_bottle,TodayLiquorPrice,,2026-08-28,actual,2026-08-28T00:00:00Z\n",
        encoding="utf-8",
    )

    (raw_dir / "electronics").mkdir(parents=True)
    (raw_dir / "electronics" / "electronics_shipments_quarterly.csv").write_text(
        "report_quarter,trade_date,global_smartphone_shipments_million,china_smartphone_shipments_million,global_pc_shipments_million,ai_phone_penetration_rate,ai_pc_penetration_rate,smartphone_yoy_growth,pc_yoy_growth,apple_shipments_million,transsion_shipments_million,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-Q2,2026-06-30,330.0,79.5,73.0,0.30,0.35,0.05,0.08,55.0,37.0,million_units/percent,IDC,,2026-07-25,actual,2026-07-25T00:00:00Z\n",
        encoding="utf-8",
    )

    new_metrics = [
        "semiconductor_lead",
        "chemical_market",
        "solar_price_chain",
        "agriculture_pork",
        "liquor_wholesale",
        "consumer_electronics",
        "coal_market",
    ]

    res = sync_all_industry_metrics(
        raw_dir=raw_dir,
        curated_dir=curated_dir,
        metrics=new_metrics,
    )

    for metric in new_metrics:
        assert metric in res
        assert res[metric] > 0
        assert (curated_dir / f"{metric}.parquet").exists()
