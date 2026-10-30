"""新能源汽车端点的 RAW/Curated 与缓存窗口契约测试。"""

import io
import json
import zipfile
from datetime import date
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.automotive.collectors.nev import (
    NevCollector,
)
from stock_data.fetcher.industry.automotive.models import NevMonthlyRecord
from stock_data.fetcher.industry.automotive.registry import ENDPOINT_SPECS
from stock_data.fetcher.industry.automotive.schemas import (
    NEV_MONTHLY_RAW_SCHEMA,
    NEV_MONTHLY_SCHEMA,
)
from stock_data.fetcher.industry.automotive.transform import (
    records_to_nev_frame,
    records_to_raw_nev_frame,
)
from stock_data.fetcher.industry.common import get_month_end_date
from stock_data.fetcher.industry.contracts import IndustryCollectionResult
from stock_data.fetcher.industry.task_executor import execute_single_industry_task


def _record(month: str = "2026-07") -> NevMonthlyRecord:
    year, month_number = (int(part) for part in month.split("-"))
    return NevMonthlyRecord(
        report_month=month,
        trade_date=get_month_end_date(year, month_number),
        wholesale_volume_ten_thousand=100.0,
        total_volume_ten_thousand=200.0,
        penetration_rate=0.5,
        unit="ten_thousand_units",
        source="CPCA",
        source_url="https://www.cpcaauto.com/",
        release_date=date(2026, 8, 10),
        raw_content_sha256="sha-nev",
        raw_snapshot_path="automotive/cpca/cpca.html.gz",
        wholesale_volume_raw="100.0",
        total_volume_raw="200.0",
        penetration_rate_raw="50.0%",
    )


def test_automotive_endpoint_declares_raw_contract() -> None:
    spec = ENDPOINT_SPECS[0]

    assert spec.endpoint == "nev_monthly_sales"
    assert spec.target_file == "nev_monthly_sales.parquet"
    assert spec.raw_subdir == "automotive"
    assert spec.raw_target_file == "data.parquet"


def test_automotive_source_modules_are_split_by_source() -> None:
    from stock_data.fetcher.industry.automotive.collectors import (
        CabiaCollector,
        CpcaCollector,
    )
    from stock_data.fetcher.industry.automotive.parsers import (
        parse_cabia_battery_article,
        parse_cpca_bulletin_article,
    )

    assert CabiaCollector.__module__.endswith(".collectors.cabia")
    assert CpcaCollector.__module__.endswith(".collectors.cpca")
    assert NevCollector.__module__.endswith(".collectors.nev")
    assert parse_cabia_battery_article.__module__.endswith(".parsers.cabia")
    assert parse_cpca_bulletin_article.__module__.endswith(".parsers.cpca")


def test_automotive_raw_transform_preserves_source_fields_and_curated_derives_values() -> None:
    raw = records_to_raw_nev_frame([_record()])

    assert raw.columns == list(NEV_MONTHLY_RAW_SCHEMA)
    assert raw["wholesale_volume_raw"][0] == "100.0"
    assert raw["penetration_rate_raw"][0] == "50.0%"
    assert raw["raw_content_sha256"][0] == "sha-nev"
    assert "wholesale_volume_3mma" not in raw.columns
    assert "yoy_growth_3mma" not in raw.columns

    curated = records_to_nev_frame([_record()])
    assert curated.schema == NEV_MONTHLY_SCHEMA
    assert curated["wholesale_volume_ten_thousand"][0] == 100.0
    assert curated["penetration_rate"][0] == 0.5


def test_automotive_collector_replays_cpca_snapshot(tmp_path: Path) -> None:
    cpca_dir = tmp_path / "automotive" / "cpca"
    cpca_dir.mkdir(parents=True)
    (cpca_dir / "cpca_snapshot.json").write_text(
        json.dumps(
            [
                {
                    "report_month": "2026-07",
                    "wholesale_volume_ten_thousand": 95.13,
                    "total_volume_ten_thousand": 200.0,
                    "source": "CPCA",
                }
            ]
        ),
        encoding="utf-8",
    )

    result = NevCollector(raw_dir=tmp_path).replay_cached_snapshots(
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
    )

    assert result[0].wholesale_volume_ten_thousand == 95.13
    assert result[0].penetration_rate is None
    assert records_to_nev_frame(result)["penetration_rate"][0] == 0.4756
    assert not (tmp_path / "automotive" / "cpca" / "nev_monthly_sales.csv").exists()


def test_cpca_collector_uses_cached_snapshot_without_online_adapter(
    tmp_path: Path, monkeypatch
) -> None:
    from stock_data.fetcher.industry.automotive.collectors.cpca import CpcaCollector

    cpca_dir = tmp_path / "automotive" / "cpca"
    cpca_dir.mkdir(parents=True)
    (cpca_dir / "cpca_snapshot.json").write_text(
        json.dumps(
            [
                {
                    "report_month": "2026-07",
                    "wholesale_volume_ten_thousand": 95.13,
                    "total_volume_ten_thousand": 200.0,
                    "source": "CPCA",
                }
            ]
        ),
        encoding="utf-8",
    )
    collector = CpcaCollector(raw_dir=tmp_path)

    def fail_adapter(**kwargs: object) -> list[NevMonthlyRecord]:
        raise AssertionError("缓存覆盖请求月份时不应调用在线适配器")

    monkeypatch.setattr(collector, "fetch_online", fail_adapter)
    result = collector.collect(
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
    )

    assert result[0].report_month == "2026-07"


def test_automotive_endpoint_writes_raw_before_curated(tmp_path: Path, monkeypatch) -> None:
    record = _record()
    seen: dict[str, object] = {}

    def fake_collect(
        self: NevCollector,
        force: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> IndustryCollectionResult:
        seen.update(force=force, start_date=start_date, end_date=end_date)
        return IndustryCollectionResult([record], fetched_periods=("2026-07",))

    monkeypatch.setattr(NevCollector, "collect", fake_collect)
    result = execute_single_industry_task(
        endpoint="nev_monthly_sales",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
        force_refresh=True,
        raw_dir=tmp_path / "raw",
        curated_dir=tmp_path / "curated",
    )

    assert result.status == "SUCCESS"
    assert seen == {
        "force": True,
        "start_date": date(2026, 7, 1),
        "end_date": date(2026, 7, 31),
    }
    raw = pl.read_parquet(tmp_path / "raw" / "automotive" / "data.parquet")
    curated = pl.read_parquet(tmp_path / "curated" / "nev_monthly_sales.parquet")
    assert "wholesale_volume_raw" in raw.columns
    assert "wholesale_volume_3mma" not in raw.columns
    assert "wholesale_volume_3mma" in curated.columns


def test_cpca_collector_fetches_online_when_month_is_missing(tmp_path: Path, monkeypatch) -> None:
    from stock_data.fetcher.industry.automotive.collectors import cpca as cpca_module

    online_record = _record("2026-08")
    called: dict[str, object] = {}

    def fake_fetch_online(**kwargs: object) -> list[NevMonthlyRecord]:
        called.update(kwargs)
        return [online_record]

    collector = cpca_module.CpcaCollector(raw_dir=tmp_path)
    monkeypatch.setattr(collector, "fetch_online", fake_fetch_online)

    records = collector.collect(
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 31),
    )

    assert records == [online_record]
    assert collector.last_online_attempted is True
    assert called == {
        "start_date": date(2026, 8, 1),
        "end_date": date(2026, 8, 31),
    }


def test_cpca_official_chart_snapshots_preserve_source_tables(tmp_path: Path, monkeypatch) -> None:
    from stock_data.fetcher.industry.automotive.collectors import cpca as cpca_module

    chart_payloads = {
        "6": [
            {
                "dataList": [
                    {"month": "8月", "2025年": [80, 160, 80, 20], "2026年": [90, 180, 90, 20]}
                ]
            }
        ],
        "1": [
            {
                "dataList": [
                    {"month": "8月", "2025年": [170, 170, 160, 10], "2026年": [180, 180, 170, 20]}
                ]
            }
        ],
    }

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}

        def __init__(self, payload: object) -> None:
            self.content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.text = self.content.decode("utf-8")

        def json(self) -> object:
            return json.loads(self.content)

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        del kwargs
        chart_type = url.split("charttype=", 1)[1]
        return FakeResponse(chart_payloads[chart_type])

    monkeypatch.setattr(cpca_module.requests, "get", fake_get)
    client = cpca_module.CpcaOnlineClient(tmp_path)
    records = client.fetch(start_date=date(2026, 8, 1), end_date=date(2026, 8, 31))

    record = next(record for record in records if record["report_month"] == "2026-08")
    assert record["retail_volume_ten_thousand"] == 170.0
    assert record["export_volume_ten_thousand"] == 20.0
    assert record["penetration_rate"] == 0.5
    assert (tmp_path / "automotive" / "cpca" / "chartlist_6.json.gz").exists()
    assert (tmp_path / "automotive" / "cpca" / "chartlist_1.json.gz").exists()


def test_cpca_official_chart_request_retries_transient_failure(tmp_path: Path, monkeypatch) -> None:
    from stock_data.fetcher.industry.automotive.clients import cpca as cpca_module

    chart_payloads = {
        "6": [{"dataList": [{"month": "8月", "2026年": [90, 180, 90, 20]}]}],
        "1": [{"dataList": [{"month": "8月", "2026年": [180, 180, 170, 20]}]}],
    }
    attempts: dict[str, int] = {"6": 0, "1": 0}

    class FakeResponse:
        status_code = 200

        def __init__(self, payload: object) -> None:
            self.content = json.dumps(payload).encode("utf-8")
            self.text = self.content.decode("utf-8")

        def json(self) -> object:
            return json.loads(self.content)

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        del kwargs
        chart_type = url.split("charttype=", 1)[1]
        attempts[chart_type] += 1
        if attempts[chart_type] == 1:
            raise TimeoutError("temporary CPCA timeout")
        return FakeResponse(chart_payloads[chart_type])

    monkeypatch.setattr(cpca_module.requests, "get", fake_get)
    records = cpca_module.CpcaOnlineClient(tmp_path).fetch(
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 31)
    )

    assert [record["report_month"] for record in records] == ["2026-08"]
    assert attempts == {"6": 2, "1": 2}


def test_cpca_official_report_archive_backfills_historical_month(
    tmp_path: Path, monkeypatch
) -> None:
    from stock_data.fetcher.industry.automotive.collectors import cpca as cpca_module

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr(
            "report.txt",
            "2024年12月新能源汽车行业月报，新能源市场销量约为99.8万辆，新能源市场销量占总体乘用车销量59.2%。",
        )
    listing = (
        '<a href="/newslist.php?types=bgzl&id=2024">【新能源】2024年12月新能源汽车行业月报</a>'
    ).encode()
    detail = '<a href="/upload/report.zip">下载</a>'.encode()

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/html"}

        def __init__(self, content: bytes, content_type: str = "text/html") -> None:
            self.content = content
            self.text = content.decode("utf-8", errors="ignore")
            self.headers = {"content-type": content_type}

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        del kwargs
        if "report.zip" in url:
            return FakeResponse(archive.getvalue(), "application/zip")
        if "id=2024" in url:
            return FakeResponse(detail)
        return FakeResponse(listing)

    monkeypatch.setattr(cpca_module.requests, "get", fake_get)
    client = cpca_module.CpcaOnlineClient(
        tmp_path,
        report_index_url="https://example.test/list",
        max_history_pages=1,
    )

    records = client.fetch(start_date=date(2024, 12, 1), end_date=date(2024, 12, 31))

    assert [record["report_month"] for record in records] == ["2024-12"]
    assert records[0]["retail_volume_ten_thousand"] == 99.8
    assert records[0]["raw_snapshot_path"].endswith(".zip")


def test_cabia_collector_discovers_online_resource_and_records_lineage(
    tmp_path: Path, monkeypatch
) -> None:
    from stock_data.fetcher.industry.automotive.clients import cls as cls_module
    from stock_data.fetcher.industry.automotive.collectors import cabia as cabia_module

    payload = {
        "data": {
            "roll_data": [
                {
                    "id": "2456965",
                    "title": "中国汽车动力电池产业创新联盟：8月我国动力电池装车量60.5GWh 同比增长20.1%",
                    "content": (
                        "中国汽车动力电池产业创新联盟发布数据显示，2026年8月，"
                        "我国动力和其他电池合计产量为120.0GWh。其中，动力电池装车量60.5GWh，同比增长20.1%。"
                    ),
                    "ctime": 1787019900,
                }
            ]
        }
    }

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        text = content.decode("utf-8")

        @staticmethod
        def json() -> dict[str, object]:
            return payload

    monkeypatch.setattr(cls_module.requests, "get", lambda *args, **kwargs: FakeResponse())
    crawler = cabia_module.CabiaCrawler(
        raw_dir=tmp_path,
        resource_api_url="https://example.test/api/resources",
    )

    result = crawler.fetch_latest_bulletins(force=True)

    record = result["2026-08"]
    assert record["battery_installation_gwh"] == 60.5
    assert record["raw_content_sha256"]
    assert record["raw_snapshot_path"].startswith("automotive/cabia/")
    assert (tmp_path / record["raw_snapshot_path"]).exists()


def test_nev_collector_reports_online_failure_without_losing_cache(
    tmp_path: Path, monkeypatch
) -> None:
    collector = NevCollector(raw_dir=tmp_path)

    def failed_cpca_collect(**kwargs: object) -> list[NevMonthlyRecord]:
        collector.cpca_source.last_errors = ("CPCA 在线采集失败",)
        collector.cpca_source.last_fetched_periods = ()
        return [_record("2026-07")]

    monkeypatch.setattr(collector.cpca_source, "collect", failed_cpca_collect)
    monkeypatch.setattr(collector.cabia_source, "collect", lambda **kwargs: [])

    result = collector.collect()

    assert result
    assert result.status == "PARTIAL"
    assert result[0].report_month == "2026-07"
    assert result.errors
