"""工程机械在线爬虫 (CcmaCrawler/KomatsuCrawler) 与双源采集集成单元测试。"""

from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from stock_data.fetcher.industry.machinery.collector import MachineryCollector
from stock_data.fetcher.industry.machinery.crawler import (
    parse_ccma_excavator_article,
    parse_komatsu_china_hours_text,
)


def test_parse_ccma_excavator_article() -> None:
    html_sample = """
    <html>
    <head><title>2026年7月工程机械行业主要产品销售快报一</title></head>
    <body>
    <div class="date">2026年08月07日 21:23</div>
    <div class="content">
    据中国工程机械工业协会对挖掘机主要制造企业统计，2026年7月销售各类挖掘机19521台，同比增长13.9%。
    其中：国内销量7608台（含电动挖掘机41台），同比增长4.13%；出口11913台（含电动挖掘机62台），同比增长21.2%。
    </div>
    </body>
    </html>
    """
    res = parse_ccma_excavator_article(html_sample, source_url="http://www.cncma.org/article/22639")
    assert res is not None
    assert res["report_month"] == "2026-07"
    assert res["excavator_total_units"] == 19521.0
    assert res["excavator_domestic_units"] == 7608.0
    assert res["excavator_export_units"] == 11913.0
    assert res["release_date"] == date(2026, 8, 7)
    assert res["source"] == "CCMA"


def test_parse_komatsu_china_hours_text() -> None:
    text_sample = """
    近日，小松官方公布了2026年7月小松挖掘机开工小时数。
    数据显示，2026年7月中国地区小松挖掘机开工小时数为90.8小时，同比增长1.34%。
    """
    res = parse_komatsu_china_hours_text(text_sample)
    assert "2026-07" in res
    assert res["2026-07"] == 90.8


def test_machinery_collector_online_crawl_and_merge(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw_industry"
    machinery_dir = raw_dir / "machinery"
    machinery_dir.mkdir(parents=True)

    # 1. 写入初始历史数据 (2026-06)
    csv_file = machinery_dir / "excavator_monthly.csv"
    csv_file.write_text(
        "report_month,trade_date,excavator_total_units,excavator_domestic_units,excavator_export_units,komatsu_hours_china,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-06,2026-06-30,25445.0,10898.0,14547.0,91.2,units/hours,CCMA/Komatsu,http://www.cncma.org/,2026-07-07,actual,2026-07-07T10:00:00Z\n",
        encoding="utf-8",
    )

    # 2. Mock 在线爬虫，模拟 CCMA 发布 2026-07 新闻与小松发布 2026-07 开工小时
    mock_ccma_list_resp = MagicMock()
    mock_ccma_list_resp.status_code = 200
    mock_ccma_list_resp.text = (
        '<a href="/article/22639">2026年7月工程机械行业主要产品销售快报一</a>'
    )

    mock_ccma_art_resp = MagicMock()
    mock_ccma_art_resp.status_code = 200
    mock_ccma_art_resp.text = """
    2026年08月07日
    据中国工程机械工业协会对挖掘机主要制造企业统计，2026年7月销售各类挖掘机19521台，同比增长13.9%。
    其中：国内销量7608台，同比增长4.13%；出口11913台，同比增长21.2%。
    """

    mock_komatsu_resp = MagicMock()
    mock_komatsu_resp.status_code = 200
    mock_komatsu_resp.text = "2026年7月中国地区小松挖掘机开工小时数为90.8小时"

    collector = MachineryCollector(raw_dir=raw_dir)

    def custom_requests_get(url: str, **kwargs: Any) -> Any:
        if "column/23" in url:
            return mock_ccma_list_resp
        if "article/22639" in url:
            return mock_ccma_art_resp
        if "demand-orders" in url:
            return mock_komatsu_resp
        resp = MagicMock()
        resp.status_code = 404
        return resp

    with patch("curl_cffi.requests.get", side_effect=custom_requests_get):
        records = collector.collect()

    assert len(records) == 2
    assert records[0].report_month == "2026-06"
    assert records[1].report_month == "2026-07"
    assert records[1].excavator_total_units == 19521.0
    assert records[1].excavator_domestic_units == 7608.0
    assert records[1].excavator_export_units == 11913.0
    assert records[1].komatsu_hours_china == 90.8

    # 验证 CSV 自动回写增量
    updated_csv_text = csv_file.read_text(encoding="utf-8")
    assert "2026-07" in updated_csv_text
    assert "19521.0" in updated_csv_text


def test_machinery_collector_network_error_fallback(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw_industry"
    machinery_dir = raw_dir / "machinery"
    machinery_dir.mkdir(parents=True)

    csv_file = machinery_dir / "excavator_monthly.csv"
    csv_file.write_text(
        "report_month,trade_date,excavator_total_units,excavator_domestic_units,excavator_export_units,komatsu_hours_china,unit,source,source_url,release_date,data_status,collected_at\n"
        "2026-06,2026-06-30,25445.0,10898.0,14547.0,91.2,units/hours,CCMA/Komatsu,http://www.cncma.org/,2026-07-07,actual,2026-07-07T10:00:00Z\n",
        encoding="utf-8",
    )

    collector = MachineryCollector(raw_dir=raw_dir)

    with patch("curl_cffi.requests.get", side_effect=Exception("Network unreachable")):
        records = collector.collect()

    assert len(records) == 1
    assert records[0].report_month == "2026-06"
    assert records[0].excavator_total_units == 25445.0
