"""FuturesInventoryCollector 单元测试（纯本地 RAW，无东财在线源）。"""

from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.chemicals.collectors.inventory import (
    FuturesInventoryCollector,
    _missing_date_ranges,
)


def _write_local_sa(
    collector: FuturesInventoryCollector,
    rows: list[dict[str, object]],
) -> None:
    collector._save_symbol_raw_csv(
        "SA",
        {str(row["trade_date"]): row for row in rows},
    )


def _sa_row(
    trade_date: date,
    inventory: float,
    change: float,
    *,
    source: str = "Exchange_Official/CZCE",
    source_url: str = "https://www.czce.com.cn/",
    snapshot: str = "chemicals/futures_inventory/czce_daily/2026/20260828.xls",
) -> dict[str, object]:
    return {
        "symbol": "SA",
        "name": "纯碱",
        "industry_code": "220200",
        "trade_date": trade_date,
        "inventory": inventory,
        "change": change,
        "unit": "contracts",
        "source": source,
        "source_url": source_url,
        "release_date": trade_date,
        "collected_at": "2026-08-29T00:00:00Z",
        "raw_content_sha256": "sha-local",
        "raw_snapshot_path": snapshot,
    }


def test_futures_inventory_collector_reads_local_raw(tmp_path: Path) -> None:
    collector = FuturesInventoryCollector(raw_dir=tmp_path)
    _write_local_sa(
        collector,
        [
            _sa_row(date(2026, 8, 28), 8050.0, 357.0),
            _sa_row(date(2026, 8, 31), 7013.0, -1037.0),
        ],
    )

    df = collector.collect(symbols=["SA"])
    assert not df.is_empty()
    assert len(df) == 2
    assert "symbol" in df.columns
    assert "inventory" in df.columns
    assert "change" in df.columns
    assert df["symbol"][0] == "SA"
    assert df["inventory"][1] == 7013.0


def test_futures_inventory_project_raw() -> None:
    collector = FuturesInventoryCollector(raw_dir="data/raw/industry")
    sa_csv = collector.inv_dir / "SA.csv"
    if sa_csv.exists():
        records = collector._load_symbol_raw_csv("SA")
        assert len(records) > 0
        latest_d = max(records.keys())
        assert records[latest_d]["inventory"] is not None


def test_futures_inventory_checks_internal_gaps() -> None:
    missing = _missing_date_ranges(
        {date(2026, 8, 3), date(2026, 8, 5), date(2026, 8, 7)},
        date(2026, 8, 3),
        date(2026, 8, 7),
    )

    assert missing == (("2026-08-04", "2026-08-04"), ("2026-08-06", "2026-08-06"))


def test_futures_inventory_preserves_local_lineage(tmp_path: Path) -> None:
    collector = FuturesInventoryCollector(raw_dir=tmp_path)
    trade_date = date(2026, 8, 28)
    _write_local_sa(collector, [_sa_row(trade_date, 8050.0, 357.0)])

    frame = collector.collect(symbols=["SA"], start_date=trade_date, end_date=trade_date)

    assert frame["source"][0] == "Exchange_Official/CZCE"
    assert frame["raw_content_sha256"][0] == "sha-local"
    assert (
        frame["raw_snapshot_path"][0] == "chemicals/futures_inventory/czce_daily/2026/20260828.xls"
    )


def test_futures_inventory_result_reports_missing_range(tmp_path: Path) -> None:
    collector = FuturesInventoryCollector(raw_dir=tmp_path)
    result = collector.collect_result(
        symbols=["SA"],
        start_date=date(2026, 8, 28),
        end_date=date(2026, 8, 31),
    )

    assert result.status == "MISSING_RANGE"
    assert result.missing_periods


def test_futures_inventory_uses_exact_local_day_without_online(tmp_path: Path) -> None:
    collector = FuturesInventoryCollector(raw_dir=tmp_path)
    trade_date = date(2026, 8, 28)
    # 遗留东财快照行：仅当作本地历史 provenance 保留，不再触发任何在线拉取
    _write_local_sa(
        collector,
        [
            _sa_row(
                trade_date,
                8050.0,
                357.0,
                source="Eastmoney/CZCE",
                source_url="https://data.eastmoney.com/ifdata/kcsj.html",
                snapshot="chemicals/futures_inventory/SA_response.csv",
            )
        ],
    )

    result = collector.collect_result(
        symbols=["SA"],
        start_date=trade_date,
        end_date=trade_date,
    )

    assert result.status == "SUCCESS"
    assert result.cached_periods == ("SA:2026-08-28..2026-08-28",)
    assert not result.fetched_periods
