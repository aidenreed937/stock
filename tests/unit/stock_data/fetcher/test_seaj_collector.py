"""SEAJ 半导体设备采集器单元测试。"""

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import polars as pl

from stock_data.fetcher.industry.models import SemiconductorEquipmentRecord
from stock_data.fetcher.industry.semiconductor.collectors import seaj as seaj_module
from stock_data.fetcher.industry.semiconductor.collectors.seaj import (
    SEAJ_RELEASE_DATES_URL,
    SEAJ_STATISTICS_URL,
    SeajEquipmentCollector,
)
from stock_data.fetcher.industry.semiconductor.schemas import SEMICONDUCTOR_EQUIPMENT_RAW_SCHEMA
from stock_data.fetcher.industry.semiconductor.transforms import (
    records_to_raw_semiconductor_equipment_frame,
    records_to_semiconductor_equipment_frame,
)


def _sample_record() -> SemiconductorEquipmentRecord:
    return SemiconductorEquipmentRecord(
        report_month="2026-07",
        trade_date=date(2026, 7, 31),
        billings_3mma_jpy=556.22,
        yoy_growth_3mma=0.354,
        mom_growth_3mma=0.083,
        unit="billion_jpy",
        source="SEAJ",
        source_url="https://www.seaj.or.jp/statistics/",
        release_date=date(2026, 8, 21),
        data_status="actual",
        collected_at="2026-09-01T00:00:00Z",
        billings_jpy_raw="556,220",
        yoy_reported="35.4%",
        mom_reported="8.3%",
    )


def test_seaj_collector_rebuilds_from_online_raw_snapshots(tmp_path: Path, monkeypatch) -> None:
    index_html = (
        "<table>"
        "<tr><td>販売高速報値(3ヶ月平均) 半導体製造装置（日本製）2026年7月度</td>"
        '<td><a href="70971354181554.pdf">pdf</a></td><td>2026年8月21日</td></tr>'
        "<tr><td>販売高速報値(3ヶ月平均) 半導体</td>"
        '<td><a href="9097484030727.xls">xls</a></td></tr>'
        "</table>"
    ).encode("shift_jis")

    def on_get(url: str, **kwargs) -> MagicMock:
        response = MagicMock()
        response.status_code = 200
        if url == SEAJ_STATISTICS_URL:
            response.content = index_html
        elif url == SEAJ_RELEASE_DATES_URL:
            response.content = b"calendar"
        elif url.endswith(".xls"):
            response.content = b"xls"
        else:
            response.content = b"pdf"
        return response

    monkeypatch.setattr(
        seaj_module,
        "parse_seaj_historical_xls",
        lambda content, **kwargs: [
            {
                "report_month": "2026-06",
                "billings_3mma_jpy": 513.61,
                "yoy_growth_3mma": 0.269,
                "sales_3mma_raw": "513610.333333",
                "yoy_growth_3mma_raw": "0.269454",
            }
        ],
    )
    monkeypatch.setattr(
        seaj_module,
        "parse_seaj_release_calendar_pdf",
        lambda content: {
            "2026-06": date(2026, 7, 21),
            "2026-07": date(2026, 8, 21),
        },
    )
    collector = SeajEquipmentCollector(raw_dir=tmp_path / "raw")
    monkeypatch.setattr(
        collector.pdf_parser,
        "parse_pdf_bytes",
        lambda content, **kwargs: [
            {
                "report_month": "2026-07",
                "billings_3mma_jpy": 556.22,
                "mom_growth_3mma": 0.083,
                "yoy_growth_3mma": 0.354,
                "sales_3mma_raw": "556,220",
                "mom_growth_3mma_raw": "8.3%",
                "yoy_growth_3mma_raw": "35.4%",
                "release_date": date(2026, 8, 21),
            }
        ],
    )

    with patch(
        "stock_data.fetcher.industry.semiconductor.collectors.seaj.requests.get",
        side_effect=on_get,
    ):
        records = collector.collect()

    assert [record.report_month for record in records] == ["2026-06", "2026-07"]
    assert records[0].billings_3mma_jpy == 513.61
    assert records[0].mom_growth_3mma is None
    assert records[1].billings_3mma_jpy == 556.22
    assert records[1].release_date == date(2026, 8, 21)
    assert records[1].raw_content_sha256 == seaj_module.raw_content_sha256(b"pdf")
    assert records[1].raw_snapshot_path == "semiconductor/seaj/latest_press_release.pdf"

    raw = records_to_raw_semiconductor_equipment_frame(records)
    assert raw.columns == list(SEMICONDUCTOR_EQUIPMENT_RAW_SCHEMA)
    assert raw["sales_3mma_raw"].to_list() == ["513610.333333", "556,220"]
    assert raw["yoy_growth_3mma_raw"].to_list() == ["0.269454", "35.4%"]
    assert raw["mom_growth_3mma_raw"].to_list() == [None, "8.3%"]
    assert "billings_3mma_jpy" not in raw.columns

    curated = records_to_semiconductor_equipment_frame(records)
    assert curated["billings_3mma_jpy"].to_list() == [513.61, 556.22]
    assert curated["mom_growth_3mma"].to_list() == [None, 0.083]

    snapshot_dir = tmp_path / "raw" / "semiconductor" / "seaj"
    assert (snapshot_dir / seaj_module.SEAJ_INDEX_FILENAME).exists()
    assert (snapshot_dir / seaj_module.SEAJ_HISTORICAL_XLS_FILENAME).exists()
    assert (snapshot_dir / seaj_module.SEAJ_RELEASE_DATES_FILENAME).exists()
    assert (snapshot_dir / seaj_module.SEAJ_LATEST_PDF_FILENAME).exists()


def test_seaj_transform_frame() -> None:
    records = [_sample_record()]
    df = records_to_semiconductor_equipment_frame(records)
    assert not df.is_empty()
    assert "report_month" in df.columns
    assert "billings_3mma_jpy" in df.columns
    assert "yoy_growth" not in df.columns
    assert "release_date" in df.columns
    assert "raw_content_sha256" not in df.columns
    assert "raw_snapshot_path" not in df.columns
    assert df["billings_3mma_jpy"].is_not_null().any()


def test_seaj_incremental_transform_keeps_history_and_recomputes_mom() -> None:
    existing = records_to_semiconductor_equipment_frame(
        [
            SemiconductorEquipmentRecord("2026-07", date(2026, 7, 31), 100.0),
            SemiconductorEquipmentRecord("2026-08", date(2026, 8, 31), 110.0),
        ]
    )
    incremental = records_to_semiconductor_equipment_frame(
        [SemiconductorEquipmentRecord("2026-09", date(2026, 9, 30), 121.0)],
        existing_df=existing,
    )

    assert incremental.height == 3
    assert incremental.filter(pl.col("report_month") == "2026-09")["mom_growth_3mma"][0] == 0.1


def test_seaj_recent_window_skips_historical_excel(tmp_path: Path, monkeypatch) -> None:
    index_html = (
        "<table>"
        "<tr><td>販売高速報値(3ヶ月平均) 半導体製造装置（日本製）2026年7月度</td>"
        '<td><a href="latest.pdf">pdf</a></td><td>2026年8月21日</td></tr>'
        "<tr><td>販売高速報値(3ヶ月平均) 半導体</td>"
        '<td><a href="history.xls">xls</a></td></tr>'
        "</table>"
    ).encode("shift_jis")
    requested_urls: list[str] = []

    def on_get(url: str, **kwargs) -> MagicMock:
        requested_urls.append(url)
        response = MagicMock()
        response.status_code = 200
        if url == SEAJ_STATISTICS_URL:
            response.content = index_html
        elif url == SEAJ_RELEASE_DATES_URL:
            response.content = b"calendar"
        else:
            response.content = b"pdf"
        return response

    monkeypatch.setattr(
        seaj_module,
        "parse_seaj_release_calendar_pdf",
        lambda content: {"2026-07": date(2026, 8, 21)},
    )
    collector = SeajEquipmentCollector(raw_dir=tmp_path / "raw")
    monkeypatch.setattr(
        collector.pdf_parser,
        "parse_pdf_bytes",
        lambda content, **kwargs: [
            {
                "report_month": "2026-07",
                "billings_3mma_jpy": 556.22,
                "release_date": date(2026, 8, 21),
            }
        ],
    )

    with patch(
        "stock_data.fetcher.industry.semiconductor.collectors.seaj.requests.get",
        side_effect=on_get,
    ):
        records = collector.collect(
            start_date=date(2026, 7, 31),
            end_date=date(2026, 7, 31),
        )

    assert [record.report_month for record in records] == ["2026-07"]
    assert not any(url.endswith("history.xls") for url in requested_urls)
