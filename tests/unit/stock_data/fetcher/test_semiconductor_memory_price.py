"""测试 TrendForce DRAM/NAND 价格端点。"""

from __future__ import annotations

from datetime import UTC, date, datetime

import polars as pl

from stock_data.fetcher.industry.semiconductor.collectors.memory_price import MemoryPriceCollector
from stock_data.fetcher.industry.semiconductor.parsers import parse_trendforce_memory_price_html
from stock_data.fetcher.industry.semiconductor.schemas import (
    MEMORY_PRICE_CURATED_SCHEMA,
    MEMORY_PRICE_RAW_SCHEMA,
)
from stock_data.fetcher.industry.semiconductor.transforms import (
    build_memory_price_curated_frame,
    build_memory_price_raw_frame,
)
from stock_data.fetcher.industry.task_executor import execute_single_industry_task


def test_parse_trendforce_memory_price_html_keeps_source_table_strings() -> None:
    rows = parse_trendforce_memory_price_html(
        _trendforce_html(),
        product_family="DRAM",
        price_scope="contract",
        page_slug="dram_contract",
        source_url="https://www.trendforce.com/price/dram/dram_contract",
        collected_at="2026-09-04T00:00:00+00:00",
        raw_content_hash="sha-dram",
        raw_snapshot_path="semiconductor/trendforce/dram_contract.html.gz",
    )

    assert len(rows) == 2
    spot = rows[0]
    assert spot["trade_date"] == date(2026, 9, 3)
    assert spot["updated_at_raw"] == "2026-09-03 18:10 (GMT+8)"
    assert spot["product_family"] == "DRAM"
    assert spot["daily_high_raw"] == "2.100"
    assert spot["session_change_raw"] == "1.25%"
    assert spot["raw_content_sha256"] == "sha-dram"


def test_memory_price_curated_numeric_and_percent_conversion() -> None:
    raw = build_memory_price_raw_frame(
        parse_trendforce_memory_price_html(
            _trendforce_html(),
            product_family="DRAM",
            price_scope="contract",
            page_slug="dram_contract",
            source_url="https://www.trendforce.com/price/dram/dram_contract",
            collected_at="2026-09-04T00:00:00+00:00",
            raw_content_hash="sha-dram",
            raw_snapshot_path="semiconductor/trendforce/dram_contract.html.gz",
        )
    )

    assert raw.columns == list(MEMORY_PRICE_RAW_SCHEMA)
    assert raw["session_change_raw"].to_list()[0] == "1.25%"
    assert raw["updated_at_raw"].to_list()[0] == "2026-09-03 18:10 (GMT+8)"
    assert "session_change" not in raw.columns
    assert "session_average_usd" not in raw.columns

    curated = build_memory_price_curated_frame(raw)
    assert curated.columns == list(MEMORY_PRICE_CURATED_SCHEMA)
    assert curated.schema["updated_at"] == pl.Datetime("us", "UTC")
    first = curated.filter(pl.col("item") == "DDR4 8Gb 1Gx8 3200").to_dicts()[0]
    assert first["updated_at"] == datetime(2026, 9, 3, 10, 10, tzinfo=UTC)
    assert first["daily_high_usd"] == 2.1
    assert first["session_average_usd"] == 2.0
    assert first["session_change"] == 0.0125
    contract = curated.filter(pl.col("item") == "DDR5 16Gb 2Gx8 5600").to_dicts()[0]
    assert contract["average_usd"] == 4.6
    assert contract["average_change"] == -0.02
    assert "raw_snapshot_path" not in curated.columns


def test_memory_price_endpoint_writes_raw_and_curated(tmp_path, monkeypatch) -> None:
    class Response:
        status_code = 200
        text = _trendforce_html()
        content = text.encode("utf-8")

    monkeypatch.setattr(MemoryPriceCollector, "_get", lambda self, url: Response())

    count = execute_single_industry_task(
        endpoint="semiconductor_memory_price",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 4),
        raw_dir=tmp_path / "raw",
        curated_dir=tmp_path / "curated",
    )

    assert count == 8
    raw = pl.read_parquet(
        tmp_path / "raw" / "semiconductor" / "price" / "semiconductor_memory_price.parquet"
    )
    curated = pl.read_parquet(
        tmp_path / "curated" / "semiconductor" / "price" / "semiconductor_memory_price.parquet"
    )
    assert raw.columns == list(MEMORY_PRICE_RAW_SCHEMA)
    assert curated.columns == list(MEMORY_PRICE_CURATED_SCHEMA)
    assert "average_change" not in raw.columns
    assert "average_change" in curated.columns


def test_memory_price_collector_filters_current_snapshot_to_requested_window(
    tmp_path, monkeypatch
) -> None:
    class Response:
        status_code = 200
        text = _trendforce_html()
        content = text.encode("utf-8")

    monkeypatch.setattr(MemoryPriceCollector, "_get", lambda self, url: Response())
    collector = MemoryPriceCollector(raw_dir=tmp_path / "raw")

    filtered = collector.collect_raw(
        start_date=date(2026, 9, 4),
        end_date=date(2026, 9, 4),
    )
    assert filtered.is_empty()

    in_window = collector.collect_raw(
        start_date=date(2026, 9, 3),
        end_date=date(2026, 9, 3),
    )
    assert in_window.height == 8


def _trendforce_html() -> str:
    return """
    <html>
      <body>
        <div>Last Update 2026-09-03 18:10 (GMT+8)</div>
        <h2>DRAM Spot Price</h2>
        <table>
          <tr>
            <th>Item</th><th>Daily High</th><th>Daily Low</th><th>Session High</th>
            <th>Session Low</th><th>Session Average</th><th>Session Change</th><th>History</th>
          </tr>
          <tr>
            <td>DDR4 8Gb 1Gx8 3200</td><td>2.100</td><td>1.900</td><td>2.050</td>
            <td>1.950</td><td>2.000</td><td>1.25%</td><td>History</td>
          </tr>
        </table>
        <h2>DRAM Contract Price (2H Jul)</h2>
        <table>
          <tr>
            <th>Item</th><th>High</th><th>Low</th><th>Average</th>
            <th>Average Change</th><th>Low Change</th><th>History</th>
          </tr>
          <tr>
            <td>DDR5 16Gb 2Gx8 5600</td><td>4.800</td><td>4.400</td><td>4.600</td>
            <td>-2.00%</td><td>0.00%</td><td>History</td>
          </tr>
        </table>
      </body>
    </html>
    """
