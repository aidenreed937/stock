"""创新药海外 License-out (BD) 交易实体解耦与月度特征工程单元测试。"""

from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.models import (
    PharmaBdAssetRecord,
    PharmaBdDealRecord,
    PharmaBdEventRecord,
)
from stock_data.fetcher.industry.pharma.collector import PharmaBdCollector
from stock_data.fetcher.industry.pharma.transform import (
    PHARMA_BD_ASSET_SCHEMA,
    PHARMA_BD_DEAL_SCHEMA,
    PHARMA_BD_EVENT_SCHEMA,
    PHARMA_LICENSE_OUT_SCHEMA,
    assets_to_frame,
    deals_to_frame,
    empty_pharma_license_out,
    events_to_frame,
    records_to_pharma_bd_frame,
)


def test_empty_pharma_license_out() -> None:
    df = empty_pharma_license_out()
    assert df.schema == PHARMA_LICENSE_OUT_SCHEMA
    assert df.is_empty()


def test_deals_assets_events_frame_conversion() -> None:
    deal = PharmaBdDealRecord(
        deal_id="DEAL-TEST-01",
        licensor="恒瑞医药",
        licensor_type="listed_a",
        licensee="Merck & Co.",
        is_mnc=True,
        transaction_type="license_out",
        territory_scope="global_ex_china",
        announcement_date=date(2023, 10, 15),
    )
    df_deal = deals_to_frame([deal])
    assert df_deal.schema == PHARMA_BD_DEAL_SCHEMA
    assert len(df_deal) == 1
    assert df_deal["is_mnc"][0] is True

    asset = PharmaBdAssetRecord(
        asset_id="AST-01",
        deal_id="DEAL-TEST-01",
        drug_name_code="HRS-1167",
        target="PARP1",
        modality="small_molecule",
        stage="phase_1",
    )
    df_asset = assets_to_frame([asset])
    assert df_asset.schema == PHARMA_BD_ASSET_SCHEMA
    assert len(df_asset) == 1

    event = PharmaBdEventRecord(
        event_id="EVT-01",
        deal_id="DEAL-TEST-01",
        event_type="initial_deal",
        event_date=date(2023, 10, 15),
        upfront_cash_usd=160000000.0,
        potential_total_deal_usd=1400000000.0,
    )
    df_event = events_to_frame([event])
    assert df_event.schema == PHARMA_BD_EVENT_SCHEMA
    assert len(df_event) == 1
    assert df_event["upfront_cash_usd"][0] == 160000000.0


def test_pharma_bd_collector_and_aggregation(tmp_path: Path, monkeypatch) -> None:
    from stock_data.fetcher.industry.pharma.crawler import PharmaAnnouncementCrawler

    raw_dir = tmp_path / "raw_industry"
    processed_dir = tmp_path / "processed_industry"
    pharma_dir = raw_dir / "pharma"
    pharma_dir.mkdir(parents=True)

    # mock 在线公告爬虫, 以最新采集为准
    sample_deal = {
        "deal_id": "DEAL-TEST-01",
        "licensor": "恒瑞医药",
        "licensor_type": "listed_a",
        "licensee": "Merck & Co.",
        "is_mnc": True,
        "transaction_type": "license_out",
        "territory_scope": "global_ex_china",
        "announcement_date": "2023-10-15",
        "effective_date": "2023-10-15",
        "source_filing": "HKEX / PR",
        "source_url": "http://www.hkexnews.hk",
        "assets": [
            {
                "asset_id": "AST-01",
                "drug_name_code": "HRS-1167",
                "target": "PARP1",
                "modality": "adc",
                "stage": "phase_2",
                "indication": "Solid Tumors",
            }
        ],
        "events": [
            {
                "event_id": "EVT-01",
                "event_type": "initial_deal",
                "event_date": "2023-10-15",
                "upfront_cash_usd": 160000000.0,
                "potential_total_deal_usd": 1400000000.0,
            }
        ],
    }
    monkeypatch.setattr(PharmaAnnouncementCrawler, "fetch_latest_deals", lambda self: [sample_deal])

    collector = PharmaBdCollector(raw_dir=raw_dir, processed_dir=processed_dir)
    records = collector.collect()

    assert len(records) >= 1
    df_curated = records_to_pharma_bd_frame(records)
    assert not df_curated.is_empty()
    assert "upfront_cash_million_usd" in df_curated.columns
    assert "upfront_3mma" in df_curated.columns
    assert "yoy_growth_3mma" in df_curated.columns
    assert "adc_asset_count" in df_curated.columns

    # 实体表落盘检查
    assert (processed_dir / "pharma_bd_deals.parquet").exists()
    assert (processed_dir / "pharma_bd_assets.parquet").exists()
    assert (processed_dir / "pharma_bd_events.parquet").exists()


def test_pharma_announcement_crawler_extraction() -> None:
    from stock_data.fetcher.industry.pharma.crawler import (
        PharmaAnnouncementCrawler,
        extract_modality_and_target,
        extract_money_usd,
        match_mnc_licensee,
    )

    # 1. 货币与金额抽取测试
    text_cny = "本协议项下首付款为人民币3.5亿元，潜在总交易金额最高可达120亿元人民币。"
    upfront_cny, total_cny = extract_money_usd(text_cny)
    assert upfront_cny is not None and upfront_cny > 40_000_000.0
    assert total_cny is not None and total_cny > 1_500_000_000.0

    text_usd = "Company will receive an upfront payment of $150 million, and up to $1.2 billion in total milestones."
    upfront_usd, total_usd = extract_money_usd(text_usd)
    assert upfront_usd == 150_000_000.0
    assert total_usd == 1_200_000_000.0

    # 2. 模态与靶点抽取测试
    modality_adc, target_adc = extract_modality_and_target(
        "新型 HER2 抗体偶联药物 (ADC) 全球独家授权合作"
    )
    assert modality_adc == "adc"
    assert "HER2" in target_adc

    modality_bisp, target_bisp = extract_modality_and_target(
        "PD-1/VEGF 双特异性抗体海外临床开发合作协议"
    )
    assert modality_bisp == "bispecific"
    assert "PD-1" in target_bisp or "VEGF" in target_bisp

    # 3. MNC 买方识别测试
    licensee_msd, is_mnc_msd = match_mnc_licensee(
        "关于与默沙东 (Merck & Co.) 签署全球独家许可协议的公告"
    )
    assert is_mnc_msd is True
    assert "Merck" in licensee_msd

    # 4. 单条公告解析结构化测试
    crawler = PharmaAnnouncementCrawler()
    mock_ann = {
        "secName": "恒瑞医药",
        "announcementTitle": "关于与阿斯利康 (AstraZeneca) 签署 Claudin 18.2 ADC 对外许可协议的公告",
        "announcementTime": 1700000000000,
        "announcementContent": "首付款1亿美元，交易总额最高达15亿美元，授予其全球独家开发权益。",
    }
    parsed = crawler.parse_announcement_item(mock_ann)
    assert parsed is not None
    assert parsed["licensor"] == "恒瑞医药"
    assert parsed["is_mnc"] is True
    assert parsed["licensee"] == "AstraZeneca"
    assert parsed["assets"][0]["modality"] == "adc"
    assert parsed["events"][0]["upfront_cash_usd"] == 100_000_000.0


def test_pharma_announcement_without_amount_keeps_amounts_null() -> None:
    from stock_data.fetcher.industry.pharma.crawler import PharmaAnnouncementCrawler

    crawler = PharmaAnnouncementCrawler()
    parsed = crawler.parse_announcement_item(
        {
            "secName": "测试药企",
            "announcementTitle": "关于与海外合作方签署创新药对外许可协议的公告",
            "announcementTime": 1700000000000,
            "announcementContent": "双方将在海外临床开发和商业化方面开展合作。",
        }
    )

    assert parsed is not None
    event = parsed["events"][0]
    assert event["upfront_cash_usd"] is None
    assert event["potential_total_deal_usd"] is None


def test_pharma_announcement_without_announcement_time_is_skipped() -> None:
    from stock_data.fetcher.industry.pharma.crawler import PharmaAnnouncementCrawler

    crawler = PharmaAnnouncementCrawler()
    parsed = crawler.parse_announcement_item(
        {
            "secName": "测试药企",
            "announcementTitle": "关于与海外合作方签署创新药对外许可协议的公告",
            "announcementContent": "首付款1亿美元，交易总额最高达15亿美元。",
        }
    )

    assert parsed is None


def test_pharma_bd_collector_with_crawler_live_merge(tmp_path: Path) -> None:
    from unittest.mock import patch

    raw_dir = tmp_path / "raw_industry"
    processed_dir = tmp_path / "processed_industry"
    pharma_dir = raw_dir / "pharma"
    pharma_dir.mkdir(parents=True)

    mock_new_deal = {
        "deal_id": "DEAL-LIVE-2024-08-TEST",
        "licensor": "百利天恒",
        "licensor_type": "listed_a",
        "licensee": "Bristol Myers Squibb",
        "is_mnc": True,
        "transaction_type": "license_out",
        "territory_scope": "global_ex_china",
        "announcement_date": "2024-08-15",
        "effective_date": "2024-08-15",
        "source_filing": "CNINFO",
        "assets": [
            {
                "asset_id": "AST-LIVE-01",
                "drug_name_code": "BL-M07D1",
                "target": "HER2",
                "modality": "adc",
                "stage": "phase_1",
                "indication": "Solid Tumors",
            }
        ],
        "events": [
            {
                "event_id": "EVT-LIVE-01",
                "event_type": "initial_deal",
                "event_date": "2024-08-15",
                "upfront_cash_usd": 500000000.0,
                "potential_total_deal_usd": 3000000000.0,
            }
        ],
    }

    collector = PharmaBdCollector(raw_dir=raw_dir, processed_dir=processed_dir)
    with patch.object(collector.crawler, "fetch_latest_deals", return_value=[mock_new_deal]):
        records = collector.collect()
        assert len(records) == 1
        rec_2024_08 = next(r for r in records if r.report_month == "2024-08")
        assert rec_2024_08.deal_count == 1
        assert rec_2024_08.upfront_cash_million_usd == 500.0


def test_pharma_crawler_tolerates_null_announcement_payload(tmp_path: Path, monkeypatch) -> None:
    """巨潮资讯返回 JSON null 时应降级为空结果，而不是抛 NoneType 异常。"""
    from stock_data.fetcher.industry.pharma import crawler as crawler_module

    class _NullResponse:
        status_code = 200
        text = "null"

    class _FakeRequests:
        @staticmethod
        def post(*args: object, **kwargs: object) -> _NullResponse:
            return _NullResponse()

    monkeypatch.setattr(crawler_module, "requests", _FakeRequests)
    crawler = crawler_module.PharmaAnnouncementCrawler(raw_dir=tmp_path)

    assert crawler.fetch_latest_deals() == []
