"""基础化工真实基本面数据采集器与转换器单元测试。"""

from datetime import date
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.chemicals.collectors.market import ChemicalsCollector
from stock_data.fetcher.industry.chemicals.parsers.raw_csv import (
    load_chemicals_raw_csv,
    save_chemicals_raw_csv,
)
from stock_data.fetcher.industry.chemicals.quality import validate_chemical_market_records
from stock_data.fetcher.industry.chemicals.transforms.facts import (
    records_to_chemical_market_frame,
)
from stock_data.fetcher.industry.models import ChemicalMarketRecord


def test_chemicals_raw_csv_roundtrip(tmp_path: Path) -> None:
    csv_file = tmp_path / "test_chemicals.csv"
    sample = [
        ChemicalMarketRecord(
            report_month="2026-08",
            trade_date=date(2026, 8, 31),
            soda_ash_production=289.0,
            caustic_soda_production=350.0,
            synthetic_fiber_production=620.0,
            chemical_fertilizer_production=500.0,
            plastics_production=1050.0,
            plate_glass_production=8850.0,
            spot_soda_ash_price_cny=2200.0,
            spot_pta_price_cny=5200.0,
            spot_urea_price_cny=2250.0,
            spot_mdi_price_cny=16866.67,
            spot_tio2_price_cny=14060.00,
            spot_refrigerant_r32_price_cny=35000.0,
            soda_ash_operating_rate=None,
            pta_operating_rate=None,
            chemical_social_inventory=None,
            unit="mixed",
            source="NBS/CZCE/100ppi",
            source_url="https://data.stats.gov.cn/",
            release_date=date(2026, 9, 18),
            data_status="actual",
            collected_at="2026-09-01T00:00:00Z",
        )
    ]
    save_chemicals_raw_csv(csv_file, sample)
    loaded = load_chemicals_raw_csv(csv_file)
    assert len(loaded) == 1
    assert loaded[0].report_month == "2026-08"
    assert loaded[0].soda_ash_production == 289.0
    assert loaded[0].plate_glass_production == 8850.0
    assert loaded[0].spot_soda_ash_price_cny == 2200.0
    assert loaded[0].soda_ash_price_cny == 2200.0  # 向后兼容属性
    assert loaded[0].soda_ash_operating_rate is None  # 未授权商业源保持 None


def test_chemicals_collector_does_not_carry_forward_missing_monthly_facts(
    tmp_path: Path,
) -> None:
    chem_dir = tmp_path / "chemicals"
    chem_dir.mkdir(parents=True)
    save_chemicals_raw_csv(
        chem_dir / "chemical_operating_spreads.csv",
        [
            ChemicalMarketRecord(
                report_month="2026-08",
                trade_date=date(2026, 8, 31),
                soda_ash_production=289.0,
                spot_soda_ash_price_cny=2200.0,
                spot_mdi_price_cny=16866.67,
                release_date=date(2026, 9, 18),
                collected_at="2026-09-01T00:00:00Z",
            )
        ],
    )
    _write_spot_reference_parquet(tmp_path, month="2026-09", mdi=17000.0)

    collector = ChemicalsCollector(raw_dir=tmp_path, curated_dir=tmp_path / "curated")
    records = collector.collect(force=False)

    rec_2026_09 = next(r for r in records if r.report_month == "2026-09")
    assert rec_2026_09.spot_mdi_price_cny == 17000.0
    assert rec_2026_09.mdi_price_cny == 17000.0
    assert rec_2026_09.soda_ash_production is None
    assert rec_2026_09.spot_soda_ash_price_cny is None
    assert rec_2026_09.soda_ash_price_cny is None


def test_chemicals_collect_result_reports_cached_month_without_refresh(tmp_path: Path) -> None:
    csv_file = tmp_path / "chemicals" / "chemical_operating_spreads.csv"
    save_chemicals_raw_csv(
        csv_file,
        [
            ChemicalMarketRecord(
                report_month="2026-08",
                trade_date=date(2026, 8, 31),
                soda_ash_production=289.0,
                source="NBS_Official",
                release_date=date(2026, 9, 5),
            )
        ],
    )

    result = ChemicalsCollector(raw_dir=tmp_path).collect_result(
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 31),
    )

    assert result.status == "NO_CHANGE"
    assert result.cached_periods == ("2026-08",)
    assert result.missing_periods == ()
    assert result.updated is False


def test_chemical_market_quality_rejects_invalid_values() -> None:
    records, errors = validate_chemical_market_records(
        [
            ChemicalMarketRecord(
                report_month="2026-08",
                trade_date=date(2026, 8, 31),
                soda_ash_production=-1.0,
                soda_ash_operating_rate=101.0,
            )
        ]
    )

    assert records == []
    assert any("soda_ash_production" in error for error in errors)
    assert any("soda_ash_operating_rate" in error for error in errors)


def test_research_report_parser_requires_publish_date(tmp_path: Path) -> None:
    from stock_data.fetcher.industry.chemicals.parsers.research import ResearchReportParser

    parser = ResearchReportParser(raw_dir=tmp_path)
    records = parser.extract_metrics_from_text("纯碱开工率80.44%，企业库存190.84万吨")

    assert records == []


def test_chemicals_collector_project_raw() -> None:
    collector = ChemicalsCollector(raw_dir="data/raw/industry")
    records = collector.collect(force=False)
    assert len(records) >= 120
    r0 = records[0]
    assert r0.report_month == "2016-09"
    assert r0.soda_ash_production is not None
    assert r0.plate_glass_production is not None
    assert r0.soda_ash_operating_rate is None


def test_chemicals_loader_rejects_legacy_unproven_ppi_prices(tmp_path: Path) -> None:
    csv_file = tmp_path / "legacy.csv"
    csv_file.write_text(
        "report_month,mdi_price_cny,tio2_price_cny,source,release_date\n"
        "2026-08,17000,14060,NBS_Official,2026-09-18\n",
        encoding="utf-8",
    )

    records = load_chemicals_raw_csv(csv_file)

    assert records[0].mdi_price_cny is None
    assert records[0].tio2_price_cny is None


def test_chemicals_transform_frame() -> None:
    collector = ChemicalsCollector(raw_dir="data/raw/industry")
    records = collector.collect(force=False)
    df = records_to_chemical_market_frame(records)
    assert not df.is_empty()
    assert "report_month" in df.columns
    assert "soda_ash_production" in df.columns
    assert "plate_glass_production" in df.columns
    assert "spot_soda_ash_price_cny" in df.columns
    assert "czce_soda_ash_receipt" not in df.columns
    assert df["soda_ash_production"].is_not_null().any()
    assert df["soda_ash_operating_rate"].is_null().all()  # 严格保持 NULL


def test_chemicals_collector_offline_by_default(tmp_path: Path) -> None:
    """验证 ChemicalsCollector 默认走纯离线安全模式，零网络请求。"""
    chem_dir = tmp_path / "chemicals"
    chem_dir.mkdir(parents=True)
    save_chemicals_raw_csv(
        chem_dir / "chemical_operating_spreads.csv",
        [
            ChemicalMarketRecord(
                report_month="2026-08",
                trade_date=date(2026, 8, 31),
                soda_ash_production=289.0,
                release_date=date(2026, 9, 18),
            )
        ],
    )
    # 不传入任何 mock，验证默认不发起网络请求且无任何 collection_errors
    collector = ChemicalsCollector(raw_dir=tmp_path)
    records = collector.collect(force=False)
    assert len(records) == 1
    assert collector.collection_errors == []


def test_weekly_survey_collector_offline_by_default(tmp_path: Path) -> None:
    """验证 ChemicalWeeklySurveyCollector 默认离线模式不发起 100ppi 爬虫，无报错。"""
    from stock_data.fetcher.industry.chemicals.collectors.weekly_survey import (
        ChemicalWeeklySurveyCollector,
    )

    collector = ChemicalWeeklySurveyCollector(raw_dir=tmp_path)
    result = collector.collect_result()
    assert result.status in {"EMPTY", "SUCCESS", "NO_CHANGE"}
    assert "100ppi 周报请求失败或返回空页面" not in collector.collection_errors


def test_nbs_crawler_offline_and_unknown_product(tmp_path: Path) -> None:
    """验证 NbsChemicalsCrawler 在离线模式及未知品种时安全返回 None。"""
    from stock_data.fetcher.industry.chemicals.collectors.capacity import NbsChemicalsCrawler

    # 1. 离线模式默认不发起网络请求
    offline_crawler = NbsChemicalsCrawler(raw_dir=tmp_path, enable_network=False)
    res_offline = offline_crawler.fetch_month("2026-08", product_name="纯碱")
    assert res_offline is None

    # 2. 未在 NBS 目录树配置的品种安全退出
    online_crawler = NbsChemicalsCrawler(raw_dir=tmp_path, enable_network=True)
    res_unknown = online_crawler.fetch_month("2026-08", product_name="未知化工品")
    assert res_unknown is None


def _write_spot_reference_parquet(
    tmp_path: Path,
    *,
    month: str,
    mdi: float | None = None,
    tio2: float | None = None,
    release_date: date | None = None,
    raw_sha: str = "sha-mdi",
) -> Path:
    """向 tmp_path/curated 写入含 MDI/TiO2 的 chemical_spot_price.parquet。"""
    rows = []
    if mdi is not None:
        rows.append(
            {
                "symbol": "MDI",
                "trade_date": date(int(month[:4]), int(month[5:7]), 15),
                "spot_price_cny": mdi,
                "source": "100ppi",
                "source_url": "https://www.100ppi.com/graph/cindex.php?f=graph_ave&ppid=975&type=1&mode=3",
                "release_date": release_date or date(int(month[:4]), int(month[5:7]), 15),
                "data_status": "spot_benchmark",
                "collected_at": "2026-09-16T00:00:00Z",
                "raw_content_sha256": raw_sha,
                "raw_snapshot_path": "chemicals/100ppi/MDI.json",
            }
        )
    if tio2 is not None:
        rows.append(
            {
                "symbol": "TiO2",
                "trade_date": date(int(month[:4]), int(month[5:7]), 15),
                "spot_price_cny": tio2,
                "source": "100ppi",
                "source_url": "https://www.100ppi.com/graph/cindex.php?f=graph_ave&ppid=645&type=1&mode=3",
                "release_date": release_date or date(int(month[:4]), int(month[5:7]), 15),
                "data_status": "spot_benchmark",
                "collected_at": "2026-09-16T00:00:00Z",
                "raw_content_sha256": "sha-tio2",
                "raw_snapshot_path": "chemicals/100ppi/TiO2.json",
            }
        )
    curated_dir = tmp_path / "curated"
    curated_dir.mkdir(parents=True, exist_ok=True)
    file = curated_dir / "chemical_spot_price.parquet"
    pl.DataFrame(rows).write_parquet(file)
    return file
