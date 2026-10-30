"""韩国双雄 DART 发现、解析和幂等合并的离线回归测试。"""

import csv
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.semiconductor.collectors.korea_memory_dart import (
    KoreaMemoryDartCollector,
    _discovery_windows,
    _merge_korea_raw_rows,
    _normalize_samsung_manifest_rows,
)
from stock_data.fetcher.industry.semiconductor.parsers.korea_memory_dart import (
    DartReport,
    parse_samsung_inventory_html,
    parse_samsung_segment_html,
    parse_skhynix_financial_html,
    select_latest_dart_revisions,
)

ROOT = Path("data/raw/industry/semiconductor/korea_filings")


def test_samsung_old_and_new_inventory_scopes_parse_from_dart_html() -> None:
    legacy = parse_samsung_inventory_html(
        (ROOT / "samsung_electronics_2020_business_report_inventory_by_division.html").read_bytes()
    )
    current = parse_samsung_inventory_html(
        (ROOT / "samsung_electronics_2026_2Q_interim_inventory_by_division.html").read_bytes()
    )

    assert legacy.inventory_krw_million == 13_906_811
    assert legacy.group_inventory_krw_million == 32_043_145
    assert legacy.inventory_scope == "legacy_semiconductor_business"
    assert current.inventory_krw_million == 38_056_737
    assert current.group_inventory_krw_million == 71_389_118
    assert current.inventory_scope == "ds_division"


def test_samsung_segment_parser_keeps_reported_unit() -> None:
    fact = parse_samsung_segment_html(
        (ROOT / "samsung_electronics_2026_2Q_business_segment_summary.html").read_bytes()
    )

    assert fact.ds_revenue_krw_million == 209_231_700
    assert fact.ds_operating_profit_krw_million == 142_859_300
    assert fact.reported_unit == "hundred_million_krw"


def test_skhynix_parser_reads_consolidated_inventory_and_cost() -> None:
    fact = parse_skhynix_financial_html(
        (ROOT / "sk_hynix_dart_2026_2Q_consolidated_financial_statements.html").read_bytes()
    )

    assert fact.inventory_krw_million == 17_985_706
    assert fact.cost_of_revenue_quarter_krw_million == 13_327_390
    assert fact.cost_of_revenue_cumulative_krw_million == 24_224_263


def test_dart_revision_selection_uses_latest_filing_date_then_rcp_no() -> None:
    reports = [
        DartReport("samsung", "2026Q1", "quarterly_report", date(2026, 5, 15), "1000000001"),
        DartReport("samsung", "2026Q1", "quarterly_report", date(2026, 5, 20), "1000000002"),
        DartReport("samsung", "2026Q2", "half_year_report", date(2026, 8, 14), "1000000003"),
    ]

    selected = select_latest_dart_revisions(reports, target_quarters={"2026Q1"})

    assert selected["2026Q1"].rcp_no == "1000000002"


def test_dart_discovery_windows_are_bounded_and_contiguous() -> None:
    windows = _discovery_windows(date(2016, 1, 1), date(2026, 9, 11))

    assert len(windows) == 2
    assert windows[0][0] == date(2016, 1, 1)
    assert windows[-1][1] == date(2026, 9, 11)
    assert all((end - start).days <= 365 * 9 for start, end in windows)
    assert windows[0][1].toordinal() + 1 == windows[1][0].toordinal()


def test_samsung_manifest_normalizes_legacy_interim_duplicates() -> None:
    rows = [
        {
            "report_quarter": "2021Q1",
            "report_type": "interim_report",
            "local_snapshot_path": "inventory_by_division.html",
        },
        {
            "report_quarter": "2021Q1",
            "report_type": "quarterly_report",
            "local_snapshot_path": "inventory_by_division.html",
        },
        {
            "report_quarter": "2021Q1",
            "report_type": "interim_report_segment_summary",
            "local_snapshot_path": "segment_summary.html",
        },
    ]

    normalized = _normalize_samsung_manifest_rows(rows)

    assert [row["report_type"] for row in normalized] == [
        "quarterly_report",
        "quarterly_report_segment_summary",
    ]


def test_korea_raw_merge_is_idempotent_ignoring_collected_at(tmp_path: Path) -> None:
    path = tmp_path / "korea_memory_raw.csv"
    row = {
        "symbol": "000660.KS",
        "report_quarter": "2026Q2",
        "trade_date": "2026-06-30",
        "inventory_krw": "17985.706",
        "cost_of_revenue_krw": "13327.390",
        "collected_at": "2026-09-10T00:00:00Z",
    }
    changed_first = _merge_korea_raw_rows(path, [row])
    changed_second = _merge_korea_raw_rows(
        path,
        [{**row, "collected_at": "2026-09-10T01:00:00Z"}],
    )

    assert changed_first == 1
    assert changed_second == 0
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["report_quarter"] == "2026Q2"


def test_collector_reuses_one_session_for_dart_requests(tmp_path: Path) -> None:
    collector = KoreaMemoryDartCollector(tmp_path)

    first = collector._get_session()
    second = collector._get_session()

    assert first is second
