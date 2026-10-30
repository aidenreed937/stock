import csv
import gzip
from datetime import date

import polars as pl

from stock_data.fetcher.industry.semiconductor.collectors.equipment_gm import (
    AmatEquipmentGmCollector,
)
from stock_data.fetcher.industry.semiconductor.schemas import EQUIPMENT_GM_ATOMIC_SCHEMA


def test_sec_equipment_collector_seeds_manifest_and_skips_known_accession(
    tmp_path, monkeypatch
) -> None:
    raw_root = tmp_path / "raw" / "industry"
    collector = AmatEquipmentGmCollector(raw_root)
    raw_dir = raw_root / "semiconductor" / "equipment" / "sec_edgar" / "AMAT"
    raw_dir.mkdir(parents=True)
    existing = raw_dir / "AMAT__2026-08-13__000000000000000001__old.htm.gz"
    with gzip.open(existing, "wb") as handle:
        handle.write(b"old filing")

    monkeypatch.setattr(
        collector,
        "_list_recent_filings",
        lambda cursor: [
            {
                "form": "8-K",
                "filing_date": "2026-09-01",
                "accession": "0000000000-00-000002",
                "primary_document": "amat.htm",
            }
        ],
    )
    monkeypatch.setattr(
        collector,
        "_get_json",
        lambda url: {"directory": {"item": [{"name": "exhibit991earningsrelease.htm"}]}},
    )
    monkeypatch.setattr(
        collector,
        "_get_bytes",
        lambda url: b"revenue gross margin " * 400,
    )
    monkeypatch.setattr(
        collector,
        "_parse_frame",
        lambda: pl.DataFrame(schema=EQUIPMENT_GM_ATOMIC_SCHEMA),
    )

    collector.collect_raw(start_date=date(2026, 7, 1), end_date=date(2026, 9, 30))
    manifest_path = raw_dir / "manifest.csv"
    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert {row["status"] for row in rows} == {"seeded", "success"}
    assert any("000000000000000002" in row["accession"] for row in rows)
    downloaded = raw_dir / (
        "AMAT__2026-09-01__000000000000000002__exhibit991earningsrelease.htm.gz"
    )
    assert downloaded.exists()

    collector_again = AmatEquipmentGmCollector(raw_root)
    monkeypatch.setattr(
        collector_again,
        "_list_recent_filings",
        lambda cursor: [
            {
                "form": "8-K",
                "filing_date": "2026-09-01",
                "accession": "0000000000-00-000002",
                "primary_document": "amat.htm",
            }
        ],
    )
    monkeypatch.setattr(
        collector_again, "_parse_frame", lambda: pl.DataFrame(schema=EQUIPMENT_GM_ATOMIC_SCHEMA)
    )
    get_bytes_calls: list[str] = []
    monkeypatch.setattr(
        collector_again, "_get_bytes", lambda url: get_bytes_calls.append(url) or b""
    )
    collector_again.collect_raw(start_date=date(2026, 7, 1), end_date=date(2026, 9, 30))
    assert get_bytes_calls == []
