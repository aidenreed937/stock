"""化工期货官方在线/回放 RAW 回填与任务注册集成测试。"""

import hashlib
from datetime import date
from pathlib import Path

import openpyxl

from stock_data.core.industry_task_specs import INDUSTRY_TASK_SPECS
from stock_data.fetcher.industry.chemicals.collectors import (
    FuturesInventoryCollector,
    FuturesPriceCollector,
    official,
)

CZCE_DAILY_TEXT = """
\t\t\t\t\t郑州商品交易所期货每日行情表(2026-09-15)
合约代码|昨结算    |今开盘    |最高价    |最低价    |今收盘    |今结算    |涨跌1    |涨跌2    |成交量(手)|持仓量    |增减量    |成交额(万元)|交割结算价
SA701 |1,061.00  |1,063.00  |1,063.00  |1,014.00  |1,017.00  |1,035.00  |17.00    |31.00    |2,121,220 |1,594,499 |11,422  |2,240,997.54|
"""


def test_futures_price_online_backfill_writes_raw_csv_and_fetched_labels(
    tmp_path: Path, monkeypatch
) -> None:
    """enable_network 的 backfill_raw 只写 RAW CSV，并返回 (summary, fetched)。"""

    def fake_czce_download(trade_date: date, cache_dir: Path) -> str | None:
        if trade_date == date(2026, 9, 15):
            return CZCE_DAILY_TEXT
        return None

    monkeypatch.setattr(official, "download_czce_daily_text", fake_czce_download)
    monkeypatch.setattr(official, "download_dce_daily_text", lambda *_: None)

    collector = FuturesPriceCollector(raw_dir=tmp_path, enable_network=True)
    summary, fetched = collector.backfill_raw(
        start_date=date(2026, 9, 15),
        end_date=date(2026, 9, 15),
    )

    assert summary["SA"] == 1
    assert sum(summary.values()) == 1
    assert fetched == {"SA:2026-09-15"}

    csv_path = tmp_path / "chemicals" / "futures_daily" / "SA.csv"
    assert csv_path.exists()
    lines = csv_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2  # header + 1 row
    assert "SA,SA0,2026-09-15" in lines[1]
    assert "1035.00" in lines[1]


def test_download_czce_daily_text_writes_cache_and_reuses(tmp_path: Path, monkeypatch) -> None:
    """真实下载器写缓存；二次调用命中缓存，不再发起网络请求。"""
    fixture_content = (CZCE_DAILY_TEXT + "\n" + "#" * max(0, 1024 - len(CZCE_DAILY_TEXT))).encode(
        "utf-8"
    )

    class FakeResponse:
        status_code = 200
        content = fixture_content

    monkeypatch.setattr(official.requests, "get", lambda *_, **__: FakeResponse())
    cache_dir = tmp_path / "czce_daily_cache"

    first = official.download_czce_daily_text(date(2026, 9, 15), cache_dir)
    assert first is not None
    assert "郑州商品交易所期货每日行情表" in first
    cache_file = cache_dir / "2026" / "20260915.txt"
    assert cache_file.exists()

    def bomb(*_, **__):
        raise AssertionError("缓存已命中，不应再请求网络")

    monkeypatch.setattr(official.requests, "get", bomb)
    second = official.download_czce_daily_text(date(2026, 9, 15), cache_dir)
    assert second == first


def test_futures_price_collect_result_online_fetches_missing_window(
    tmp_path: Path, monkeypatch
) -> None:
    """collect_result 在线模式按请求窗口补拉后返回标准化治理状态。"""

    def fake_czce_download(trade_date: date, cache_dir: Path) -> str | None:
        if trade_date == date(2026, 9, 15):
            return CZCE_DAILY_TEXT
        return None

    monkeypatch.setattr(official, "download_czce_daily_text", fake_czce_download)
    monkeypatch.setattr(official, "download_dce_daily_text", lambda *_: None)

    collector = FuturesPriceCollector(raw_dir=tmp_path, enable_network=True)
    result = collector.collect_result(
        start_date=date(2026, 9, 15),
        end_date=date(2026, 9, 15),
    )

    assert result.status == "SUCCESS"
    assert result.fetched_periods == ("SA:2026-09-15",)
    assert not result.frame.is_empty()
    assert result.frame["close"][0] == 1017.0
    assert result.frame["settle"][0] == 1035.0


def _write_czce_inventory_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["郑商所仓单日报"])
    ws.append(["品种：纯碱"])
    ws.append(["", "仓单数量", "仓单数量(保税)", "当日增减"])
    ws.append(["总计", "1000", "200", "-50"])
    wb.save(path)


def test_inventory_replay_from_local_cache_writes_symbol_csvs(tmp_path: Path) -> None:
    """backfill_raw(download=False) 从本地 czce_daily 快照回放并合并 RAW CSV。"""
    fixture = tmp_path / "chemicals" / "futures_inventory" / "czce_daily" / "2026" / "20260915.xlsx"
    _write_czce_inventory_fixture(fixture)

    collector = FuturesInventoryCollector(raw_dir=tmp_path)
    summary, fetched = collector.backfill_raw(download=False)

    assert "SA" in summary
    assert summary["SA"] >= 1
    assert "SA:2026-09-15" in fetched

    csv_path = tmp_path / "chemicals" / "futures_inventory" / "SA.csv"
    assert csv_path.exists()
    lines = csv_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert "SA,纯碱" in lines[1]
    assert "1200.0" in lines[1]  # 1000 (仓单数量) + 200 (保税)
    assert "-50.0" in lines[1]

    expected_sha = hashlib.sha256(fixture.read_bytes()).hexdigest()
    assert expected_sha in lines[1]
    assert "czce_daily/2026/20260915.xlsx" in lines[1]


def test_chemical_futures_daily_task_spec_registered() -> None:
    spec = next(
        (item for item in INDUSTRY_TASK_SPECS if item["task"] == "chemical_futures_daily"),
        None,
    )
    assert spec is not None
    assert spec["frequency"] == "daily"
    assert spec["dataset"] == "futures_daily"
    assert spec["primary_keys"] == ("symbol", "contract", "trade_date")
    assert spec["units"]["close"] == "cny_per_ton"
    assert spec["units"]["volume"] == "lots"
