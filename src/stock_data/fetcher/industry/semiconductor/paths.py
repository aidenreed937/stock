"""半导体产业 RAW 快照与输入文件的统一路径布局。"""

from __future__ import annotations

from pathlib import Path

SEMICONDUCTOR_RAW_SUBDIR = "semiconductor"
LEGACY_SEMICONDUCTOR_RAW_SUBDIR = "semiconductors"
SIA_RAW_SUBDIR = "sia"
LEAD_TIME_RAW_SUBDIR = "lead_time"
SEAJ_RAW_SUBDIR = "seaj"
SEMI_RAW_SUBDIR = "semi"
FOUNDRY_RAW_SUBDIR = "foundry"
INVENTORY_RAW_SUBDIR = "inventory"

INVENTORY_RAW_FILENAME = "idm_quarterly_financials_10y.csv"
TSMC_REVENUE_HTML_SUBDIR = "tsmc"
TSMC_MONTHLY_HTML_FILENAME = "tsmc_monthly_revenue_{year}.html.gz"


class SemiconductorRawPaths:
    """基于调用方传入的 RAW 根目录解析半导体相关路径。

    `semiconductors` 复数目录是历史快照布局，必须保留以支持离线回放；新端点
    的结构化 RAW 表和新源快照统一放在 `semiconductor` 单数目录。
    """

    def __init__(self, raw_dir: Path | str) -> None:
        self.raw_root = Path(raw_dir)
        self.semiconductor_dir = self.raw_root / SEMICONDUCTOR_RAW_SUBDIR
        self.legacy_semiconductor_dir = self.raw_root / LEGACY_SEMICONDUCTOR_RAW_SUBDIR
        self.sia_dir = self.raw_root / SIA_RAW_SUBDIR
        self.lead_time_dir = self.raw_root / LEAD_TIME_RAW_SUBDIR
        self.seaj_dir = self.semiconductor_dir / SEAJ_RAW_SUBDIR
        self.semi_dir = self.semiconductor_dir / SEMI_RAW_SUBDIR
        self.foundry_dir = self.legacy_semiconductor_dir / FOUNDRY_RAW_SUBDIR
        self.inventory_dir = self.legacy_semiconductor_dir / INVENTORY_RAW_SUBDIR
        self.inventory_sec_dir = self.inventory_dir / "sec_submissions"
        self.inventory_csv = self.inventory_dir / INVENTORY_RAW_FILENAME
        self.tsmc_monthly_html_dir = self.raw_root / TSMC_REVENUE_HTML_SUBDIR
