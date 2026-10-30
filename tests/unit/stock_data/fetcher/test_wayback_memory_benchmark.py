"""测试 Wayback Machine 内存现货多点快照基准采集器 (WaybackMemoryPriceBenchmarkCollector)。"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from stock_data.fetcher.industry.semiconductor.collectors.wayback_memory_benchmark import (
    WaybackMemoryPriceBenchmarkCollector,
    parse_dramexchange_snapshot_html,
)
from stock_data.fetcher.industry.semiconductor.schemas import (
    MEMORY_BENCHMARK_CURATED_SCHEMA,
    MEMORY_BENCHMARK_RAW_SCHEMA,
)
from stock_data.fetcher.industry.semiconductor.transforms import (
    records_to_memory_benchmark_frame,
    records_to_raw_memory_benchmark_frame,
)

SAMPLE_HTML_2021_08 = """
<html>
<body>
<table>
  <tr><td>DRAM Spot Price</td></tr>
  <tr><td>Item</td><td>Daily High</td><td>Daily Low</td><td>Session High</td><td>Session Low</td><td>Session Average</td><td>Session Change</td></tr>
  <tr><td>DDR4 16G (2G*8) 2666 Mbps</td><td>8.50</td><td>8.00</td><td>8.50</td><td>8.00</td><td>8.170</td><td>-0.12 %</td></tr>
  <tr><td>DDR4 8G (1G*8) 2666 Mbps</td><td>5.05</td><td>4.10</td><td>5.05</td><td>4.10</td><td>4.223</td><td>-0.05 %</td></tr>
  <tr><td>Wafer Spot Price</td></tr>
  <tr><td>Item</td><td>Weekly High</td><td>Weekly Low</td><td>Session High</td><td>Session Low</td><td>Session Average</td><td>Average Change</td></tr>
  <tr><td>512Gb TLC</td><td>5.50</td><td>4.70</td><td>5.50</td><td>4.70</td><td>4.894</td><td>0.10 %</td></tr>
</table>
</body>
</html>
"""

SAMPLE_HTML_2021_12 = """
<html>
<body>
<table>
  <tr><td>DRAM Spot Price</td></tr>
  <tr><td>Item</td><td>Daily High</td><td>Daily Low</td><td>Session High</td><td>Session Low</td><td>Session Average</td><td>Session Change</td></tr>
  <tr><td>DDR4 16Gb (2Gx8) 2666 Mbps</td><td>8.05</td><td>6.75</td><td>8.05</td><td>6.75</td><td>7.400</td><td>0.41 %</td></tr>
  <tr><td>512Gb TLC</td><td>4.40</td><td>3.90</td><td>4.40</td><td>3.90</td><td>4.015</td><td>0.00 %</td></tr>
</table>
</body>
</html>
"""


def test_parse_dramexchange_snapshot_html() -> None:
    """验证从不同时期的快照 HTML 中精准提取 DRAM 与 Wafer 均价。"""
    res1 = parse_dramexchange_snapshot_html(SAMPLE_HTML_2021_08)
    assert res1["DRAM"] == 8.170
    assert res1["NAND"] == 4.894

    res2 = parse_dramexchange_snapshot_html(SAMPLE_HTML_2021_12)
    assert res2["DRAM"] == 7.400
    assert res2["NAND"] == 4.015

    res_empty = parse_dramexchange_snapshot_html("<html><body>empty</body></html>")
    assert res_empty == {}


def test_wayback_collector_offline_caching_and_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证采集器正常抓取、Gzip 存证、离线命中与输出标准 Record。"""
    raw_dir = tmp_path / "raw"
    collector = WaybackMemoryPriceBenchmarkCollector(raw_dir=raw_dir, request_delay=0.0)

    # Mock requests.get to return SAMPLE_HTML_2021_08
    class MockResponse:
        status_code = 200
        url = "https://web.archive.org/web/20210815id_/https://www.dramexchange.com/"
        content = SAMPLE_HTML_2021_08.encode("utf-8")

    network_calls = 0

    def mock_get(*args: Any, **kwargs: Any) -> MockResponse:
        nonlocal network_calls
        network_calls += 1
        return MockResponse()

    monkeypatch.setattr(
        "stock_data.fetcher.industry.semiconductor.collectors.wayback_memory_benchmark.requests.get",
        mock_get,
    )

    # 1. 首次运行：联网抓取并生成缓存
    records = collector.collect(force=False, target_months=["2021-08"])
    assert len(records) == 2  # DRAM (61050) + NAND (6106)
    assert network_calls > 0

    dram_rec = next(r for r in records if r.product_family == "DRAM")
    nand_rec = next(r for r in records if r.product_family == "NAND")

    assert dram_rec.indicator_id == 61050
    assert dram_rec.price_usd == 8.170
    assert dram_rec.report_month == "2021-08"
    assert dram_rec.trade_date == date(2021, 8, 31)
    assert dram_rec.data_status == "wayback_proxy"

    assert nand_rec.indicator_id == 6106
    assert nand_rec.price_usd == 4.894
    assert nand_rec.report_month == "2021-08"
    assert nand_rec.trade_date == date(2021, 8, 31)

    # 2. 二次运行（force=False）：应直接命中本地快照，不再触发网络调用
    calls_before = network_calls
    records_cached = collector.collect(force=False, target_months=["2021-08"])
    assert network_calls == calls_before
    assert len(records_cached) == 2
    assert records_cached[0].price_usd == records[0].price_usd


def test_wayback_records_to_curated_integration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证 Wayback 记录能无缝输入 records_to_memory_benchmark_frame 并生成合规 Curated 表。"""
    raw_dir = tmp_path / "raw"
    collector = WaybackMemoryPriceBenchmarkCollector(raw_dir=raw_dir, request_delay=0.0)

    class MockResponse:
        status_code = 200
        url = "https://web.archive.org/web/20210815id_/https://www.dramexchange.com/"
        content = SAMPLE_HTML_2021_08.encode("utf-8")

    def _mock_get(*args: Any, **kwargs: Any) -> MockResponse:
        return MockResponse()

    monkeypatch.setattr(
        "stock_data.fetcher.industry.semiconductor.collectors.wayback_memory_benchmark.requests.get",
        _mock_get,
    )

    records = collector._collect_month("2021-08", force=False, collected_at="2026-09-11T00:00:00Z")
    assert len(records) == 2

    # RAW 表转换
    raw_df = records_to_raw_memory_benchmark_frame(records)
    assert raw_df.columns == list(MEMORY_BENCHMARK_RAW_SCHEMA)
    assert not raw_df.is_empty()

    # Curated 表转换：应自动匹配 datatrack_release_calendar.yaml 中的 2021-09-03
    curated_df = records_to_memory_benchmark_frame(records)
    assert curated_df.columns == list(MEMORY_BENCHMARK_CURATED_SCHEMA)
    assert len(curated_df) == 2

    dram_row = curated_df.filter(pl.col("product_family") == "DRAM").to_dicts()[0]
    assert dram_row["report_month"] == "2021-08"
    assert dram_row["trade_date"] == date(2021, 8, 31)
    assert dram_row["release_date"] == date(2021, 9, 3)
    assert dram_row["release_date_status"] == "proxy_calendar"
    assert dram_row["price_usd"] == 8.170
