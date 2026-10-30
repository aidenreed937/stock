"""TSMC 官方先进封装财务拆解解析与增量爬虫测试。"""

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from stock_data.fetcher.industry.semiconductor.collectors.adv_pkg_revenue import (
    TsmcAdvancedPackagingRevenueCollector,
)
from stock_data.fetcher.industry.semiconductor.collectors.tsmc_adv_pkg_crawler import (
    TsmcAdvPkgRevenueCrawler,
    _next_candidate_quarters,
)
from stock_data.fetcher.industry.semiconductor.parsers.adv_pkg_revenue import (
    append_tsmc_adv_pkg_revenue_raw_record,
    load_tsmc_adv_pkg_revenue_raw_csv,
    parse_tsmc_management_report_pdf,
)


def test_next_candidate_quarters() -> None:
    assert _next_candidate_quarters("2026Q2", count=3) == ["2026Q3", "2026Q4", "2027Q1"]
    assert _next_candidate_quarters("2024Q4", count=2) == ["2025Q1", "2025Q2"]
    assert _next_candidate_quarters("invalid") == []


def test_parse_tsmc_management_report_pdf_historical() -> None:
    sample_pdf = Path(
        "data/raw/industry/semiconductor/tsmc_filings/tsmc_2024Q4_management_report.pdf"
    )
    if not sample_pdf.exists():
        pytest.skip("本地存量 PDF 不存在，跳过离线解析测试")

    parsed = parse_tsmc_management_report_pdf(sample_pdf)
    assert parsed is not None
    assert parsed["symbol"] == "2330.TW"
    assert parsed["report_quarter"] == "2024Q4"
    assert parsed["trade_date"] == date(2024, 12, 31)
    assert parsed["release_date"] == date(2025, 1, 16)
    assert parsed["net_revenue_ntd_bn"] == 868.46
    assert parsed["net_revenue_usd_bn"] == 26.88
    assert parsed["advanced_wafer_pct"] == 0.74
    assert parsed["hpc_platform_pct"] == 0.53


def test_append_tsmc_adv_pkg_revenue_raw_record(tmp_path: Path) -> None:
    csv_file = tmp_path / "tsmc_adv_pkg_revenue_raw.csv"

    # 初始化一条记录
    rec1 = {
        "symbol": "2330.TW",
        "report_quarter": "2026Q1",
        "trade_date": date(2026, 3, 31),
        "release_date": date(2026, 4, 16),
        "net_revenue_ntd_bn": 1134.1,
        "net_revenue_usd_bn": 35.9,
        "advanced_wafer_pct": 0.74,
        "hpc_platform_pct": 0.61,
        "packaging_testing_others_pct": 0.095,
        "data_status": "actual",
        "source": "TSMC_OFFICIAL_MANAGEMENT_REPORT",
        "source_url": "https://investor.tsmc.com",
        "collected_at": "2026-04-16T00:00:00Z",
        "raw_content_sha256": "hash1",
        "raw_snapshot_path": "data/raw/filing1.pdf",
    }
    appended = append_tsmc_adv_pkg_revenue_raw_record(csv_file, [rec1])
    assert appended == 1

    # 尝试重复追加已存在记录，应被排重忽略
    appended_dup = append_tsmc_adv_pkg_revenue_raw_record(csv_file, [rec1])
    assert appended_dup == 0

    # 追加乱序新记录，应自动按 trade_date 升序排序
    rec0 = dict(rec1, report_quarter="2025Q4", trade_date=date(2025, 12, 31))
    rec2 = dict(rec1, report_quarter="2026Q2", trade_date=date(2026, 6, 30))
    appended_new = append_tsmc_adv_pkg_revenue_raw_record(csv_file, [rec2, rec0])
    assert appended_new == 2

    records = load_tsmc_adv_pkg_revenue_raw_csv(csv_file, verify_hash=False)
    assert len(records) == 3
    assert [r.report_quarter for r in records] == ["2025Q4", "2026Q1", "2026Q2"]


def test_tsmc_adv_pkg_crawler_incremental_mock(tmp_path: Path) -> None:
    raw_dir = tmp_path / "data" / "raw"
    filings_dir = raw_dir / "semiconductor" / "tsmc_filings"
    filings_dir.mkdir(parents=True, exist_ok=True)
    csv_file = raw_dir / "semiconductor" / "tsmc_adv_pkg_revenue_raw.csv"

    # 写入初始 CSV (截止到 2024Q3)
    rec_init = {
        "symbol": "2330.TW",
        "report_quarter": "2024Q3",
        "trade_date": date(2024, 9, 30),
        "release_date": date(2024, 10, 17),
        "net_revenue_ntd_bn": 759.69,
        "net_revenue_usd_bn": 23.5,
        "advanced_wafer_pct": 0.69,
        "hpc_platform_pct": 0.51,
        "packaging_testing_others_pct": 0.08,
        "data_status": "actual",
        "source": "TSMC_OFFICIAL_MANAGEMENT_REPORT",
        "source_url": "https://investor.tsmc.com",
        "collected_at": "2024-10-17T00:00:00Z",
        "raw_content_sha256": "init_hash",
        "raw_snapshot_path": "dummy.pdf",
    }
    append_tsmc_adv_pkg_revenue_raw_record(csv_file, [rec_init])

    crawler = TsmcAdvPkgRevenueCrawler(raw_dir=raw_dir)

    # 读取本地真实 2024Q4 PDF 作为 Mock 返回
    real_pdf = Path(
        "data/raw/industry/semiconductor/tsmc_filings/tsmc_2024Q4_management_report.pdf"
    )
    if not real_pdf.exists():
        pytest.skip("真实 2024Q4 PDF 不存在，跳过 mock 增量测试")
    pdf_bytes = real_pdf.read_bytes()

    html_content = b'<html><body><a href="https://investor.tsmc.com/files/tsmc_2024Q4_management_report.pdf">Management Report PDF</a></body></html>'

    def fake_get(url: str, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if url.endswith(".pdf"):
            resp.content = pdf_bytes
        else:
            resp.content = html_content
        return resp

    with patch.object(crawler, "_get_tsmc", side_effect=fake_get):
        new_records = crawler.sync_incremental(current_max_quarter="2024Q3")

    assert len(new_records) >= 1
    assert new_records[0]["report_quarter"] == "2024Q4"
    assert new_records[0]["net_revenue_ntd_bn"] == 868.46
    assert (filings_dir / "tsmc_2024Q4_management_report.pdf").exists()

    # 验证 CSV 已成功追加
    records_in_csv = load_tsmc_adv_pkg_revenue_raw_csv(csv_file, verify_hash=False)
    assert any(r.report_quarter == "2024Q4" for r in records_in_csv)


def test_tsmc_adv_pkg_crawler_network_graceful_failure(tmp_path: Path) -> None:
    raw_dir = tmp_path / "data" / "raw"
    crawler = TsmcAdvPkgRevenueCrawler(raw_dir=raw_dir)

    def failing_get(url: str, **kwargs):
        raise ConnectionError("Mock network connection timeout")

    with patch.object(crawler, "_get_tsmc", side_effect=failing_get):
        # 即使发生网络连接异常，也绝不崩溃，而是返回空列表
        result = crawler.sync_incremental(current_max_quarter="2026Q2")
        assert result == []


def test_tsmc_collector_full_flow() -> None:
    # 针对本地生产 RAW 目录执行采集器测试（真实存在 18 份存量文件）
    collector = TsmcAdvancedPackagingRevenueCollector(raw_dir="data/raw/industry")
    # 模拟网络不可达，纯粹回退读取本地存量
    with patch(
        "stock_data.fetcher.industry.semiconductor.collectors.tsmc_adv_pkg_crawler.TsmcAdvPkgRevenueCrawler.sync_incremental",
        return_value=[],
    ):
        records = collector.collect()

    assert len(records) >= 34
    assert records[0].report_quarter == "2018Q1"
    # 首条为不可变历史值，用于锁定解析正确性
    assert records[0].net_revenue_ntd_bn == 248.08
    assert records[0].data_status == "actual"

    # 报告期须单调递增，且已推进到至少 2026Q2；本地存量随披露持续增长，不锁定具体季度
    keys = [(int(record.report_quarter[:4]), int(record.report_quarter[-1])) for record in records]
    assert keys == sorted(keys)
    assert keys[-1] >= (2026, 2)
    assert records[-1].net_revenue_ntd_bn > 0
    assert records[-1].data_status == "actual"
