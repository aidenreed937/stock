"""化工产业 RAW 快照与输入文件的统一路径布局。"""

from __future__ import annotations

from pathlib import Path

CHEMICALS_RAW_SUBDIR = "chemicals"
PPI_RAW_SUBDIR = "100ppi"
OPERATING_RATES_RAW_SUBDIR = "operating_rates"
NBS_RAW_SUBDIR = "nbs"
FUTURES_INVENTORY_RAW_SUBDIR = "futures_inventory"
FUTURES_HOLD_RANK_RAW_SUBDIR = "futures_hold_rank"
CAPACITY_RAW_SUBDIR = "capacity"

CHEMICAL_MARKET_LEGACY_FILENAME = "chemical_operating_spreads.csv"
CHEMICAL_MARKET_STANDARD_FILENAME = "chemical_market_prices.csv"
CHEMICAL_MARKET_RAW_FILENAME = CHEMICAL_MARKET_LEGACY_FILENAME
WEEKLY_SURVEY_RAW_FILENAME = "weekly_survey.csv"
WEEKLY_SOURCES_RAW_FILENAME = "mysteel_weekly_sources.csv"
SPREAD_RAW_FILENAME = "chemical_spreads.csv"
NBS_SODA_ASH_RAW_FILENAME = "nbs_soda_ash_monthly.csv"
CHEMICALS_RAW_FILENAME = "data.parquet"
CAPACITY_RAW_FILENAME = CHEMICALS_RAW_FILENAME


class ChemicalsRawPaths:
    """基于调用方传入的 RAW 根目录解析化工产业路径。"""

    def __init__(self, raw_dir: Path | str) -> None:
        self.raw_root = Path(raw_dir)
        self.chemicals_dir = self.raw_root / CHEMICALS_RAW_SUBDIR
        self.ppi_dir = self.chemicals_dir / PPI_RAW_SUBDIR
        self.operating_rates_dir = self.chemicals_dir / OPERATING_RATES_RAW_SUBDIR
        self.nbs_dir = self.chemicals_dir / NBS_RAW_SUBDIR
        self.futures_inventory_dir = self.chemicals_dir / FUTURES_INVENTORY_RAW_SUBDIR
        self.futures_hold_rank_dir = self.chemicals_dir / FUTURES_HOLD_RANK_RAW_SUBDIR
        self.capacity_dir = self.chemicals_dir / CAPACITY_RAW_SUBDIR

        self.legacy_market_csv = self.chemicals_dir / CHEMICAL_MARKET_LEGACY_FILENAME
        self.standard_market_csv = self.chemicals_dir / CHEMICAL_MARKET_STANDARD_FILENAME
        self.market_csv = (
            self.standard_market_csv
            if self.standard_market_csv.exists()
            else self.legacy_market_csv
        )
        self.weekly_survey_csv = self.operating_rates_dir / WEEKLY_SURVEY_RAW_FILENAME
        self.weekly_sources_manifest = self.operating_rates_dir / WEEKLY_SOURCES_RAW_FILENAME
        self.spread_csv = self.chemicals_dir / SPREAD_RAW_FILENAME
        self.nbs_soda_ash_csv = self.nbs_dir / NBS_SODA_ASH_RAW_FILENAME
        self.chemicals_parquet = self.chemicals_dir / CHEMICALS_RAW_FILENAME
        self.capacity_parquet = self.chemicals_parquet


__all__ = [
    "CAPACITY_RAW_FILENAME",
    "CAPACITY_RAW_SUBDIR",
    "CHEMICALS_RAW_FILENAME",
    "CHEMICALS_RAW_SUBDIR",
    "CHEMICAL_MARKET_LEGACY_FILENAME",
    "CHEMICAL_MARKET_RAW_FILENAME",
    "CHEMICAL_MARKET_STANDARD_FILENAME",
    "FUTURES_HOLD_RANK_RAW_SUBDIR",
    "FUTURES_INVENTORY_RAW_SUBDIR",
    "NBS_RAW_SUBDIR",
    "NBS_SODA_ASH_RAW_FILENAME",
    "OPERATING_RATES_RAW_SUBDIR",
    "PPI_RAW_SUBDIR",
    "SPREAD_RAW_FILENAME",
    "WEEKLY_SOURCES_RAW_FILENAME",
    "WEEKLY_SURVEY_RAW_FILENAME",
    "ChemicalsRawPaths",
]
