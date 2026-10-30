"""国家统计局 (NBS) 流通领域重要生产资料解析器单元测试。"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup

from stock_data.fetcher.industry.chemicals.parsers.nbs_production_materials import (
    extract_nbs_commodity_prices,
    parse_nbs_report_metadata,
    save_nbs_prices_to_survey_csv,
)

SAMPLE_NBS_HTML = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="ArticleTitle" content="2026年9月上旬流通领域重要生产资料市场价格变动情况">
    <meta name="PubDate" content="2026/09/14 09:30">
    <title>2026年9月上旬流通领域重要生产资料市场价格变动情况 - 国家统计局</title>
</head>
<body>
    <table class="detail-text-content">
        <tr>
            <th>产品名称</th>
            <th>计量单位</th>
            <th>本期价格</th>
            <th>比上期涨跌</th>
            <th>涨跌幅(%)</th>
        </tr>
        <tr>
            <td>硫酸（98%）</td>
            <td>吨</td>
            <td>1835.7</td>
            <td>-68.1</td>
            <td>-3.6</td>
        </tr>
        <tr>
            <td>烧碱（液碱，32%）</td>
            <td>吨</td>
            <td>682.6</td>
            <td>-2.8</td>
            <td>-0.4</td>
        </tr>
        <tr>
            <td>甲醇（优等品）</td>
            <td>吨</td>
            <td>3379.1</td>
            <td>505.9</td>
            <td>17.6</td>
        </tr>
    </table>
    <!-- 模拟移动端重复表格 -->
    <table class="mobile-news-content">
        <tr>
            <td>硫酸（98%）</td>
            <td>吨</td>
            <td>1835.7</td>
            <td>-68.1</td>
            <td>-3.6</td>
        </tr>
    </table>
</body>
</html>
"""


def test_parse_nbs_report_metadata():
    soup = BeautifulSoup(SAMPLE_NBS_HTML, "html.parser")
    title, release_date, trade_date = parse_nbs_report_metadata(soup)
    assert title == "2026年9月上旬流通领域重要生产资料市场价格变动情况"
    assert release_date == date(2026, 9, 14)
    assert trade_date == date(2026, 9, 10)


def test_parse_nbs_report_metadata_tendays():
    # 测试中旬与下旬
    for tenday, expected_day in [("中旬", 20), ("下旬", 28)]:
        html = f"""<html><head>
        <meta name="ArticleTitle" content="2025年2月{tenday}流通领域重要生产资料市场价格变动情况">
        <meta name="PubDate" content="2025/03/04">
        </head><body></body></html>"""
        soup = BeautifulSoup(html, "html.parser")
        _, rel_d, tr_d = parse_nbs_report_metadata(soup)
        assert tr_d == date(2025, 2, expected_day)
        assert rel_d == date(2025, 3, 4)


def test_extract_nbs_commodity_prices_deduplication():
    records = extract_nbs_commodity_prices(
        SAMPLE_NBS_HTML,
        source_url="https://www.stats.gov.cn/test.html",
        target_symbols=["H2SO4"],
    )
    # 尽管 HTML 中有桌面和移动端两套表格，记录应被去重为 1 条
    assert len(records) == 1
    rec = records[0]
    assert rec["symbol"] == "H2SO4"
    assert rec["product_name"] == "硫酸"
    assert rec["spot_price_cny"] == 1835.7
    assert rec["trade_date"] == "2026-09-10"
    assert rec["release_date"] == "2026-09-14"
    assert rec["source"] == "NBS_流通领域重要生产资料"


def test_extract_multiple_nbs_commodities():
    records = extract_nbs_commodity_prices(
        SAMPLE_NBS_HTML,
        source_url="https://www.stats.gov.cn/test.html",
        target_symbols=["H2SO4", "NaOH", "Methanol"],
    )
    symbols = {r["symbol"] for r in records}
    assert symbols == {"H2SO4", "NaOH", "Methanol"}
    prices = {r["symbol"]: r["spot_price_cny"] for r in records}
    assert prices["H2SO4"] == 1835.7
    assert prices["NaOH"] == 682.6
    assert prices["Methanol"] == 3379.1


def test_save_nbs_prices_to_survey_csv(tmp_path: Path):
    csv_file = tmp_path / "expert_prices_survey.csv"
    initial_rows = [
        {
            "trade_date": "2026-08-31",
            "report_date": "2026-08-31",
            "product_name": "钛白粉",
            "symbol": "TiO2",
            "spec": "金红石型;硫酸法",
            "spot_price_cny": 13400.0,
            "unit": "元/吨",
            "source": "攀枝花钒钛交易中心",
            "source_url": "https://test.com",
            "release_date": "2026-09-01",
            "data_status": "verified_industry_report",
            "collected_at": "2026-09-16T00:00:00Z",
        }
    ]
    with csv_file.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(initial_rows[0].keys()))
        writer.writeheader()
        writer.writerows(initial_rows)

    new_records = [
        {
            "trade_date": "2026-09-10",
            "report_date": "2026-09-10",
            "product_name": "硫酸",
            "symbol": "H2SO4",
            "spec": "98%;工业级浓硫酸",
            "spot_price_cny": 1835.7,
            "unit": "元/吨",
            "source": "NBS_流通领域重要生产资料",
            "source_url": "https://stats.gov.cn/test.html",
            "release_date": "2026-09-14",
            "data_status": "verified_industry_report",
            "collected_at": "2026-09-16T10:00:00Z",
        }
    ]

    saved = save_nbs_prices_to_survey_csv(new_records, csv_file)
    assert saved.exists()

    with saved.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    symbols = [r["symbol"] for r in rows]
    assert "TiO2" in symbols
    assert "H2SO4" in symbols
