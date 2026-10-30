from pathlib import Path
from unittest.mock import MagicMock, patch

from stock_data.fetcher.industry.chemicals.collectors.cfa_futures import (
    CFA_PROGRAM_MAPPING,
    CFAFuturesReportCollector,
)
from stock_data.fetcher.industry.chemicals.collectors.mysteel_backfill import (
    MysteelWeeklyBackfiller,
)
from stock_data.fetcher.industry.chemicals.reparse import reparse_all_snapshots_offline


def test_cfa_program_mapping_coverage() -> None:
    """验证 CFA 支持的核心大宗能化品种代码映射。"""
    assert "SA" in CFA_PROGRAM_MAPPING
    assert "TA" in CFA_PROGRAM_MAPPING
    assert "MA" in CFA_PROGRAM_MAPPING
    assert "V" in CFA_PROGRAM_MAPPING
    assert "MEG" in CFA_PROGRAM_MAPPING
    assert CFA_PROGRAM_MAPPING["SA"]["product_name"] == "纯碱"
    assert CFA_PROGRAM_MAPPING["V"]["product_name"] == "聚氯乙烯"


def test_discover_cfa_reports(tmp_path: Path) -> None:
    """验证 CFA 官方 REST API 研报发现逻辑。"""
    collector = CFAFuturesReportCollector(raw_dir=tmp_path)

    mock_api_payload = {
        "data": {
            "dataList": [
                {
                    "docTitle": "弘业期货-纯碱周报-260821",
                    "docPubUrl": "/servicesupport/analygarden/nyhgl/cj_5769/202608/P020260821123456.pdf",
                    "docRelTime": "2026-08-21 17:30:00",
                    "docAuthor": "张三",
                    "docSourceName": "弘业期货",
                },
                {
                    "docTitle": "无效文档非PDF",
                    "docPubUrl": "/some/page.html",
                    "docRelTime": "2026-08-21",
                },
            ]
        }
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_api_payload

    with patch("curl_cffi.requests.get", return_value=mock_resp):
        reports = collector.discover_reports(symbol="SA", max_pages=1)

    assert len(reports) == 1
    assert reports[0]["title"] == "弘业期货-纯碱周报-260821"
    assert reports[0]["publish_date"] == "2026-08-21"
    assert reports[0]["url"].startswith("https://www.cfachina.org/")
    assert reports[0]["url"].endswith(".pdf")


def test_backfill_and_parse_cfa_reports(tmp_path: Path) -> None:
    """验证 CFA 研报下载、多品种指标提取与 CSV 入库闭环。"""
    collector = CFAFuturesReportCollector(raw_dir=tmp_path)

    mock_text = """
    供给方面：本周纯碱产量回升，整体高位震荡。截至8月20日当周，纯碱综合产能利用率78.31%（周环比+2.16个百分点），纯碱产量74.58万吨。
    库存：本周截至8月20日，纯碱厂家总库存184.49万吨。
    """
    reports = [
        {
            "title": "弘业期货-纯碱周报",
            "url": "https://www.cfachina.org/test.pdf",
            "publish_date": "2026-08-21",
        }
    ]

    with (
        patch("curl_cffi.requests.get") as mock_get,
        patch("pypdf.PdfReader") as mock_pdf,
    ):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"fake-pdf-content"
        mock_get.return_value = mock_resp

        mock_page = MagicMock()
        mock_page.extract_text.return_value = mock_text
        mock_reader_instance = MagicMock()
        mock_reader_instance.pages = [mock_page]
        mock_pdf.return_value = mock_reader_instance

        added = collector.backfill_and_parse(
            reports=reports,
            symbol="SA",
            product_name="纯碱",
            force=True,
        )

    assert added >= 1
    records = collector.collector._load_raw_csv()
    key = ("纯碱", "2026-08-20", "CFA_Futures_Report:Longzhong")
    assert key in records
    rec = records[key]
    assert rec["operating_rate_pct"] == 78.31
    assert rec["weekly_output_w_tons"] == 74.58
    assert rec["factory_inventory_w_tons"] == 184.49


def test_mysteel_backfiller_sync_sources_csv(tmp_path: Path) -> None:
    """验证 Mysteel 周报清单增量同步逻辑。"""
    backfiller = MysteelWeeklyBackfiller(raw_dir=tmp_path)
    config_csv = tmp_path / "chemicals_weekly_sources.csv"

    discovered = {
        "2026-09-17": ("纯碱产量周数据分析（20260917）", "https://nenghua.mysteel.com/a/1.html"),
        "2026-09-10": ("纯碱产量周数据分析（20260910）", "https://nenghua.mysteel.com/a/2.html"),
    }

    added = backfiller.sync_sources_csv(discovered, config_csv)
    assert added == 2
    assert config_csv.exists()

    # 重复同步幂等
    added_again = backfiller.sync_sources_csv(discovered, config_csv)
    assert added_again == 0


def test_reparse_all_snapshots_empty_dir(tmp_path: Path) -> None:
    """验证快照目录为空或不存在时离线重放引擎的优雅防御。"""
    count = reparse_all_snapshots_offline(raw_dir=tmp_path)
    assert count == 0
