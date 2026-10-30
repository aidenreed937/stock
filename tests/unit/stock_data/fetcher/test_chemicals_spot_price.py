"""基础化工 100ppi 现货出厂基准价采集与转换单元测试。"""

from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path

import polars as pl
import pytest

import stock_data.fetcher.industry.chemicals.collectors.spot_price as spot_price_module
from stock_data.fetcher.industry.chemicals.collectors.spot_price import (
    COMMODITY_CATALOG,
    STATUS_FALLBACK,
    STATUS_ONLINE,
    STATUS_REJECTED,
    ChemicalSpotPriceCollector,
    load_all_spot_price_snapshots,
    parse_100ppi_chart_text,
)
from stock_data.fetcher.industry.chemicals.models import ChemicalSpotPriceRecord
from stock_data.fetcher.industry.chemicals.quality import validate_spot_price_records
from stock_data.fetcher.industry.chemicals.schemas import (
    CHEMICAL_SPOT_PRICE_RAW_SCHEMA,
    CHEMICAL_SPOT_PRICE_SCHEMA,
)
from stock_data.fetcher.industry.chemicals.transforms.spot_price import (
    build_spot_price_curated_frame,
    build_spot_price_raw_frame,
)


def test_parse_100ppi_chart_text_success() -> None:
    sample_js = """
    var option = {
        xAxis: {
            type: 'category',
            data: ['2026-09-14', '2026-09-15', '2026-09-16']
        },
        series: [{
            name: '价格',
            type: 'line',
            data: [1050.00, 1050.00, 1060.00,]
        }]
    };
    """
    records = parse_100ppi_chart_text(sample_js, symbol="SA_light")
    assert len(records) == 3
    assert records[0].product_name == "轻质纯碱"
    assert records[0].symbol == "SA_light"
    assert records[0].trade_date == date(2026, 9, 14)
    assert records[0].spot_price_cny == 1050.0
    assert records[2].trade_date == date(2026, 9, 16)
    assert records[2].spot_price_cny == 1060.0
    assert records[0].source == "100ppi"
    assert records[0].data_status == "spot_benchmark"


def test_parse_100ppi_chart_text_empty_or_malformed() -> None:
    assert parse_100ppi_chart_text("", symbol="SA") == []
    assert parse_100ppi_chart_text("var foo = 'bar';", symbol="SA") == []
    assert parse_100ppi_chart_text("xAxis: { data: 'invalid' }", symbol="SA") == []


def test_transforms_spot_price_frames() -> None:
    df_raw = build_spot_price_raw_frame(pl.DataFrame())
    assert set(df_raw.columns) == set(CHEMICAL_SPOT_PRICE_RAW_SCHEMA.keys())
    assert len(df_raw) == 0

    df_curated = build_spot_price_curated_frame(pl.DataFrame())
    assert set(df_curated.columns) == set(CHEMICAL_SPOT_PRICE_SCHEMA.keys())
    assert len(df_curated) == 0

    # 包含源值文本与重复项的 DataFrame
    sample = pl.DataFrame(
        {
            "symbol": ["SA", "SA"],
            "trade_date": [date(2026, 9, 15), date(2026, 9, 15)],
            "product_name": ["重质纯碱", "重质纯碱"],
            "spot_price_cny": [1080.0, 1090.0],
            "spec": ["优等品", "优等品"],
            "region": ["国内", "国内"],
            "unit": ["元/吨", "元/吨"],
            "source": ["100ppi", "100ppi"],
            "source_url": ["http://test", "http://test"],
            "release_date": [date(2026, 9, 15), date(2026, 9, 15)],
            "data_status": ["spot_benchmark", "spot_benchmark"],
            "collected_at": ["2026-09-16T00:00:00Z", "2026-09-16T00:00:00Z"],
        }
    )
    curated = build_spot_price_curated_frame(sample)
    assert len(curated) == 1
    assert curated["spot_price_cny"][0] == 1090.0


def test_collector_offline_raw_snapshot_and_materialize(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    curated_dir = tmp_path / "curated"

    collector = ChemicalSpotPriceCollector(raw_dir=raw_dir, curated_dir=curated_dir)
    ppi_dir = collector.ppi_dir

    # 构造虚构 RAW 快照
    fake_snapshot = {
        "symbol": "SA",
        "product_name": "重质纯碱",
        "ppid": 737,
        "spec": "99.20% min;优等品",
        "region": "国内",
        "unit": "元/吨",
        "source": "100ppi",
        "source_url": "https://www.100ppi.com/test",
        "collected_at": "2026-09-16T00:00:00Z",
        "count": 2,
        "dates": ["2026-09-14", "2026-09-15"],
        "prices": [1085.0, 1090.0],
    }
    (ppi_dir / "SA.json").write_text(json.dumps(fake_snapshot), encoding="utf-8")

    # 离线模式读取
    records = collector.collect_symbol("SA", use_network=False)
    assert len(records) == 2
    assert collector.collection_status["SA"] == STATUS_FALLBACK
    assert records[0].trade_date == date(2026, 9, 14)
    assert records[0].spot_price_cny == 1085.0
    assert records[1].spot_price_cny == 1090.0

    # 物化 Curated Parquet
    curated_df = collector.materialize_curated({"SA": records})
    assert len(curated_df) == 2
    out_file = curated_dir / "chemical_spot_price.parquet"
    assert out_file.exists()
    loaded = pl.read_parquet(out_file)
    assert len(loaded) == 2
    assert loaded["symbol"][0] == "SA"


def test_collector_online_success_updates_snapshot_and_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_dir = tmp_path / "raw"
    curated_dir = tmp_path / "curated"
    collector = ChemicalSpotPriceCollector(raw_dir=raw_dir, curated_dir=curated_dir)
    monkeypatch.setattr(
        collector,
        "fetch_via_browser",
        lambda ppid: {
            "dates": ["2026-09-14", "2026-09-15"],
            "prices": [1085.0, 1090.0],
        },
    )

    records = collector.collect_symbol("SA", use_network=True)

    assert len(records) == 2
    assert collector.collection_status["SA"] == STATUS_ONLINE
    snapshot = json.loads((collector.ppi_dir / "SA.json").read_text(encoding="utf-8"))
    assert snapshot["end_date"] == "2026-09-15"
    assert snapshot["prices"] == [1085.0, 1090.0]


def test_collector_partial_result_does_not_overwrite_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_dir = tmp_path / "raw"
    curated_dir = tmp_path / "curated"
    collector = ChemicalSpotPriceCollector(raw_dir=raw_dir, curated_dir=curated_dir)
    snapshot_path = _write_fake_snapshot(collector)

    monkeypatch.setattr(
        collector,
        "fetch_via_browser",
        lambda ppid: {"dates": ["2026-09-16"], "prices": []},
    )
    before = snapshot_path.read_bytes()

    records = collector.collect_symbol("SA", use_network=True)

    assert len(records) == 2
    assert snapshot_path.read_bytes() == before
    assert collector.collection_status["SA"] == STATUS_REJECTED


def test_collector_length_mismatch_does_not_overwrite_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_dir = tmp_path / "raw"
    curated_dir = tmp_path / "curated"
    collector = ChemicalSpotPriceCollector(raw_dir=raw_dir, curated_dir=curated_dir)
    snapshot_path = _write_fake_snapshot(collector)

    monkeypatch.setattr(
        collector,
        "fetch_via_browser",
        lambda ppid: {
            "dates": ["2026-09-15", "2026-09-16"],
            "prices": [1090.0],
        },
    )
    before = snapshot_path.read_bytes()

    records = collector.collect_symbol("SA", use_network=True)

    assert len(records) == 2
    assert snapshot_path.read_bytes() == before
    assert collector.collection_status["SA"] == STATUS_REJECTED


@pytest.mark.parametrize("fetch_result", [None, {"error": "no eval", "status": 200}])
def test_collector_fetch_error_falls_back_with_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fetch_result: dict[str, object] | None,
) -> None:
    raw_dir = tmp_path / "raw"
    curated_dir = tmp_path / "curated"
    collector = ChemicalSpotPriceCollector(raw_dir=raw_dir, curated_dir=curated_dir)
    snapshot_path = _write_fake_snapshot(collector)

    monkeypatch.setattr(collector, "fetch_via_browser", lambda ppid: fetch_result)
    before = snapshot_path.read_bytes()

    records = collector.collect_symbol("SA", use_network=True)

    assert len(records) == 2
    assert snapshot_path.read_bytes() == before
    assert collector.collection_status["SA"] == STATUS_FALLBACK


def test_save_raw_snapshot_leaves_no_temp_file(tmp_path: Path) -> None:
    collector = ChemicalSpotPriceCollector(
        raw_dir=tmp_path / "raw",
        curated_dir=tmp_path / "curated",
    )

    collector.save_raw_snapshot(
        "SA",
        ["2026-09-14", "2026-09-15"],
        [1085.0, 1090.0],
        COMMODITY_CATALOG["SA"],
    )

    assert (collector.ppi_dir / "SA.json").exists()
    assert list(collector.ppi_dir.glob(".*.json.tmp")) == []


def test_collect_all_populates_collection_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector = ChemicalSpotPriceCollector(
        raw_dir=tmp_path / "raw",
        curated_dir=tmp_path / "curated",
    )
    monkeypatch.setattr(
        collector,
        "fetch_via_browser",
        lambda ppid: {"dates": ["2026-09-14"], "prices": [1085.0]},
    )

    result = collector.collect_all(symbols=["SA", "UR"], use_network=True)

    assert len(result["SA"]) == 1
    assert len(result["UR"]) == 1
    assert collector.collection_status == {"SA": STATUS_ONLINE, "UR": STATUS_ONLINE}


def _write_fake_snapshot(collector: ChemicalSpotPriceCollector) -> Path:
    """向 collector 的 100ppi 目录写入一条可回放的 SA 快照。"""
    fake_snapshot = {
        "symbol": "SA",
        "product_name": "重质纯碱",
        "ppid": 737,
        "spec": "99.20% min;优等品",
        "region": "国内",
        "unit": "元/吨",
        "source": "100ppi",
        "source_url": "https://www.100ppi.com/test",
        "collected_at": "2026-09-16T00:00:00Z",
        "count": 2,
        "dates": ["2026-09-14", "2026-09-15"],
        "prices": [1085.0, 1090.0],
    }
    snapshot_path = collector.ppi_dir / "SA.json"
    snapshot_path.write_text(json.dumps(fake_snapshot), encoding="utf-8")
    return snapshot_path


def test_parse_100ppi_chart_text_unpacks_packer() -> None:
    packed_js = (
        "var page = 1;"
        "eval(function(p,a,c,k,e,d){return 1}"
        "('0:{2:[\\'3\\',\\'4\\',\\'5\\']},1:[{2:[6,7,6]}]',62,8,"
        "'xAxis|series|data|2026-09-14|2026-09-15|2026-09-16|1050|1060'.split('|'),0,{}))"
        ";var tail = 2;"
    )

    records = parse_100ppi_chart_text(packed_js, symbol="SA")

    assert len(records) == 3
    assert records[0].trade_date == date(2026, 9, 14)
    assert records[0].spot_price_cny == 1050.0
    assert records[1].spot_price_cny == 1060.0
    assert records[2].trade_date == date(2026, 9, 16)
    assert records[2].spot_price_cny == 1050.0


def test_parse_100ppi_chart_text_malformed_packer_returns_empty() -> None:
    # count 与字典长度不一致，应原样返回且解析不到数组
    malformed = (
        "eval(function(p,a,c,k,e,d){return 1}('0:{2:[\\'3\\']}',62,2,'xAxis|data'.split('|'),0,{}))"
    )
    assert parse_100ppi_chart_text(malformed, symbol="SA") == []

    # 合法 packer 但解包后不含 xAxis/series
    no_chart = (
        "eval(function(p,a,c,k,e,d){return 1}('0(\\'1\\');',2,2,'alert|test'.split('|'),0,{}))"
    )
    assert parse_100ppi_chart_text(no_chart, symbol="SA") == []


def test_fetch_via_browser_parses_stdout_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collector = ChemicalSpotPriceCollector(
        raw_dir=tmp_path / "raw",
        curated_dir=tmp_path / "curated",
    )
    expected = {"dates": ["2026-09-14", "2026-09-15"], "prices": [1085.0, 1090.0]}

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[-1] == "location.origin":
            return subprocess.CompletedProcess(cmd, 0, stdout='"https://www.100ppi.com"', stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(expected), stderr="")

    monkeypatch.setattr(spot_price_module.subprocess, "run", fake_run)

    assert collector.fetch_via_browser(737) == expected


def test_fetch_via_browser_nonzero_exit_returns_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector = ChemicalSpotPriceCollector(
        raw_dir=tmp_path / "raw",
        curated_dir=tmp_path / "curated",
    )

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[-1] == "location.origin":
            return subprocess.CompletedProcess(cmd, 0, stdout='"https://www.100ppi.com"', stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

    monkeypatch.setattr(spot_price_module.subprocess, "run", fake_run)

    assert collector.fetch_via_browser(737) is None


def test_fetch_via_browser_invalid_stdout_returns_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector = ChemicalSpotPriceCollector(
        raw_dir=tmp_path / "raw",
        curated_dir=tmp_path / "curated",
    )

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[-1] == "location.origin":
            return subprocess.CompletedProcess(cmd, 0, stdout='"https://www.100ppi.com"', stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="not-json", stderr="")

    monkeypatch.setattr(spot_price_module.subprocess, "run", fake_run)

    assert collector.fetch_via_browser(737) is None


def test_ensure_browser_session_opens_homepage_when_off_domain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector = ChemicalSpotPriceCollector(
        raw_dir=tmp_path / "raw",
        curated_dir=tmp_path / "curated",
    )
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if len(calls) == 1:
            return subprocess.CompletedProcess(cmd, 0, stdout='"https://example.com"', stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(spot_price_module.subprocess, "run", fake_run)

    assert collector.ensure_browser_session() is True
    assert any("open" in cmd for cmd in calls)


def test_parse_100ppi_chart_text_weekend_release_date() -> None:
    """周末的 chart 点位，release_date 应回退到最近工作日（周五）。"""
    sample_js = """
    var option = {
        xAxis: {
            type: 'category',
            data: ['2026-09-18', '2026-09-19', '2026-09-20']
        },
        series: [{
            name: '价格',
            type: 'line',
            data: [1050.00, 1050.00, 1060.00,]
        }]
    };
    """
    records = parse_100ppi_chart_text(sample_js, symbol="SA")

    assert records[0].release_date == date(2026, 9, 18)
    assert records[1].release_date == date(2026, 9, 18)
    assert records[2].release_date == date(2026, 9, 18)


def test_load_from_raw_snapshot_weekend_release_date(tmp_path: Path) -> None:
    collector = ChemicalSpotPriceCollector(
        raw_dir=tmp_path / "raw",
        curated_dir=tmp_path / "curated",
    )
    fake_snapshot = {
        "symbol": "SA",
        "product_name": "重质纯碱",
        "ppid": 737,
        "spec": "99.20% min;优等品",
        "region": "国内",
        "unit": "元/吨",
        "source": "100ppi",
        "source_url": "https://www.100ppi.com/test",
        "collected_at": "2026-09-16T00:00:00Z",
        "count": 2,
        "dates": ["2026-09-19", "2026-09-20"],
        "prices": [1085.0, 1085.0],
    }
    (collector.ppi_dir / "SA.json").write_text(json.dumps(fake_snapshot), encoding="utf-8")

    records = collector.load_from_raw_snapshot("SA")

    assert records[0].release_date == date(2026, 9, 18)
    assert records[1].release_date == date(2026, 9, 18)


def test_collect_result_and_load_all_snapshots(tmp_path: Path) -> None:
    collector = ChemicalSpotPriceCollector(
        raw_dir=tmp_path / "raw",
        curated_dir=tmp_path / "curated",
    )
    collector.save_raw_snapshot(
        "SA",
        ["2026-09-14", "2026-09-15"],
        [1085.0, 1090.0],
        COMMODITY_CATALOG["SA"],
    )
    collector.save_raw_snapshot(
        "UR",
        ["2026-09-14"],
        [1800.0],
        COMMODITY_CATALOG["UR"],
    )

    all_records = load_all_spot_price_snapshots(collector.ppi_dir, ["SA", "UR"])
    assert len(all_records) == 3
    assert {record.symbol for record in all_records} == {"SA", "UR"}

    flat = collector.collect_result(symbols=["SA", "UR"], use_network=False)
    assert len(flat) == 3
    assert collector.collection_status["SA"] == STATUS_FALLBACK


def test_materialize_curated_filters_invalid_records(tmp_path: Path) -> None:
    collector = ChemicalSpotPriceCollector(
        raw_dir=tmp_path / "raw",
        curated_dir=tmp_path / "curated",
    )
    good = ChemicalSpotPriceRecord(
        product_name="重质纯碱",
        symbol="SA",
        trade_date=date(2026, 9, 15),
        spot_price_cny=1085.0,
        source="100ppi",
        release_date=date(2026, 9, 15),
    )
    bad_negative = ChemicalSpotPriceRecord(
        product_name="重质纯碱",
        symbol="SA",
        trade_date=date(2026, 9, 16),
        spot_price_cny=-1.0,
        source="100ppi",
        release_date=date(2026, 9, 16),
    )

    curated = collector.materialize_curated({"SA": [good, bad_negative]})

    assert len(curated) == 1
    assert curated["spot_price_cny"][0] == 1085.0


def test_validate_spot_price_records_rejects_invalid_entries() -> None:
    good = ChemicalSpotPriceRecord(
        product_name="重质纯碱",
        symbol="SA",
        trade_date=date(2026, 9, 15),
        spot_price_cny=1085.0,
        source="100ppi",
        release_date=date(2026, 9, 15),
    )
    duplicate = ChemicalSpotPriceRecord(
        product_name="重质纯碱",
        symbol="SA",
        trade_date=date(2026, 9, 15),
        spot_price_cny=1086.0,
        source="100ppi",
        release_date=date(2026, 9, 15),
    )
    negative = ChemicalSpotPriceRecord(
        product_name="重质纯碱",
        symbol="SA",
        trade_date=date(2026, 9, 16),
        spot_price_cny=-1.0,
        source="100ppi",
        release_date=date(2026, 9, 16),
    )

    valid, errors = validate_spot_price_records([good, duplicate, negative])

    assert len(valid) == 1
    assert valid[0] is good
    assert any("重复" in message for message in errors)
    assert any("非负数" in message for message in errors)


def test_tio2_feedstocks_catalog_and_snapshot_replay(tmp_path: Path) -> None:
    """验证 100ppi 现货目录管理：公开日度品种与关键酸类原料已纳管，非标矿产原料由产业调查专职承接。"""
    # 1. 核心大宗成品及关键酸类原料在目录中
    assert "TiO2" in COMMODITY_CATALOG
    assert COMMODITY_CATALOG["TiO2"]["ppid"] == 645
    assert COMMODITY_CATALOG["TiO2"]["product_name"] == "钛白粉"
    assert "H2SO4" in COMMODITY_CATALOG
    assert COMMODITY_CATALOG["H2SO4"]["ppid"] == 236
    assert COMMODITY_CATALOG["H2SO4"]["product_name"] == "硫酸"

    # 2. 非标/非连续日频矿产原料（钛精矿）明确不纳入 100ppi 目录（由周报/产业调查链路专职承接）
    assert "ilmenite" not in COMMODITY_CATALOG

    # 3. 快照回放与加载验证（使用独立临时目录验证契约，不污染全局真实 RAW）
    ppi_mock_dir = tmp_path / "chemicals" / "100ppi"
    ppi_mock_dir.mkdir(parents=True, exist_ok=True)
    mock_payload = {
        "symbol": "TiO2",
        "product_name": "钛白粉",
        "spec": "金红石型(R2型);硫酸法",
        "region": "国内",
        "unit": "元/吨",
        "dates": ["2026-09-14", "2026-09-15"],
        "prices": [14000.0, 14200.0],
    }
    (ppi_mock_dir / "TiO2.json").write_text(json.dumps(mock_payload), encoding="utf-8")

    collector = ChemicalSpotPriceCollector(raw_dir=tmp_path)
    tio2_recs = collector.load_from_raw_snapshot("TiO2")
    assert len(tio2_recs) == 2
    assert tio2_recs[0].product_name == "钛白粉"
    assert tio2_recs[0].spot_price_cny == 14000.0
    assert tio2_recs[1].spot_price_cny == 14200.0
