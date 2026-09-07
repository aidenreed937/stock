"""海关产业数据 RAW、Curated 与目录文件的统一路径布局。"""

from __future__ import annotations

from pathlib import Path

CUSTOMS_RAW_SUBDIR = "customs"
COMTRADE_RAW_SUBDIR = "comtrade"
TARIFFLINE_RAW_SUBDIR = "comtrade_tariffline"
GACC_RAW_SUBDIR = "gacc"

DEFAULT_HS_CATALOG_PATH = Path("config/data/customs/hs_codes_catalog.csv")
DEFAULT_GACC_CATALOG_PATH = Path("config/data/customs/gacc_code_catalog.csv")
DEFAULT_GACC_CODES_CSV_PATH = Path("config/data/customs/gacc_hs_codes.csv")
DEFAULT_GACC_CODES_PATH = Path("config/data/customs/gacc_hs_codes.txt")
DEFAULT_TARIFFLINE_RAW_DIR = "data/raw/industry/customs/comtrade_tariffline"
DEFAULT_CUSTOMS_CURATED_PATH = Path("data/curated/industry/customs_trade.parquet")
DEFAULT_GACC_CURATED_PATH = Path("data/curated/industry/customs_trade_gacc.parquet")


class CustomsRawPaths:
    """基于调用方传入的 RAW 根目录解析海关数据路径。"""

    def __init__(self, raw_dir: Path | str) -> None:
        self.raw_root = Path(raw_dir)
        self.customs_dir = self.raw_root / CUSTOMS_RAW_SUBDIR
        self.comtrade_dir = self.customs_dir / COMTRADE_RAW_SUBDIR
        self.tariffline_dir = self.customs_dir / TARIFFLINE_RAW_SUBDIR
        self.gacc_dir = self.customs_dir / GACC_RAW_SUBDIR


__all__ = [
    "COMTRADE_RAW_SUBDIR",
    "CUSTOMS_RAW_SUBDIR",
    "DEFAULT_CUSTOMS_CURATED_PATH",
    "DEFAULT_GACC_CATALOG_PATH",
    "DEFAULT_GACC_CODES_CSV_PATH",
    "DEFAULT_GACC_CODES_PATH",
    "DEFAULT_GACC_CURATED_PATH",
    "DEFAULT_HS_CATALOG_PATH",
    "DEFAULT_TARIFFLINE_RAW_DIR",
    "GACC_RAW_SUBDIR",
    "TARIFFLINE_RAW_SUBDIR",
    "CustomsRawPaths",
]
