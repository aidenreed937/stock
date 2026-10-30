"""EastmoneyReportCollector 单元测试。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from stock_data.fetcher.industry.chemicals.collectors.eastmoney_report import (
    EastmoneyReportCollector,
    ReportItem,
)


@pytest.fixture
def sample_raw_items() -> list[dict[str, Any]]:
    return [
        {
            "infoCode": "AP001",
            "title": "氯碱化工行业深度：烧碱与PVC供需格局演变",
            "orgSName": "中信证券",
            "publishDate": "2024-05-15 08:30:00",
            "industryName": "化学原料",
            "researcher": "张三,李四",
        },
        {
            "infoCode": "AP002",
            "title": "食品饮料周报：白酒动销韧性显现",
            "orgSName": "国泰君安",
            "publishDate": "2024-05-16 09:00:00",
            "industryName": "食品饮料",
            "researcher": "王五",
        },
        {
            "infoCode": "AP003",
            "title": "化纤产业链跟踪：PTA与聚酯负荷平稳",
            "orgSName": "华泰证券",
            "publishDate": "2024-05-17 10:00:00",
            "industryName": "化学纤维",
            "researcher": "赵六",
        },
    ]


def test_filter_reports(tmp_path: Path, sample_raw_items: list[dict[str, Any]]) -> None:
    collector = EastmoneyReportCollector(raw_pdf_dir=tmp_path, enable_network=False)
    filtered = collector.filter_reports(
        sample_raw_items, target_products=["caustic_soda", "pvc", "pta"]
    )

    assert len(filtered) == 2
    assert filtered[0].info_code == "AP001"
    assert "caustic_soda" in filtered[0].matched_products
    assert "pvc" in filtered[0].matched_products
    assert filtered[0].pdf_url == "https://pdf.dfcfw.com/pdf/H3_AP001_1.pdf"

    assert filtered[1].info_code == "AP003"
    assert "pta" in filtered[1].matched_products


def test_download_pdf_cached(tmp_path: Path) -> None:
    collector = EastmoneyReportCollector(raw_pdf_dir=tmp_path, enable_network=False)
    item = ReportItem(
        info_code="AP001",
        title="测试研报",
        org_name="中信证券",
        publish_date="2024-05-15",
        industry_name="化学原料",
        authors=["张三"],
        pdf_url="https://fake.url/test.pdf",
        matched_products=["caustic_soda"],
    )

    pdf_file = tmp_path / "2024-05-15_中信证券_AP001.pdf"
    pdf_file.write_bytes(b"dummy pdf content for sha256 test")

    dest_path, sha256_val = collector.download_pdf(item, force=False)
    assert dest_path == pdf_file
    assert sha256_val is not None
    assert len(sha256_val) == 64


def test_extract_capacity_sections_mock(tmp_path: Path) -> None:
    collector = EastmoneyReportCollector(raw_pdf_dir=tmp_path, enable_network=False)
    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 dummy")

    mock_page1 = MagicMock()
    mock_page1.extract_text.return_value = "普通宏观叙述，未提及核心词汇"

    mock_page2 = MagicMock()
    mock_page2.extract_text.return_value = (
        "2024年全国烧碱总产能达到4988万吨，行业开工率保持在82.5%\n下游氧化铝新增产能投产拉动刚需"
    )

    mock_reader = MagicMock()
    mock_reader.pages = [mock_page1, mock_page2]

    with patch(
        "stock_data.fetcher.industry.chemicals.collectors.eastmoney_report.PdfReader",
        return_value=mock_reader,
    ):
        sections = collector.extract_capacity_sections(fake_pdf)

    assert len(sections) == 1
    assert sections[0].page_number == 2
    assert "总产能" in sections[0].matched_keywords
    assert "万吨" in sections[0].matched_keywords
    assert "4988万吨" in sections[0].snippet


def test_sync_and_extract_end_to_end(
    tmp_path: Path, sample_raw_items: list[dict[str, Any]]
) -> None:
    collector = EastmoneyReportCollector(raw_pdf_dir=tmp_path, enable_network=True)

    with (
        patch.object(collector, "fetch_report_list", return_value=sample_raw_items),
        patch.object(collector, "download_pdf", return_value=(tmp_path / "test.pdf", "mocksha256")),
        patch.object(collector, "extract_capacity_sections", return_value=[]),
    ):
        records = collector.sync_and_extract(
            target_products=["caustic_soda"],
            max_pages=1,
            download_pdfs=True,
        )

    assert len(records) == 1
    assert records[0].info_code == "AP001"
    assert records[0].sha256 == "mocksha256"

    # 验证 manifest 写入
    manifest_path = tmp_path / "manifest.json"
    assert manifest_path.exists()
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "AP001" in manifest_data["reports"]
    assert manifest_data["total_count"] == 1
