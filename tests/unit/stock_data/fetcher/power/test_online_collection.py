"""光伏在线采集、缓存命中和范围强刷契约测试。"""

from datetime import date

from stock_data.fetcher.industry.contracts import IndustryCollectionResult, IndustryRunContext
from stock_data.fetcher.industry.power.collectors.infolink import (
    PvPriceChainCollector,
    save_pv_price_raw_csv,
)
from stock_data.fetcher.industry.power.collectors.nbs import NbsSolarCellCollector
from stock_data.fetcher.industry.power.collectors.nea import SolarCollector
from stock_data.fetcher.industry.power.collectors.silicon import SiliconBranchCollector
from stock_data.fetcher.industry.power.models import (
    SiliconWaferMonthlyRecord,
    SolarCapacityRecord,
    SolarPriceChainRecord,
)
from stock_data.fetcher.industry.power.registry import ENDPOINT_SPECS
from stock_data.fetcher.industry.power.transforms import records_to_solar_price_chain_frame
from stock_data.fetcher.industry.runner import run_endpoint


def test_nbs_online_response_parser_and_snapshot_lineage(tmp_path, monkeypatch) -> None:
    from stock_data.fetcher.industry.power.collectors import nbs as nbs_module

    payload = {
        "data": [
            {
                "code": "202607MM",
                "name": "2026年7月",
                "values": [
                    {"i_showname": "太阳能电池产量当期值 (万千瓦)", "value": "6579.3"},
                    {"i_showname": "太阳能电池产量累计值 (万千瓦)", "value": "44607.9"},
                    {"i_showname": "太阳能电池产量同比增长 (%)", "value": "-9.4"},
                    {"i_showname": "太阳能电池产量累计增长 (%)", "value": "-13.6"},
                ],
            }
        ]
    }

    class Response:
        status_code = 200
        content = b"nbs-response"

        @staticmethod
        def json():
            return payload

    monkeypatch.setattr(nbs_module.requests, "post", lambda *args, **kwargs: Response())
    collector = NbsSolarCellCollector(raw_dir=tmp_path)
    result = collector.crawler.fetch_range(["2026-07"])

    assert result.status == "SUCCESS"
    assert result.fetched_periods == ("2026-07",)
    assert result[0]["output_current"] == 6579.3
    assert result[0]["raw_snapshot_path"] == "power/nbs/nbs_solar_cell_2026-07.json.gz"


def test_solar_range_cache_hit_does_not_call_network(tmp_path) -> None:
    collector = SolarCollector(raw_dir=tmp_path)
    collector.save_to_raw_csv(
        collector.paths.nea_dir / "solar_capacity.csv",
        [
            collector_record := SolarCapacityRecord(
                report_month="2026-07",
                trade_date=date(2026, 7, 31),
                cumulative_capacity_gw=100.0,
            )
        ],
    )

    class NoNetwork:
        def fetch_latest_bulletins(self, **kwargs):
            raise AssertionError("范围已被本地 RAW 覆盖时不应联网")

    collector.crawler = NoNetwork()
    result = collector.collect(
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
    )

    assert result.status == "NO_CHANGE"
    assert result[0].report_month == collector_record.report_month


def test_infolink_range_cache_hit_and_force_refresh(tmp_path) -> None:
    record = SolarPriceChainRecord(
        report_date="2026-08-26",
        trade_date=date(2026, 8, 26),
        module_price_cny_watt=0.72,
    )
    raw_file = tmp_path / "power" / "infolink" / "pv_price_chain_weekly.csv"
    save_pv_price_raw_csv(raw_file, [record])

    class FakeCrawler:
        def __init__(self):
            self.calls = []

        def fetch_range(self, start_date, end_date, *, force=False):
            self.calls.append((start_date, end_date, force))
            return IndustryCollectionResult(
                [
                    {
                        "report_date": "2026-08-26",
                        "trade_date": date(2026, 8, 26),
                        "module_price_cny_watt": 0.73,
                    }
                ],
                fetched_periods=("2026-08-26",),
            )

    crawler = FakeCrawler()
    collector = PvPriceChainCollector(raw_dir=tmp_path, crawler=crawler)
    cached = collector.collect(start_date=date(2026, 8, 24), end_date=date(2026, 8, 30))
    assert cached.status == "NO_CHANGE"
    assert crawler.calls == []

    refreshed = collector.collect(
        force=True,
        start_date=date(2026, 8, 24),
        end_date=date(2026, 8, 30),
    )
    assert refreshed.status == "SUCCESS"
    assert crawler.calls == [(date(2026, 8, 24), date(2026, 8, 30), True)]


def test_silicon_online_range_preserves_secondary_source_lineage(tmp_path) -> None:
    class FakeCrawler:
        def fetch_range(self, *, start_date, end_date, periods, force=False):
            assert start_date == date(2026, 7, 1)
            assert end_date == date(2026, 7, 1)
            assert periods == ["2026-07"]
            assert force is True
            return IndustryCollectionResult(
                [
                    SiliconWaferMonthlyRecord(
                        report_month="2026-07",
                        trade_date=date(2026, 7, 31),
                        polysilicon_output_w_tons=10.51,
                        wafer_output_gw=55.26,
                        polysilicon_inventory_w_tons=52.2,
                        source="Silicon_Branch_Relayed_Solarbe",
                        source_url="https://news.solarbe.com/202608/06/50027311.html",
                        raw_content_sha256="article-sha",
                        raw_snapshot_path="power/silicon_branch/solarbe_20260806.html.gz",
                    )
                ],
                fetched_periods=("2026-07",),
            )

    result = SiliconBranchCollector(raw_dir=tmp_path, crawler=FakeCrawler()).collect(
        force=True,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
    )

    assert result.status == "SUCCESS"
    assert result[0].source == "Silicon_Branch_Relayed_Solarbe"
    assert result[0].raw_snapshot_path.endswith("solarbe_20260806.html.gz")


def test_silicon_online_merge_keeps_existing_unverified_raw_rows(tmp_path) -> None:
    raw_file = tmp_path / "power" / "silicon_wafer_monthly.csv"
    raw_file.parent.mkdir(parents=True)
    raw_file.write_text(
        "report_month,trade_date,polysilicon_output_w_tons,wafer_output_gw,data_status\n"
        "2025-12,2025-12-31,8.0,40.0,reconstructed\n",
        encoding="utf-8",
    )

    class FakeCrawler:
        def fetch_range(self, *, start_date, end_date, periods, force=False):
            del start_date, end_date, periods, force
            return IndustryCollectionResult(
                [
                    SiliconWaferMonthlyRecord(
                        report_month="2026-01",
                        trade_date=date(2026, 1, 31),
                        polysilicon_output_w_tons=9.0,
                        wafer_output_gw=42.0,
                    )
                ],
                fetched_periods=("2026-01",),
            )

    SiliconBranchCollector(raw_dir=tmp_path, crawler=FakeCrawler()).collect(
        force=True,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )

    canonical_raw = tmp_path / "power" / "silicon_branch" / "silicon_wafer_monthly.csv"
    raw_text = canonical_raw.read_text(encoding="utf-8")
    assert "2025-12" in raw_text
    assert "reconstructed" in raw_text


def test_silicon_no_range_entry_uses_online_latest_and_keeps_cached_metadata(tmp_path) -> None:
    raw_file = tmp_path / "power" / "silicon_wafer_monthly.csv"
    raw_file.parent.mkdir(parents=True)
    existing = SiliconWaferMonthlyRecord(
        report_month="2026-07",
        trade_date=date(2026, 7, 31),
        polysilicon_output_w_tons=10.0,
        wafer_output_gw=50.0,
        raw_content_sha256="same-article",
        raw_snapshot_path="power/silicon_branch/solarbe_20260806.html.gz",
        collected_at="2026-08-06T00:00:00Z",
    )
    SiliconBranchCollector(raw_dir=tmp_path).save_to_raw_csv(raw_file, [existing])

    class FakeCrawler:
        def fetch_latest(self, *, force=False):
            assert force is False
            return IndustryCollectionResult(
                [
                    {
                        "report_month": "2026-07",
                        "polysilicon_output_w_tons": 10.0,
                        "wafer_output_gw": 50.0,
                        "source": "Silicon_Branch_Relayed_Solarbe",
                        "source_url": "https://news.solarbe.com/202608/06/50027311.html",
                        "raw_content_sha256": "same-article",
                        "raw_snapshot_path": "power/silicon_branch/solarbe_20260806.html.gz",
                    }
                ],
                fetched_periods=("2026-07",),
            )

    result = SiliconBranchCollector(raw_dir=tmp_path, crawler=FakeCrawler()).collect()

    assert result.status == "SUCCESS"
    assert result[0].collected_at == "2026-08-06T00:00:00Z"


def test_silicon_no_range_entry_falls_back_to_existing_when_online_empty(tmp_path) -> None:
    raw_file = tmp_path / "power" / "silicon_wafer_monthly.csv"
    raw_file.parent.mkdir(parents=True)
    existing = SiliconWaferMonthlyRecord(
        report_month="2026-07",
        trade_date=date(2026, 7, 31),
        polysilicon_output_w_tons=10.0,
        wafer_output_gw=50.0,
    )
    SiliconBranchCollector(raw_dir=tmp_path).save_to_raw_csv(raw_file, [existing])

    class EmptyCrawler:
        def fetch_latest(self, *, force=False):
            del force
            return IndustryCollectionResult([], status="EMPTY")

    result = SiliconBranchCollector(raw_dir=tmp_path, crawler=EmptyCrawler()).collect()

    assert result.status == "NO_CHANGE"
    assert [record.report_month for record in result] == ["2026-07"]


def test_runner_does_not_report_unchanged_cached_table_as_success(tmp_path) -> None:
    record = SolarPriceChainRecord(
        report_date="2026-08-26",
        trade_date=date(2026, 8, 26),
        module_price_cny_watt=0.72,
        collected_at="2026-08-26T00:00:00Z",
    )

    def collect(raw_dir, force, start_date=None, end_date=None):
        del raw_dir, force, start_date, end_date
        return [record]

    from stock_data.fetcher.industry.runner import record_endpoint

    spec = record_endpoint(
        endpoint="online_no_change",
        domain="power",
        collect=collect,
        transform=records_to_solar_price_chain_frame,
        target_file="online_no_change.parquet",
        primary_keys=["report_date"],
        raw_subdir="power",
        raw_transform=records_to_solar_price_chain_frame,
        require_context_coverage=True,
        context_coverage_frequency="weekly",
    )
    context = IndustryRunContext(
        endpoint=spec.endpoint,
        raw_dir=tmp_path / "raw",
        curated_dir=tmp_path / "curated",
        start_date=date(2026, 8, 24),
        end_date=date(2026, 8, 30),
    )
    first = run_endpoint(spec, context)
    second = run_endpoint(spec, context)

    assert first.status == "SUCCESS"
    assert second.status == "NO_CHANGE"
    assert int(second) == 1


def test_power_endpoint_specs_keep_online_raw_contract() -> None:
    specs = {spec.endpoint: spec for spec in ENDPOINT_SPECS}
    assert specs["solar_capacity"].domain == "power"
    assert specs["solar_capacity"].raw_subdir == "power"
    assert specs["solar_price_chain"].raw_subdir == "power"
    assert specs["solar_cell_nbs"].raw_subdir == "power"
    assert specs["silicon_wafer_monthly"].raw_subdir == "power"
