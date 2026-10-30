"""光伏产业 RAW/Curated endpoint 契约与离线重放测试。"""

from datetime import date

import polars as pl

from stock_data.core.task_bundles import expand_task_targets
from stock_data.fetcher.industry.contracts import IndustryRunContext
from stock_data.fetcher.industry.power.lineage import file_lineage
from stock_data.fetcher.industry.power.models import (
    SiliconWaferMonthlyRecord,
    SolarCapacityRecord,
    SolarCellNbsRecord,
    SolarPriceChainRecord,
)
from stock_data.fetcher.industry.power.paths import POWER_RAW_SUBDIR, PowerRawPaths
from stock_data.fetcher.industry.power.registry import ENDPOINT_SPECS
from stock_data.fetcher.industry.power.schemas import (
    SILICON_WAFER_RAW_SCHEMA,
    SOLAR_CAPACITY_RAW_SCHEMA,
    SOLAR_CELL_NBS_RAW_SCHEMA,
    SOLAR_PRICE_CHAIN_RAW_SCHEMA,
)
from stock_data.fetcher.industry.power.transforms import (
    records_to_raw_silicon_wafer_monthly_frame,
    records_to_raw_solar_cell_nbs_frame,
    records_to_raw_solar_frame,
    records_to_raw_solar_price_chain_frame,
    records_to_silicon_wafer_monthly_frame,
    records_to_solar_cell_nbs_frame,
    records_to_solar_frame,
    records_to_solar_price_chain_frame,
)
from stock_data.fetcher.industry.runner import record_endpoint, run_endpoint


def test_power_raw_paths_prefer_canonical_and_read_legacy_files(tmp_path) -> None:
    paths = PowerRawPaths(tmp_path)

    assert paths.nea_dir == tmp_path / "power" / "nea"
    assert paths.nbs_dir == tmp_path / "power" / "nbs"
    assert paths.silicon_branch_dir == tmp_path / "power" / "silicon_branch"
    assert paths.infolink_dir == tmp_path / "power" / "infolink"
    assert paths.solar_capacity_csv == paths.nea_dir / "solar_capacity.csv"
    assert paths.silicon_wafer_monthly_csv == paths.silicon_branch_dir / "silicon_wafer_monthly.csv"

    legacy_nea = tmp_path / "energy" / "cn_nea" / "solar_capacity.csv"
    legacy_nbs = tmp_path / "energy" / "cn_nbs" / "nbs_solar_cell_monthly.csv"
    legacy_silicon = tmp_path / "power" / "silicon_wafer_monthly.csv"
    legacy_price = tmp_path / "energy" / "pv_price_chain_weekly.csv"
    legacy_nea.parent.mkdir(parents=True)
    legacy_nbs.parent.mkdir(parents=True)
    legacy_silicon.parent.mkdir(parents=True, exist_ok=True)
    legacy_price.parent.mkdir(parents=True, exist_ok=True)
    legacy_nea.touch()
    legacy_nbs.touch()
    legacy_silicon.touch()
    legacy_price.touch()

    assert paths.solar_capacity_csv == legacy_nea
    assert paths.solar_cell_nbs_csv == legacy_nbs
    assert paths.silicon_wafer_monthly_csv == legacy_silicon
    assert paths.pv_price_chain_csv == legacy_price

    paths.nea_dir.mkdir(parents=True)
    canonical_nea = paths.nea_dir / "solar_capacity.csv"
    canonical_nea.touch()
    assert paths.solar_capacity_csv == canonical_nea


def test_power_raw_transforms_keep_source_values_and_drop_curated_derivatives() -> None:
    capacity = [
        SolarCapacityRecord(
            report_month="2026-01",
            trade_date=date(2026, 1, 31),
            monthly_new_capacity_gw=99.0,
            cumulative_capacity_gw=999.0,
            yoy_growth=0.99,
            monthly_new_capacity_gw_raw="12.30",
            cumulative_capacity_gw_raw="456.70",
            yoy_growth_raw="0.123",
            raw_content_sha256="capacity-sha",
            raw_snapshot_path="power/nea/jan.html",
        )
    ]
    raw_capacity = records_to_raw_solar_frame(capacity)
    assert raw_capacity.columns == list(SOLAR_CAPACITY_RAW_SCHEMA)
    assert raw_capacity["monthly_new_capacity_gw_raw"][0] == "12.30"
    assert raw_capacity["cumulative_capacity_gw_raw"][0] == "456.70"
    assert raw_capacity["raw_content_sha256"][0] == "capacity-sha"
    assert "monthly_new_capacity_gw" not in raw_capacity.columns
    curated_capacity = records_to_solar_frame(capacity)
    assert curated_capacity["monthly_new_capacity_gw"][0] == 12.30
    assert curated_capacity["cumulative_capacity_gw"][0] == 456.70

    cell = [
        SolarCellNbsRecord(
            report_month="2026-01",
            trade_date=date(2026, 1, 31),
            output_current=999.0,
            output_cumulative=888.0,
            output_yoy=77.0,
            output_cum_yoy=66.0,
            output_current_raw="123.4",
            output_cumulative_raw="234.5",
            output_yoy_raw="12.3",
            output_cum_yoy_raw="23.4",
            raw_content_sha256="cell-sha",
            raw_snapshot_path="power/nbs/jan.html",
        )
    ]
    raw_cell = records_to_raw_solar_cell_nbs_frame(cell)
    assert raw_cell.columns == list(SOLAR_CELL_NBS_RAW_SCHEMA)
    assert raw_cell["output_current_raw"][0] == "123.4"
    assert raw_cell["raw_snapshot_path"][0] == "power/nbs/jan.html"
    assert "output_current" not in raw_cell.columns
    curated_cell = records_to_solar_cell_nbs_frame(cell)
    assert curated_cell["output_current"][0] == 123.4
    assert curated_cell["output_yoy"][0] == 0.123

    price = [
        SolarPriceChainRecord(
            report_date="2026-01-07",
            trade_date=date(2026, 1, 7),
            module_price_cny_watt=9.9,
            module_price_cny_watt_raw="0.723",
            raw_content_sha256="price-sha",
            raw_snapshot_path="power/infolink/jan.html",
        )
    ]
    raw_price = records_to_raw_solar_price_chain_frame(price)
    assert raw_price.columns == list(SOLAR_PRICE_CHAIN_RAW_SCHEMA)
    assert raw_price["module_price_cny_watt_raw"][0] == "0.723"
    assert "module_price_cny_watt" not in raw_price.columns
    assert "module_price_mom" not in raw_price.columns
    assert records_to_solar_price_chain_frame(price)["module_price_cny_watt"][0] == 0.723

    silicon = [
        SiliconWaferMonthlyRecord(
            report_month="2026-01",
            trade_date=date(2026, 1, 31),
            polysilicon_output_w_tons=99.0,
            wafer_output_gw=88.0,
            polysilicon_output_w_tons_raw="10.1",
            polysilicon_output_yoy=88.0,
            polysilicon_output_yoy_raw="12.5",
            wafer_output_yoy=77.0,
            wafer_output_yoy_raw="8.5",
            wafer_output_gw_raw="20.2",
            polysilicon_capacity_annual_w_tons_raw="100.0",
            wafer_capacity_annual_gw_raw="200.0",
            raw_content_sha256="silicon-sha",
            raw_snapshot_path="power/silicon_branch/jan.html",
        )
    ]
    raw_silicon = records_to_raw_silicon_wafer_monthly_frame(silicon)
    assert raw_silicon.columns == list(SILICON_WAFER_RAW_SCHEMA)
    assert raw_silicon["polysilicon_output_w_tons_raw"][0] == "10.1"
    assert "derived_polysilicon_utilization_rate" not in raw_silicon.columns
    curated_silicon = records_to_silicon_wafer_monthly_frame(silicon)
    assert curated_silicon["polysilicon_output_w_tons"][0] == 10.1
    assert curated_silicon["polysilicon_output_yoy"][0] == 0.125
    assert curated_silicon["wafer_output_yoy"][0] == 0.085
    assert curated_silicon["polysilicon_capacity_annual_w_tons"][0] == 100.0
    assert curated_silicon["derived_polysilicon_utilization_rate"][0] == 121.2


def test_silicon_capacity_lineage_points_to_annual_raw_file(tmp_path) -> None:
    from stock_data.fetcher.industry.power.collectors.silicon import SiliconBranchCollector

    monthly_file = tmp_path / "power" / "silicon_wafer_monthly.csv"
    monthly_file.parent.mkdir(parents=True)
    monthly_file.write_text(
        "report_month,trade_date,polysilicon_output_w_tons,wafer_output_gw,data_status\n"
        "2025-01,2025-01-31,9.44,44.71,actual\n",
        encoding="utf-8",
    )
    capacity_file = tmp_path / "power" / "polysilicon_wafer_capacity_annual.csv"
    capacity_file.write_text(
        "year,polysilicon_capacity_w_tons,wafer_capacity_gw\n2025,347.9,1271.1\n",
        encoding="utf-8",
    )

    class EmptyLatestCrawler:
        def fetch_latest(self, *, force=False):
            del force
            return []

    records = SiliconBranchCollector(
        raw_dir=tmp_path,
        crawler=EmptyLatestCrawler(),
    ).collect()

    raw = records_to_raw_silicon_wafer_monthly_frame(records)
    expected_hash, expected_path = file_lineage(capacity_file, tmp_path)
    assert raw["capacity_raw_content_sha256"][0] == expected_hash
    assert raw["capacity_raw_snapshot_path"][0] == expected_path
    assert raw["raw_content_sha256"][0] == file_lineage(monthly_file, tmp_path)[0]
    assert raw["raw_snapshot_path"][0] == "power/silicon_wafer_monthly.csv"


def test_solar_collector_scans_for_new_bulletins_with_existing_raw(tmp_path) -> None:
    from stock_data.fetcher.industry.power.collectors.nea import SolarCollector

    collector = SolarCollector(raw_dir=tmp_path)
    collector.save_to_raw_csv(
        collector.paths.nea_dir / "solar_capacity.csv",
        [
            SolarCapacityRecord(
                report_month="2026-01",
                trade_date=date(2026, 1, 31),
                monthly_new_capacity_gw=10.0,
                cumulative_capacity_gw=100.0,
                monthly_new_capacity_gw_raw="10.0",
                cumulative_capacity_gw_raw="100.0",
            )
        ],
    )

    class FakeCrawler:
        def __init__(self) -> None:
            self.calls = 0

        def fetch_latest_bulletins(self):
            self.calls += 1
            return {"2026-02": {"cumulative_gw": 115.0, "url": "http://test/2026-02"}}

    crawler = FakeCrawler()
    collector.crawler = crawler
    records = collector.collect()

    assert crawler.calls == 1
    assert [record.report_month for record in records] == ["2026-01", "2026-02"]
    assert records[-1].monthly_new_capacity_gw == 15.0


def test_power_registry_declares_all_raw_and_curated_endpoint_contracts() -> None:
    specs = {spec.endpoint: spec for spec in ENDPOINT_SPECS}

    assert set(specs) == {
        "solar_capacity",
        "solar_price_chain",
        "solar_cell_nbs",
        "silicon_wafer_monthly",
        "polysilicon_supply_monthly",
        "polysilicon_inventory_monthly",
        "pv_wafer_monthly",
        "polysilicon_balance",
        "solar_supply_demand",
    }
    assert specs["solar_capacity"].target_file == "solar_capacity.parquet"
    assert specs["solar_capacity"].raw_subdir == POWER_RAW_SUBDIR
    assert specs["solar_price_chain"].raw_subdir == POWER_RAW_SUBDIR
    assert specs["solar_cell_nbs"].raw_subdir == POWER_RAW_SUBDIR
    assert specs["silicon_wafer_monthly"].raw_subdir == POWER_RAW_SUBDIR
    assert specs["silicon_wafer_monthly"].target_file == "silicon_wafer_monthly.parquet"
    assert all(spec.domain == "power" for spec in specs.values())
    assert all(
        specs[name].raw_subdir == ""
        for name in {
            "polysilicon_supply_monthly",
            "polysilicon_inventory_monthly",
            "pv_wafer_monthly",
            "polysilicon_balance",
            "solar_supply_demand",
        }
    )


def test_power_endpoint_replay_writes_raw_before_curated(tmp_path, monkeypatch) -> None:
    from stock_data.fetcher.industry.power.collectors.nea import SolarCollector

    record = SolarCapacityRecord(
        report_month="2026-01",
        trade_date=date(2026, 1, 31),
        monthly_new_capacity_gw=12.3,
        cumulative_capacity_gw=456.7,
        raw_content_sha256="replay-sha",
        raw_snapshot_path="power/nea/jan.html",
    )

    def fake_collect(self, force: bool = False):
        del self, force
        return [record]

    monkeypatch.setattr(SolarCollector, "collect", fake_collect)
    spec = next(spec for spec in ENDPOINT_SPECS if spec.endpoint == "solar_capacity")
    run_endpoint(
        spec,
        IndustryRunContext(
            endpoint=spec.endpoint,
            raw_dir=tmp_path / "raw",
            curated_dir=tmp_path / "curated",
        ),
    )

    raw_path = tmp_path / "raw" / "power" / "solar_capacity.parquet"
    curated_path = tmp_path / "curated" / "solar_capacity.parquet"
    assert raw_path.exists()
    assert curated_path.exists()
    assert "monthly_new_capacity_gw" not in pl.read_parquet(raw_path).columns
    assert pl.read_parquet(curated_path)["monthly_new_capacity_gw"][0] == 12.3


def test_price_endpoint_replays_legacy_raw_when_live_source_is_unavailable(tmp_path) -> None:
    from stock_data.fetcher.industry.power.collectors.infolink import (
        PvPriceChainCollector,
        save_pv_price_raw_csv,
    )

    record = SolarPriceChainRecord(
        report_date="2026-01-07",
        trade_date=date(2026, 1, 7),
        module_price_cny_watt=0.723,
        module_price_cny_watt_raw="0.723",
    )
    legacy_path = tmp_path / "energy" / "pv_price_chain_weekly.csv"
    save_pv_price_raw_csv(legacy_path, [record])

    class OfflineCrawler:
        def fetch_live_spot_prices(self, force: bool = False):
            del force
            return

    records = PvPriceChainCollector(raw_dir=tmp_path, crawler=OfflineCrawler()).collect()

    assert [item.report_date for item in records] == ["2026-01-07"]
    assert (tmp_path / "power" / "infolink" / "pv_price_chain_weekly.csv").exists()


def test_derived_power_endpoints_replay_from_curated_only(tmp_path) -> None:
    curated_dir = tmp_path / "curated"
    raw_dir = tmp_path / "raw"
    curated_dir.mkdir()

    silicon = records_to_silicon_wafer_monthly_frame(
        [
            SiliconWaferMonthlyRecord(
                report_month="2026-01",
                trade_date=date(2026, 1, 31),
                polysilicon_output_w_tons=10.0,
                wafer_output_gw=20.0,
                polysilicon_inventory_w_tons=30.0,
            ),
            SiliconWaferMonthlyRecord(
                report_month="2026-02",
                trade_date=date(2026, 2, 28),
                polysilicon_output_w_tons=11.0,
                wafer_output_gw=21.0,
                polysilicon_inventory_w_tons=31.0,
            ),
        ]
    )
    silicon.write_parquet(curated_dir / "silicon_wafer_monthly.parquet")
    specs = {spec.endpoint: spec for spec in ENDPOINT_SPECS}

    for endpoint in (
        "polysilicon_supply_monthly",
        "polysilicon_inventory_monthly",
        "pv_wafer_monthly",
    ):
        run_endpoint(
            specs[endpoint],
            IndustryRunContext(endpoint=endpoint, raw_dir=raw_dir, curated_dir=curated_dir),
        )
        assert (curated_dir / f"{endpoint}.parquet").exists()

    pl.DataFrame(
        {
            "category_key": ["polysilicon", "polysilicon"],
            "product_key": ["polysilicon", "polysilicon"],
            "hs_code": ["280461", "280461"],
            "report_month": ["2026-01", "2026-01"],
            "trade_direction": ["import", "export"],
            "export_volume": [10_000_000.0, 2_000_000.0],
            "source": ["UN_Comtrade", "UN_Comtrade"],
            "trade_value_currency": ["USD", "USD"],
        }
    ).write_parquet(curated_dir / "customs_trade.parquet")
    pl.DataFrame(
        {
            "category_key": ["polysilicon", "polysilicon"],
            "product_key": ["polysilicon", "polysilicon"],
            "hs_code": ["28046190", "28046190"],
            "report_month": ["2026-01", "2026-01"],
            "trade_direction": ["import", "export"],
            "export_volume": [12_000_000.0, 3_000_000.0],
            "source": ["GACC", "GACC"],
            "trade_value_currency": ["USD", "USD"],
        }
    ).write_parquet(curated_dir / "customs_trade_gacc.parquet")

    run_endpoint(
        specs["polysilicon_balance"],
        IndustryRunContext(
            endpoint="polysilicon_balance", raw_dir=raw_dir, curated_dir=curated_dir
        ),
    )
    assert (curated_dir / "polysilicon_balance.parquet").exists()
    balance = pl.read_parquet(curated_dir / "polysilicon_balance.parquet")
    assert "implied_demand_w_tons" in balance.columns
    assert balance["implied_demand_w_tons"].null_count() == 0
    assert balance["total_supply_w_tons"].null_count() == 0
    assert balance["theoretical_surplus_w_tons"].null_count() == 0
    assert balance.filter(pl.col("report_month") == "2026-01")["net_imports_w_tons"][0] == 0.9
    second_balance = run_endpoint(
        specs["polysilicon_balance"],
        IndustryRunContext(
            endpoint="polysilicon_balance", raw_dir=raw_dir, curated_dir=curated_dir
        ),
    )
    assert second_balance.status == "NO_CHANGE"
    assert second_balance.updated is False

    cell = pl.DataFrame(
        {
            "report_month": ["2026-01"],
            "trade_date": [date(2026, 1, 31)],
            "output_current": [100.0],
            "output_current_3mma": [100.0],
            "output_cumulative": [100.0],
            "output_yoy": [10.0],
            "output_cum_yoy": [10.0],
            "yoy_growth_3mma": [None],
            "mom_growth_3mma": [None],
            "unit": ["ten_thousand_kw"],
            "source": ["NBS"],
            "source_url": ["nbs"],
            "release_date": [date(2026, 2, 18)],
            "data_status": ["actual"],
            "collected_at": ["2026-02-18T00:00:00Z"],
        }
    )
    capacity = pl.DataFrame(
        {
            "report_month": ["2026-01"],
            "trade_date": [date(2026, 1, 31)],
            "monthly_new_capacity_gw": [12.0],
            "monthly_new_capacity_3mma": [12.0],
            "cumulative_capacity_gw": [456.0],
            "yoy_growth": [20.0],
            "yoy_growth_3mma": [None],
            "mom_growth_3mma": [None],
            "unit": ["gw"],
            "source": ["NEA"],
            "source_url": ["nea"],
            "release_date": [date(2026, 2, 20)],
            "data_status": ["actual"],
            "collected_at": ["2026-02-20T00:00:00Z"],
        }
    )
    cell.write_parquet(curated_dir / "solar_cell_production.parquet")
    capacity.write_parquet(curated_dir / "solar_capacity.parquet")
    run_endpoint(
        specs["solar_supply_demand"],
        IndustryRunContext(
            endpoint="solar_supply_demand", raw_dir=raw_dir, curated_dir=curated_dir
        ),
    )
    assert (curated_dir / "solar_supply_demand.parquet").exists()


def test_power_bundles_include_full_photovoltaic_chain() -> None:
    expected = {
        "solar_capacity",
        "solar_price_chain",
        "solar_cell_nbs",
        "silicon_wafer_monthly",
        "polysilicon_supply_monthly",
        "polysilicon_inventory_monthly",
        "pv_wafer_monthly",
        "polysilicon_balance",
        "solar_supply_demand",
    }
    for bundle in ("industry_energy_bundle", "industry_all_bundle"):
        assert expected <= set(expand_task_targets("industry", [bundle]))
    assert (expected - {"solar_price_chain"}) <= set(
        expand_task_targets("industry", ["industry_monthly_bundle"])
    )


def test_record_endpoint_rejects_cached_rows_outside_requested_context(tmp_path) -> None:
    old_record = SolarCapacityRecord(
        report_month="2026-01",
        trade_date=date(2026, 1, 31),
        monthly_new_capacity_gw=10.0,
        cumulative_capacity_gw=100.0,
    )
    calls: dict[str, object] = {}

    def collect(raw_dir, force, start_date=None, end_date=None):
        calls.update(
            raw_dir=raw_dir,
            force=force,
            start_date=start_date,
            end_date=end_date,
        )
        return [old_record]

    spec = record_endpoint(
        endpoint="solar_capacity_test",
        domain="power",
        collect=collect,
        transform=records_to_solar_frame,
        target_file="solar_capacity_test.parquet",
        primary_keys=["report_month"],
        raw_subdir=POWER_RAW_SUBDIR,
        raw_transform=records_to_raw_solar_frame,
        force_refresh_on_gap=True,
        require_context_coverage=True,
    )
    count = run_endpoint(
        spec,
        IndustryRunContext(
            endpoint=spec.endpoint,
            raw_dir=tmp_path / "raw",
            curated_dir=tmp_path / "curated",
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 28),
        ),
    )

    assert count == 0
    assert calls["force"] is True
    assert calls["start_date"] == date(2026, 2, 1)
    assert calls["end_date"] == date(2026, 2, 28)
    assert not (tmp_path / "raw" / POWER_RAW_SUBDIR / "solar_capacity_test.parquet").exists()
    assert not (tmp_path / "curated" / "solar_capacity_test.parquet").exists()


def test_record_endpoint_accepts_new_price_within_requested_week(tmp_path) -> None:
    record = SolarPriceChainRecord(
        report_date="2026-08-26",
        trade_date=date(2026, 8, 26),
        module_price_cny_watt=0.723,
    )

    spec = record_endpoint(
        endpoint="solar_price_chain_test",
        domain="power",
        collect=lambda raw_dir, force: [record],
        transform=records_to_solar_price_chain_frame,
        target_file="solar_price_chain_test.parquet",
        primary_keys=["report_date"],
        raw_subdir=POWER_RAW_SUBDIR,
        raw_transform=records_to_raw_solar_price_chain_frame,
        force_refresh_on_gap=True,
        require_context_coverage=True,
        context_coverage_frequency="weekly",
    )

    count = run_endpoint(
        spec,
        IndustryRunContext(
            endpoint=spec.endpoint,
            raw_dir=tmp_path / "raw",
            curated_dir=tmp_path / "curated",
            start_date=date(2026, 8, 24),
            end_date=date(2026, 8, 24),
        ),
    )

    assert count == 1


def test_infolink_force_refresh_bypasses_stale_html_snapshot(tmp_path, monkeypatch) -> None:
    import stock_data.fetcher.industry.power.collectors.infolink as price_module
    from stock_data.fetcher.industry.power.collectors.infolink import InfoLinkPvPriceCrawler

    snapshot = tmp_path / "power" / "infolink" / "infolink_live_spot_price.html"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("stale", encoding="utf-8")

    class Parser:
        def parse(self, html_text, source_url="", **kwargs):
            del source_url, kwargs
            assert html_text == "fresh"
            return {
                "report_date": "2026-08-26",
                "trade_date": date(2026, 8, 26),
                "module_price_cny_watt": 0.723,
            }

    class Response:
        status_code = 200
        text = "fresh"
        content = b"fresh"

    calls: list[str] = []

    def fake_get(*args, **kwargs):
        del args, kwargs
        calls.append("network")
        return Response()

    monkeypatch.setattr(price_module.requests, "get", fake_get)
    result = InfoLinkPvPriceCrawler(raw_dir=tmp_path, parser=Parser()).fetch_live_spot_prices(
        force=True
    )

    assert result is not None
    assert calls == ["network"]


def test_infolink_default_fetch_prefers_online_over_stale_html_snapshot(
    tmp_path, monkeypatch
) -> None:
    import stock_data.fetcher.industry.power.collectors.infolink as price_module
    from stock_data.fetcher.industry.power.collectors.infolink import InfoLinkPvPriceCrawler

    snapshot = tmp_path / "power" / "infolink" / "infolink_live_spot_price.html"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("stale", encoding="utf-8")

    class Parser:
        def parse(self, html_text, source_url="", **kwargs):
            del source_url, kwargs
            assert html_text == "fresh"
            return {
                "report_date": "2026-08-26",
                "trade_date": date(2026, 8, 26),
                "module_price_cny_watt": 0.723,
            }

    class Response:
        status_code = 200
        text = "fresh"
        content = b"fresh"

    calls: list[str] = []

    def fake_get(*args, **kwargs):
        del args, kwargs
        calls.append("network")
        return Response()

    monkeypatch.setattr(price_module.requests, "get", fake_get)
    result = InfoLinkPvPriceCrawler(raw_dir=tmp_path, parser=Parser()).fetch_live_spot_prices()

    assert result is not None
    assert calls == ["network"]


def test_frame_endpoint_rejects_stale_curated_inputs(tmp_path) -> None:
    silicon = records_to_silicon_wafer_monthly_frame(
        [
            SiliconWaferMonthlyRecord(
                report_month="2026-01",
                trade_date=date(2026, 1, 31),
                wafer_output_gw=20.0,
            )
        ]
    )
    curated_dir = tmp_path / "curated"
    raw_dir = tmp_path / "raw"
    curated_dir.mkdir()
    silicon.write_parquet(curated_dir / "silicon_wafer_monthly.parquet")
    spec = next(spec for spec in ENDPOINT_SPECS if spec.endpoint == "pv_wafer_monthly")

    count = run_endpoint(
        spec,
        IndustryRunContext(
            endpoint=spec.endpoint,
            raw_dir=raw_dir,
            curated_dir=curated_dir,
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 28),
        ),
    )

    assert count == 0
    assert not (curated_dir / "pv_wafer_monthly.parquet").exists()


def test_power_replay_plan_is_dependency_ordered() -> None:
    from scripts.replay_industry_raw import POWER_REPLAY_ORDER, _build_metric_plan

    plan = _build_metric_plan()
    expected = {
        "solar_capacity",
        "solar_cell_nbs",
        "solar_price_chain",
        "silicon_wafer_monthly",
        "polysilicon_supply_monthly",
        "polysilicon_inventory_monthly",
        "pv_wafer_monthly",
        "polysilicon_balance",
        "solar_supply_demand",
    }
    assert expected <= set(plan)
    assert list(POWER_REPLAY_ORDER) == [
        "solar_capacity",
        "solar_cell_nbs",
        "solar_price_chain",
        "silicon_wafer_monthly",
        "polysilicon_supply_monthly",
        "polysilicon_inventory_monthly",
        "pv_wafer_monthly",
        "polysilicon_balance",
        "solar_supply_demand",
    ]
    assert all(
        plan[name].get("loader_uses_curated")
        for name in expected
        - {
            "solar_capacity",
            "solar_cell_nbs",
            "solar_price_chain",
            "silicon_wafer_monthly",
        }
    )


def test_industry_sync_orders_curated_power_dependencies(monkeypatch) -> None:
    import stock_data.pipeline.sync as sync_module
    from stock_data.pipeline.sync import DailySyncEngine, SyncExecutionResult
    from stock_data.pipeline.sync_models import SyncTaskItem

    day = date(2026, 9, 1)
    endpoints = [
        "solar_supply_demand",
        "solar_capacity",
        "polysilicon_balance",
        "silicon_wafer_monthly",
        "pv_wafer_monthly",
    ]
    plan = [
        SyncTaskItem(
            data_source="industry",
            endpoint=endpoint,
            dataset=endpoint,
            start_date=day,
            end_date=day,
            watermark=None,
            status="PENDING",
            is_ready=True,
        )
        for endpoint in endpoints
    ]
    execution_order: list[str] = []

    def fake_run(task, force_refresh):
        del force_refresh
        execution_order.append(task.endpoint)
        return SyncExecutionResult(
            data_source="industry",
            endpoint=task.endpoint,
            start_date=day,
            end_date=day,
            records=1,
            duration_s=0.0,
            status="SUCCESS",
        )

    monkeypatch.setattr(sync_module, "_run_sync_task", fake_run)
    DailySyncEngine(data_source="industry", max_workers=3).execute_plan(plan)

    stage0 = execution_order.index("solar_capacity")
    stage1 = execution_order.index("pv_wafer_monthly")
    stage2 = execution_order.index("polysilicon_balance")
    assert stage0 < stage1 < stage2
    assert execution_order.index("solar_supply_demand") > stage0


def test_industry_sync_blocks_derived_tasks_after_upstream_failure(monkeypatch) -> None:
    import stock_data.pipeline.sync as sync_module
    from stock_data.pipeline.sync import DailySyncEngine, SyncExecutionResult
    from stock_data.pipeline.sync_models import SyncTaskItem

    day = date(2026, 9, 1)
    endpoints = ["silicon_wafer_monthly", "pv_wafer_monthly", "polysilicon_balance"]
    plan = [
        SyncTaskItem(
            data_source="industry",
            endpoint=endpoint,
            dataset=endpoint,
            start_date=day,
            end_date=day,
            watermark=None,
            status="PENDING",
            is_ready=True,
        )
        for endpoint in endpoints
    ]
    execution_order: list[str] = []

    def fake_run(task, force_refresh):
        del force_refresh
        execution_order.append(task.endpoint)
        status = "FAILED" if task.endpoint == "silicon_wafer_monthly" else "SUCCESS"
        return SyncExecutionResult(
            data_source="industry",
            endpoint=task.endpoint,
            start_date=day,
            end_date=day,
            records=1 if status == "SUCCESS" else 0,
            duration_s=0.0,
            status=status,
        )

    monkeypatch.setattr(sync_module, "_run_sync_task", fake_run)
    results = DailySyncEngine(data_source="industry", max_workers=1).execute_plan(plan)
    by_endpoint = {result.endpoint: result for result in results}

    assert execution_order == ["silicon_wafer_monthly"]
    assert by_endpoint["silicon_wafer_monthly"].status == "FAILED"
    assert by_endpoint["pv_wafer_monthly"].status == "BLOCKED"
    assert by_endpoint["polysilicon_balance"].status == "BLOCKED"
