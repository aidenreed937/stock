"""半导体 RAW 路径布局与显式注入契约测试。"""

from inspect import Parameter, signature
from pathlib import Path

from stock_data.fetcher.industry.semiconductor import SemiconductorRawPaths
from stock_data.fetcher.industry.semiconductor.collectors import (
    ChipLeadTimeCollector,
    FoundryUtilizationCollector,
    FoundryUtilizationCrawler,
    SeajEquipmentCollector,
    SemiconductorCollector,
    SemiconductorInventoryCollector,
    SemiEquipmentCollector,
    SemiEquipmentCrawler,
    TsmcLeadCollector,
)
from stock_data.fetcher.industry.semiconductor.collectors.seaj_crawler import SeajCrawler


def test_semiconductor_raw_paths_centralize_current_and_legacy_layouts(tmp_path: Path) -> None:
    paths = SemiconductorRawPaths(tmp_path / "raw")

    assert paths.semiconductor_dir == tmp_path / "raw" / "semiconductor"
    assert paths.sia_dir == tmp_path / "raw" / "semiconductor" / "sia"
    assert paths.lead_time_dir == tmp_path / "raw" / "semiconductor" / "lead_time"
    assert paths.seaj_dir == tmp_path / "raw" / "semiconductor" / "seaj"
    assert paths.semi_dir == tmp_path / "raw" / "semiconductor" / "semi"
    assert paths.foundry_dir == tmp_path / "raw" / "semiconductor" / "foundry"
    assert paths.inventory_csv == (
        tmp_path / "raw" / "semiconductor" / "inventory" / "idm_quarterly_financials_10y.csv"
    )
    assert paths.inventory_sec_dir == (
        tmp_path / "raw" / "semiconductor" / "inventory" / "sec_submissions"
    )
    assert paths.tsmc_monthly_html_dir == tmp_path / "raw" / "semiconductor" / "tsmc"


def test_semiconductor_raw_paths_legacy_fallback(tmp_path: Path) -> None:
    """当仅存在历史复数或根级散落目录时，能够自动回退向后兼容。"""
    raw_root = tmp_path / "raw"
    (raw_root / "semiconductors" / "foundry").mkdir(parents=True)
    (raw_root / "semiconductors" / "inventory").mkdir(parents=True)
    (raw_root / "lead_time").mkdir(parents=True)
    (raw_root / "tsmc").mkdir(parents=True)
    (raw_root / "sia").mkdir(parents=True)

    paths = SemiconductorRawPaths(raw_root)
    assert paths.foundry_dir == raw_root / "semiconductors" / "foundry"
    assert paths.inventory_dir == raw_root / "semiconductors" / "inventory"
    assert paths.lead_time_dir == raw_root / "lead_time"
    assert paths.tsmc_monthly_html_dir == raw_root / "tsmc"
    assert paths.sia_dir == raw_root / "sia"


def test_semiconductor_collectors_require_explicit_raw_dir() -> None:
    constructors = (
        ChipLeadTimeCollector,
        FoundryUtilizationCollector,
        FoundryUtilizationCrawler,
        SeajEquipmentCollector,
        SeajCrawler,
        SemiconductorCollector,
        SemiconductorInventoryCollector,
        SemiEquipmentCollector,
        SemiEquipmentCrawler,
        TsmcLeadCollector,
    )

    for constructor in constructors:
        assert signature(constructor).parameters["raw_dir"].default is Parameter.empty


def test_semiconductor_collectors_do_not_own_curated_persistence() -> None:
    collectors = (
        ChipLeadTimeCollector,
        FoundryUtilizationCollector,
        SeajEquipmentCollector,
        SemiconductorCollector,
        SemiconductorInventoryCollector,
        SemiEquipmentCollector,
        TsmcLeadCollector,
    )

    for collector in collectors:
        assert not hasattr(collector, "save_curated")


def test_semiconductor_frame_collectors_collect_raw_only() -> None:
    collectors = (
        FoundryUtilizationCollector,
        SemiconductorInventoryCollector,
        SemiEquipmentCollector,
    )

    for collector in collectors:
        assert hasattr(collector, "collect_raw")
        assert not hasattr(collector, "collect")


def test_semiconductor_raw_paths_sia_dir_fallback(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    legacy_sia = raw_root / "sia"
    legacy_sia.mkdir(parents=True)
    paths = SemiconductorRawPaths(raw_root)
    assert paths.sia_dir == legacy_sia
