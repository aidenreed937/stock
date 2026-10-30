"""测试 Avnet/Arrow 渠道库存端点。"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl

from stock_data.fetcher.industry.semiconductor.collectors.channel_inventory import (
    ChannelInventoryCollector,
)
from stock_data.fetcher.industry.semiconductor.parsers import parse_channel_inventory_companyfacts
from stock_data.fetcher.industry.semiconductor.schemas import (
    CHANNEL_INVENTORY_CURATED_SCHEMA,
    CHANNEL_INVENTORY_RAW_SCHEMA,
)
from stock_data.fetcher.industry.semiconductor.transforms import (
    build_channel_inventory_curated_frame,
    build_channel_inventory_raw_frame,
)
from stock_data.fetcher.industry.task_executor import execute_single_industry_task


def test_parse_channel_inventory_companyfacts_keeps_quarterly_source_fields() -> None:
    rows = parse_channel_inventory_companyfacts(
        _companyfacts_payload(
            inventory_value=5_722_706_000,
            cost_value=8_383_088_000,
            end="2026-04-04",
            start="2026-01-01",
            accn="0001104659-26-056650",
        ),
        company="Arrow Electronics",
        symbol="ARW",
        source_url="https://data.sec.gov/api/xbrl/companyfacts/CIK0000007536.json",
        collected_at="2026-09-04T00:00:00+00:00",
        raw_content_hash="sha-arw",
        raw_snapshot_path="semiconductor/sec_companyfacts/arw_companyfacts.json.gz",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["company"] == "Arrow Electronics"
    assert row["symbol"] == "ARW"
    assert row["report_quarter"] == "2026Q1"
    assert row["trade_date"] == date(2026, 4, 4)
    assert row["inventory_usd_raw"] == "5722706000"
    assert row["cost_of_revenue_usd_raw"] == "8383088000"
    assert row["release_date"] == date(2026, 5, 7)
    assert row["raw_content_sha256"] == "sha-arw"


def test_channel_inventory_curated_derives_doi_and_aggregate() -> None:
    raw = build_channel_inventory_raw_frame(
        [
            _raw_item(
                company="Arrow Electronics",
                symbol="ARW",
                inventory="5722706000",
                cost="8383088000",
            ),
            _raw_item(
                company="Avnet",
                symbol="AVT",
                inventory="5462394000",
                cost="6380718000",
            ),
        ]
    )

    assert raw.columns == list(CHANNEL_INVENTORY_RAW_SCHEMA)
    assert "inventory_usd_million" not in raw.columns
    assert raw["inventory_usd_raw"].to_list() == ["5722706000", "5462394000"]

    curated = build_channel_inventory_curated_frame(raw)
    assert curated.columns == list(CHANNEL_INVENTORY_CURATED_SCHEMA)
    arw = curated.filter(pl.col("symbol") == "ARW").to_dicts()[0]
    assert arw["inventory_usd_million"] == 5722.706
    assert arw["cost_of_revenue_usd_million"] == 8383.088
    assert arw["channel_doi_days"] == 61.4
    assert arw["channel_weighted_doi_days"] == 68.2
    assert "raw_content_sha256" not in curated.columns


def test_channel_inventory_endpoint_writes_raw_and_curated(tmp_path, monkeypatch) -> None:
    class Response:
        status_code = 200

        def __init__(self, payload: dict[str, Any]) -> None:
            self._payload = payload
            self.text = "{}"
            self.content = b"{}"

        def json(self) -> dict[str, Any]:
            return self._payload

    def fake_get(self, url: str) -> Response:
        if "0000007536" in url:
            return Response(
                _companyfacts_payload(
                    inventory_value=5_722_706_000,
                    cost_value=8_383_088_000,
                    end="2026-04-04",
                    start="2026-01-01",
                    accn="arw-q1",
                )
            )
        return Response(
            _companyfacts_payload(
                inventory_value=5_462_394_000,
                cost_value=6_380_718_000,
                end="2026-03-28",
                start="2025-12-28",
                accn="avt-q1",
            )
        )

    monkeypatch.setattr(ChannelInventoryCollector, "_get", fake_get)

    count = execute_single_industry_task(
        endpoint="semiconductor_channel_inventory",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 6, 30),
        raw_dir=tmp_path / "raw",
        curated_dir=tmp_path / "curated",
    )

    assert count == 2
    raw = pl.read_parquet(
        tmp_path / "raw" / "semiconductor" / "inventory" / "semiconductor_channel_inventory.parquet"
    )
    curated = pl.read_parquet(
        tmp_path
        / "curated"
        / "semiconductor"
        / "inventory"
        / "semiconductor_channel_inventory.parquet"
    )
    assert raw.columns == list(CHANNEL_INVENTORY_RAW_SCHEMA)
    assert curated.columns == list(CHANNEL_INVENTORY_CURATED_SCHEMA)
    assert "channel_doi_days" not in raw.columns
    assert "channel_doi_days" in curated.columns


def test_parse_channel_inventory_companyfacts_10k_q4_diff() -> None:
    """10-K 财年 Q4：CostOfRevenue 只有全年条目时，用差分法求单季 COGS。"""
    payload = {
        "facts": {
            "us-gaap": {
                "InventoryNet": {
                    "units": {
                        "USD": [
                            {
                                "end": "2024-12-31",
                                "val": 4_709_706_000,
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2025-02-11",
                                "frame": "CY2024Q4I",
                                "accn": "arw-10k-2024",
                            }
                        ]
                    }
                },
                "CostOfRevenue": {
                    "units": {
                        "USD": [
                            {
                                "start": "2024-01-01",
                                "end": "2024-12-31",
                                "val": 24_630_916_000,
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2025-02-11",
                                "accn": "arw-10k-2024",
                            },
                            {
                                "start": "2024-01-01",
                                "end": "2024-03-30",
                                "val": 6_066_434_000,
                                "fy": 2024,
                                "fp": "Q1",
                                "form": "10-Q",
                                "filed": "2024-05-02",
                                "accn": "arw-q1",
                            },
                            {
                                "start": "2024-04-01",
                                "end": "2024-06-29",
                                "val": 6_046_424_000,
                                "fy": 2024,
                                "fp": "Q2",
                                "form": "10-Q",
                                "filed": "2024-08-01",
                                "accn": "arw-q2",
                            },
                            {
                                "start": "2024-07-01",
                                "end": "2024-09-28",
                                "val": 6_038_491_000,
                                "fy": 2024,
                                "fp": "Q3",
                                "form": "10-Q",
                                "filed": "2024-10-31",
                                "accn": "arw-q3",
                            },
                        ]
                    }
                },
            }
        }
    }
    rows = parse_channel_inventory_companyfacts(
        payload,
        company="Arrow Electronics",
        symbol="ARW",
        source_url="https://data.sec.gov/api/xbrl/companyfacts/CIK0000007536.json",
        collected_at="2026-09-04T00:00:00+00:00",
        raw_content_hash="sha-arw",
        raw_snapshot_path="semiconductor/sec_companyfacts/arw_companyfacts.json.gz",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["report_quarter"] == "2024Q4"
    assert row["form_raw"] == "10-K"
    assert row["trade_date"] == date(2024, 12, 31)
    assert row["release_date"] == date(2025, 2, 11)
    # Q4 = FY − (Q1+Q2+Q3) = 24,630,916,000 − 18,151,349,000
    assert row["cost_of_revenue_usd_raw"] == "6479567000"


def test_parse_channel_inventory_companyfacts_keeps_earliest_disclosure() -> None:
    """同一财年 Q4 被后续文件重述时，黄金表保留首次披露版本（最早 release_date）。"""

    def _k(inv_end: str, filed: str) -> dict[str, Any]:
        return {
            "end": inv_end,
            "val": 4_709_706_000,
            "fy": 2024,
            "fp": "FY",
            "form": "10-K",
            "filed": filed,
            "accn": f"arw-{filed}",
        }

    payload = {
        "facts": {
            "us-gaap": {
                "InventoryNet": {
                    "units": {
                        "USD": [_k("2024-12-31", "2025-02-11"), _k("2024-12-31", "2026-02-11")]
                    }
                },
                "CostOfRevenue": {
                    "units": {
                        "USD": [
                            {
                                "start": "2024-01-01",
                                "end": "2024-12-31",
                                "val": 24_630_916_000,
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2025-02-11",
                                "accn": "arw-2025-02-11",
                            },
                            {
                                "start": "2024-01-01",
                                "end": "2024-03-30",
                                "val": 6_066_434_000,
                                "fy": 2024,
                                "fp": "Q1",
                                "form": "10-Q",
                                "filed": "2024-05-02",
                                "accn": "arw-q1",
                            },
                            {
                                "start": "2024-04-01",
                                "end": "2024-06-29",
                                "val": 6_046_424_000,
                                "fy": 2024,
                                "fp": "Q2",
                                "form": "10-Q",
                                "filed": "2024-08-01",
                                "accn": "arw-q2",
                            },
                            {
                                "start": "2024-07-01",
                                "end": "2024-09-28",
                                "val": 6_038_491_000,
                                "fy": 2024,
                                "fp": "Q3",
                                "form": "10-Q",
                                "filed": "2024-10-31",
                                "accn": "arw-q3",
                            },
                        ]
                    }
                },
            }
        }
    }
    rows = parse_channel_inventory_companyfacts(
        payload,
        company="Arrow Electronics",
        symbol="ARW",
        source_url="https://data.sec.gov/api/xbrl/companyfacts/CIK0000007536.json",
        collected_at="2026-09-04T00:00:00+00:00",
        raw_content_hash="sha-arw",
        raw_snapshot_path="semiconductor/sec_companyfacts/arw_companyfacts.json.gz",
    )
    assert len(rows) == 1
    assert rows[0]["release_date"] == date(2025, 2, 11)


def _companyfacts_payload(
    *,
    inventory_value: int,
    cost_value: int,
    end: str,
    start: str,
    accn: str,
) -> dict[str, Any]:
    return {
        "facts": {
            "us-gaap": {
                "InventoryNet": {
                    "units": {
                        "USD": [
                            {
                                "end": end,
                                "val": inventory_value,
                                "fy": 2026,
                                "fp": "Q1",
                                "form": "10-Q",
                                "filed": "2026-05-07",
                                "frame": "CY2026Q1I",
                                "accn": accn,
                            }
                        ]
                    }
                },
                "CostOfRevenue": {
                    "units": {
                        "USD": [
                            {
                                "start": "2026-01-01",
                                "end": end,
                                "val": cost_value + 1_000,
                                "fy": 2026,
                                "fp": "Q2",
                                "form": "10-Q",
                                "filed": "2026-08-06",
                                "accn": "ignored-ytd",
                            },
                            {
                                "start": start,
                                "end": end,
                                "val": cost_value,
                                "fy": 2026,
                                "fp": "Q1",
                                "form": "10-Q",
                                "filed": "2026-05-07",
                                "frame": "CY2026Q1",
                                "accn": accn,
                            },
                        ]
                    }
                },
            }
        }
    }


def _raw_item(
    *,
    company: str,
    symbol: str,
    inventory: str,
    cost: str,
) -> dict[str, Any]:
    return {
        "company": company,
        "symbol": symbol,
        "report_quarter": "2026Q1",
        "trade_date": date(2026, 3, 31),
        "fiscal_year_raw": "2026",
        "fiscal_period_raw": "Q1",
        "inventory_usd_raw": inventory,
        "cost_of_revenue_usd_raw": cost,
        "form_raw": "10-Q",
        "accession_raw": f"{symbol.lower()}-q1",
        "source": "SEC_companyfacts",
        "source_url": "https://data.sec.gov/api/xbrl/companyfacts/test.json",
        "release_date": date(2026, 5, 7),
        "data_status": "actual",
        "collected_at": "2026-09-04T00:00:00+00:00",
        "raw_content_sha256": f"sha-{symbol.lower()}",
        "raw_snapshot_path": f"semiconductor/sec_companyfacts/{symbol.lower()}.json.gz",
    }
