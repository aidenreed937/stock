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
    AgriculturePorkRecord,
    ChemicalMarketRecord,
    CoalMarketRecord,
    ConsumerElectronicsRecord,
    LiquorWholesaleRecord,
    SemiconductorLeadRecord,
    SolarPriceChainRecord,
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


def test_sync_all_industry_metrics_with_new_metrics(tmp_path: Path, monkeypatch) -> None:
    raw_dir = tmp_path / "raw_industry"
    curated_dir = tmp_path / "curated_industry"

    # mock 全部在线采集源 (纯在线模式, 以最新采集为准)
    from stock_data.fetcher.industry.agriculture.crawler import MaraPorkCrawler
    from stock_data.fetcher.industry.chemicals.crawler import ChemicalsCrawler
    from stock_data.fetcher.industry.coal.crawler import CoalMarketCrawler
    from stock_data.fetcher.industry.consumer.collector import LiquorPriceCrawler
    from stock_data.fetcher.industry.electronics.crawler import ConsumerElectronicsCrawler
    from stock_data.fetcher.industry.power.pv_price_collector import InfoLinkPvPriceCrawler
    from stock_data.fetcher.industry.semiconductor.tsmc_collector import TsmcMonthlyRevenueCrawler

    monkeypatch.setattr(
        TsmcMonthlyRevenueCrawler,
        "fetch_latest_revenue",
        lambda self, *args, **kwargs: {
            "report_month": "2026-06",
            "release_date": "2026-07-10",
            "tsmc_revenue_ntd_million": 442680.0,
            "tsmc_revenue_usd_million": 14053.33,
            "tsmc_revenue_yoy": 0.35,
            "tsmc_revenue_mom": 0.05,
            "source": "TWSE/TSMC",
            "source_url": "",
            "collected_at": "2026-07-10T00:00:00Z",
        },
    )
    monkeypatch.setattr(
        ChemicalsCrawler,
        "fetch_latest_prices",
        lambda self, *args, **kwargs: {
            "mdi_price_cny": 9600.0,
            "tio2_price_cny": 3950.0,
            "source": "100ppi",
            "source_url": "",
            "release_date": "2026-07-05",
            "data_status": "actual",
            "collected_at": "2026-07-05T00:00:00Z",
        },
    )
    monkeypatch.setattr(
        InfoLinkPvPriceCrawler,
        "fetch_live_spot_prices",
        lambda self, *args, **kwargs: {
            "report_date": "2026-08-26",
            "trade_date": date(2026, 8, 26),
            "polysilicon_price_cny_kg": 40.0,
            "wafer_price_cny_piece": 1.1,
            "cell_price_cny_watt": 0.33,
            "module_price_cny_watt": 0.723,
            "price_cycle_stage": "bottom_rebound",
            "source": "InfoLink Consulting",
            "source_url": "",
            "collected_at": "2026-08-26T00:00:00Z",
        },
    )
    monkeypatch.setattr(
        MaraPorkCrawler,
        "fetch_latest_month",
        lambda self, *args, **kwargs: {
            "report_month": "2026-06",
            "sow_stock_million_heads": 40.5,
            "pig_price_cny_per_kg": 18.2,
            "hog_to_grain_ratio": 7.3,
            "pig_farming_profit_cny_head": 380.0,
            "source": "MARA",
            "source_url": "",
            "release_date": "2026-07-18",
            "data_status": "actual",
            "collected_at": "2026-07-18T00:00:00Z",
        },
    )
    monkeypatch.setattr(
        LiquorPriceCrawler,
        "fetch_latest_liquor_price",
        lambda self, *args, **kwargs: {
            "report_date": "2026-08-28",
            "trade_date": date(2026, 8, 28),
            "moutai_loose_price_cny": 2310.0,
            "moutai_boxed_price_cny": 2520.0,
            "wuliangye_puwu_price_cny": 945.0,
            "guojiao1573_price_cny": 875.0,
            "source": "TodayLiquorPrice",
            "source_url": "",
            "release_date": date(2026, 8, 28),
            "collected_at": "2026-08-28T00:00:00Z",
        },
    )
    monkeypatch.setattr(
        ConsumerElectronicsCrawler,
        "fetch_latest_quarter",
        lambda self, *args, **kwargs: {
            "report_quarter": "2026-Q2",
            "global_smartphone_shipments_million": 330.0,
            "china_smartphone_shipments_million": 79.5,
            "global_pc_shipments_million": 73.0,
            "smartphone_yoy_growth": 0.05,
            "pc_yoy_growth": 0.08,
            "apple_shipments_million": 55.0,
            "transsion_shipments_million": 37.0,
            "source": "IDC",
            "source_url": "",
            "release_date": "2026-07-25",
            "data_status": "actual",
            "collected_at": "2026-07-25T00:00:00Z",
        },
    )
    monkeypatch.setattr(
        CoalMarketCrawler,
        "fetch_latest_q5500",
        lambda self, *args, **kwargs: {
            "report_date": "2026-08-28",
            "q5500_fob_price_cny": 840.0,
            "source": "CCTD",
            "source_url": "",
            "release_date": "2026-08-28",
            "data_status": "actual",
            "collected_at": "2026-08-28T00:00:00Z",
        },
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

    # 1. 默认增量模式：未到发布窗口时被 DailySyncEngine 智能跳过
    res_skipped = sync_all_industry_metrics(
        raw_dir=raw_dir,
        curated_dir=curated_dir,
        metrics=new_metrics,
        force=False,
    )
    assert isinstance(res_skipped, dict)

    # 2. 强制同步模式：执行全部 Task 并落盘
    res = sync_all_industry_metrics(
        raw_dir=raw_dir,
        curated_dir=curated_dir,
        metrics=new_metrics,
        force=True,
    )

    for metric in new_metrics:
        assert metric in res
        assert res[metric] > 0
        assert (curated_dir / f"{metric}.parquet").exists()


# ---------- 新增在线采集爬虫解析器测试 (纯函数, 无需网络) ----------

CCTD_HTML_FIXTURE = (
    '<div class="data_top_title">CCTD综合交易5500 平仓价</div>'
    '<div class="fl bqz">本期值<br /><b><em style="color: #d70e18;">731</em></b></div>'
    '<div class="fl bqz">较上期<br /><span><em style="color: #d70e18;">1</em></span></div>'
    "<div>日期：2026-08-28 单位：元/吨</div>"
)

MARA_TABLE_HTML_FIXTURE = """
<html><body><div class="detail_box2">
<table class="data_table">
<tr><td>指标</td><td>数值</td><td>环比</td></tr>
<tr><td>2026年7月末能繁母猪存栏（万头）</td><td>4060</td><td>0.1%</td></tr>
<tr><td>2026年7月份全国生猪出场价格（元/公斤）</td><td>18.50</td><td>0.5%</td></tr>
<tr><td>2026年7月份猪粮比价</td><td>7.40</td><td>0.3%</td></tr>
<tr><td>2026年7月份散养生猪每头净利润（元）</td><td>420</td><td>2%</td></tr>
</table></div></body></html>
"""

MDI_HTML_FIXTURE = "[ MDI ] 8月31日，聚合MDI参考价为16866.67，与8月1日(17866.67)相比，下降了5.6% 2026-08-31 16:38:13"
TIO2_HTML_FIXTURE = "[ 钛白粉 ] 8月31日，钛白粉参考价为14060.00，与8月1日(15460.00)相比，下降了9.06% 2026-08-31 16:38:13"

IDC_SMARTPHONE_HTML_FIXTURE = """
<html><body>
<p>*Worldwide smartphone shipments increased 2.6% year-over-year (YoY) to 322.7 million units
in the third quarter of 2025 (3Q25), according to preliminary data...</p>
<table>
<tr><th>Company</th><th>3Q25 Shipments</th><th>3Q25 Market Share</th><th>3Q24 Shipments</th><th>3Q24 Market Share</th><th>YoY Change</th></tr>
<tr><td>1. Samsung</td><td>60.5</td><td>18.7%</td><td>58.1</td><td>18.5%</td><td>4.1%</td></tr>
<tr><td>2. Apple</td><td>58.6</td><td>18.2%</td><td>56.9</td><td>18.1%</td><td>2.9%</td></tr>
<tr><td>5. Transsion</td><td>29.2</td><td>9.0%</td><td>25.7</td><td>8.2%</td><td>13.6%</td></tr>
</table>
</body></html>
"""

IDC_PC_HTML_FIXTURE = (
    "<p>PC shipments during the third quarter of 2025 grew 9.4% from the prior year, "
    "with global volumes reaching 75.8 million units</p>"
)

IDC_CHINA_HTML_FIXTURE = (
    "<p>China's smartphone market shipped 68.4 million units in 3Q25, "
    "with the year-on-year (YoY) decline easing to 0.6%</p>"
)


def test_parse_cctd_q5500() -> None:
    from stock_data.fetcher.industry.coal.crawler import parse_cctd_q5500

    res = parse_cctd_q5500(CCTD_HTML_FIXTURE)
    assert res is not None
    assert res["report_date"] == "2026-08-28"
    assert res["q5500_fob_price_cny"] == 731.0


def test_parse_mara_monthly_table() -> None:
    from stock_data.fetcher.industry.agriculture.crawler import parse_mara_monthly_table

    res = parse_mara_monthly_table(MARA_TABLE_HTML_FIXTURE)
    assert res is not None
    assert res["report_month"] == "2026-07"
    assert res["sow_stock_million_heads"] == 40.6  # 4060万头 -> 40.6百万头
    assert res["pig_price_cny_per_kg"] == 18.5
    assert res["hog_to_grain_ratio"] == 7.4
    assert res["pig_farming_profit_cny_head"] == 420.0


def test_parse_100ppi_reference_prices() -> None:
    from stock_data.fetcher.industry.chemicals.crawler import (
        parse_mdi_reference_price,
        parse_tio2_reference_price,
    )

    assert parse_mdi_reference_price(MDI_HTML_FIXTURE) == 16866.67
    assert parse_tio2_reference_price(TIO2_HTML_FIXTURE) == 14060.0


def test_parse_idc_smartphone_pr() -> None:
    from stock_data.fetcher.industry.electronics.crawler import parse_idc_smartphone_pr

    res = parse_idc_smartphone_pr(IDC_SMARTPHONE_HTML_FIXTURE)
    assert res is not None
    assert res["report_quarter"] == "2025-Q3"
    assert res["global_smartphone_shipments_million"] == 322.7
    assert res["smartphone_yoy_growth"] == 0.026
    assert res["apple_shipments_million"] == 58.6
    assert res["transsion_shipments_million"] == 29.2


def test_parse_idc_pc_pr() -> None:
    from stock_data.fetcher.industry.electronics.crawler import parse_idc_pc_pr

    res = parse_idc_pc_pr(IDC_PC_HTML_FIXTURE)
    assert res is not None
    assert res["report_quarter"] == "2025-Q3"
    assert res["global_pc_shipments_million"] == 75.8
    assert res["pc_yoy_growth"] == 0.094


def test_parse_idc_china_pr() -> None:
    from stock_data.fetcher.industry.electronics.crawler import parse_idc_china_pr

    res = parse_idc_china_pr(IDC_CHINA_HTML_FIXTURE)
    assert res is not None
    assert res["report_quarter"] == "2025-Q3"
    assert res["china_smartphone_shipments_million"] == 68.4
    assert res["smartphone_yoy_growth"] == -0.006


def test_html_parser_protocol_conformance_and_injection(tmp_path: Path) -> None:
    """验证所有解析器策略类均符合 HtmlParserProtocol 协议，且各 Crawler 均支持解析器注入。"""
    from stock_data.fetcher.industry import (
        CctdCoalPriceHtmlParser,
        Chemicals100PpiHtmlParser,
        HtmlParserProtocol,
        IdcElectronicsHtmlParser,
        InfoLinkPvPriceCrawler,
        InfoLinkSpotPriceHtmlParser,
        MaraPorkHtmlParser,
    )
    from stock_data.fetcher.industry.agriculture.crawler import MaraPorkCrawler
    from stock_data.fetcher.industry.chemicals.crawler import ChemicalsCrawler
    from stock_data.fetcher.industry.coal.crawler import CoalMarketCrawler
    from stock_data.fetcher.industry.electronics.crawler import ConsumerElectronicsCrawler

    # 1. 协议实现检查
    p1 = MaraPorkHtmlParser()
    p2 = InfoLinkSpotPriceHtmlParser()
    p3 = CctdCoalPriceHtmlParser()
    p4 = Chemicals100PpiHtmlParser()
    p5 = IdcElectronicsHtmlParser()

    assert isinstance(p1, HtmlParserProtocol)
    assert isinstance(p2, HtmlParserProtocol)
    assert isinstance(p3, HtmlParserProtocol)
    assert isinstance(p4, HtmlParserProtocol)
    assert isinstance(p5, HtmlParserProtocol)

    # 2. 注入自定义测试解析器
    class MockCustomParser:
        def parse(self, html_text: str, **kwargs) -> dict:
            return {"mock_key": "injected_value"}

    mock_parser = MockCustomParser()
    crawler_mara = MaraPorkCrawler(raw_dir=tmp_path, parser=mock_parser)
    assert crawler_mara.parser is mock_parser

    crawler_infolink = InfoLinkPvPriceCrawler(raw_dir=tmp_path, parser=mock_parser)
    assert crawler_infolink.parser is mock_parser

    crawler_coal = CoalMarketCrawler(raw_dir=tmp_path, parser=mock_parser)
    assert crawler_coal.parser is mock_parser

    crawler_chem = ChemicalsCrawler(raw_dir=tmp_path, parser=p4)
    assert crawler_chem.parser is p4

    crawler_elec = ConsumerElectronicsCrawler(raw_dir=tmp_path, parser=p5)
    assert crawler_elec.parser is p5


def test_comtrade_incremental_period_calculation() -> None:
    """验证 ComtradeCollector._calculate_periods 在增量与默认模式下的计算。"""
    from stock_data.fetcher.industry.customs.collector import _calculate_periods

    # 1. 增量区间模式
    p1 = _calculate_periods(start_month="2026-03", end_month="2026-06")
    assert p1 == ["202603", "202604", "202605", "202606"]

    # 2. 跨年增量区间模式
    p2 = _calculate_periods(start_month="202511", end_month="202602")
    assert p2 == ["202511", "202512", "202601", "202602"]

    # 3. 默认 lookback 模式
    p3 = _calculate_periods(lookback_months=3)
    assert len(p3) == 3


def test_crawler_cache_hit_without_network(tmp_path: Path) -> None:
    """验证爬虫类源在本地 RAW 快照已存在时命中缓存，不发起任何网络请求。"""
    from stock_data.fetcher.industry.coal.crawler import CoalMarketCrawler
    from stock_data.fetcher.industry.power.pv_price_collector import InfoLinkPvPriceCrawler

    # 1. CoalMarketCrawler 命中快照
    coal_dir = tmp_path / "coal" / "cctd"
    coal_dir.mkdir(parents=True, exist_ok=True)
    (coal_dir / "cctd_q5500_latest.html").write_text(
        "<table><tr><td>2026-08-15</td><td>5500大卡动力煤</td><td>850.0</td></tr></table>",
        encoding="utf-8",
    )

    class MockCoalParser:
        def parse(self, html_text: str, **kwargs) -> dict:
            return {"report_date": "2026-08-15", "q5500_fob_price_cny": 850.0}

    coal_crawler = CoalMarketCrawler(raw_dir=tmp_path, parser=MockCoalParser())
    cached_coal = coal_crawler.fetch_latest_q5500(force=False)
    assert cached_coal is not None
    assert cached_coal["q5500_fob_price_cny"] == 850.0

    # 2. InfoLinkPvPriceCrawler 命中快照
    energy_dir = tmp_path / "energy"
    energy_dir.mkdir(parents=True, exist_ok=True)
    (energy_dir / "infolink_live_spot_price.html").write_text(
        "<html><body>Spot Price</body></html>",
        encoding="utf-8",
    )

    class MockPvParser:
        def parse(self, html_text: str, **kwargs) -> dict:
            return {
                "report_date": "2026-08-20",
                "trade_date": date(2026, 8, 20),
                "polysilicon_price_cny_kg": 40.0,
                "wafer_price_cny_piece": 1.2,
                "cell_price_cny_watt": 0.3,
                "module_price_cny_watt": 0.7,
            }

    pv_crawler = InfoLinkPvPriceCrawler(raw_dir=tmp_path, parser=MockPvParser())
    cached_pv = pv_crawler.fetch_live_spot_prices(force=False)
    assert cached_pv is not None
    assert cached_pv["polysilicon_price_cny_kg"] == 40.0


def test_execute_single_industry_task_dispatcher(tmp_path: Path, monkeypatch) -> None:
    """验证 execute_single_industry_task 正确分发到对应 Collector。"""
    from stock_data.fetcher.industry import (
        CoalMarketRecord,
        execute_single_industry_task,
    )
    from stock_data.fetcher.industry.coal.collector import CoalMarketCollector

    # Mock coal collector
    def mock_collect(self, force: bool = False):
        return [
            CoalMarketRecord(
                report_date="2026-08-20",
                trade_date=date(2026, 8, 20),
                q5500_fob_price_cny=850.0,
                coking_coal_price_cny=None,
                power_plant_inventory_million_ton=None,
                power_plant_daily_burn_ten_thousand_ton=None,
                power_plant_available_days=None,
                qinhuangdao_inventory_million_ton=None,
                q5500_price_yoy=None,
                q5500_price_mom=None,
                unit="cny_per_ton",
                source="CCTD",
                source_url="",
                release_date="2026-08-20",
                data_status="actual",
                collected_at="2026-08-20T00:00:00Z",
            )
        ]

    monkeypatch.setattr(CoalMarketCollector, "collect", mock_collect)
    count = execute_single_industry_task(
        endpoint="coal_market",
        raw_dir=tmp_path / "raw",
        curated_dir=tmp_path / "curated",
    )
    assert count == 1
    assert (tmp_path / "curated" / "coal_market.parquet").exists()


def test_industry_task_bundles_expansion() -> None:
    """验证产业任务包在 task_bundles 模块中的展开映射。"""
    from stock_data.core.task_bundles import expand_task_targets

    # 1. 科技硬件包
    tech_tasks = expand_task_targets("industry", ["industry_tech"])
    assert "semiconductor_sales" in tech_tasks
    assert "semiconductor_lead" in tech_tasks
    assert "cloud_capex_quarterly" in tech_tasks
    assert "consumer_electronics" in tech_tasks

    # 2. 周期能源包
    energy_tasks = expand_task_targets("industry", ["industry_energy"])
    assert "solar_capacity" in energy_tasks
    assert "solar_price_chain" in energy_tasks
    assert "non_ferrous_metals" in energy_tasks
    assert "coal_market" in energy_tasks
    assert "chemical_market" in energy_tasks

    # 3. 消费医药包
    consume_tasks = expand_task_targets("industry", ["industry_consume"])
    assert "agriculture_pork" in consume_tasks
    assert "liquor_wholesale" in consume_tasks
    assert "pharma_license_out" in consume_tasks

    # 4. 全产业大包
    all_tasks = expand_task_targets("industry", ["industry_all"])
    assert len(all_tasks) == 16


def test_sync_all_industry_metrics_bundle_orchestration(tmp_path: Path, monkeypatch) -> None:
    """验证 sync_all_industry_metrics 支持按 bundle 编排并使用指定线程池并发执行。"""
    import stock_data.fetcher.industry.pipeline as pipeline_mod

    executed_endpoints: list[str] = []

    def mock_exec(
        endpoint,
        start_date=None,
        end_date=None,
        force_refresh=False,
        raw_dir=None,
        curated_dir=None,
    ):
        executed_endpoints.append(endpoint)
        return 10

    monkeypatch.setattr(pipeline_mod, "execute_single_industry_task", mock_exec)

    res = sync_all_industry_metrics(
        raw_dir=tmp_path / "raw",
        curated_dir=tmp_path / "curated",
        bundle="industry_tech",
        force=True,
        max_workers=4,
    )

    assert "semiconductor_sales" in res
    assert "semiconductor_lead" in res
    assert "cloud_capex_quarterly" in res
    assert "consumer_electronics" in res
    assert len(res) == 4
    assert set(executed_endpoints) == {
        "semiconductor_sales",
        "semiconductor_lead",
        "cloud_capex_quarterly",
        "consumer_electronics",
    }
