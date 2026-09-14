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
DATATRACK_RAW_SUBDIR = "datatrack"
TAIWAN_MEMORY_RAW_SUBDIR = "taiwan_memory"

INVENTORY_RAW_FILENAME = "idm_quarterly_financials_10y.csv"
TSMC_REVENUE_HTML_SUBDIR = "tsmc"
TSMC_MONTHLY_HTML_FILENAME = "tsmc_monthly_revenue_{year}.html.gz"

# 半导体 5 大产研分类子目录
SEMICONDUCTOR_SALES_RAW_SUBDIR = f"{SEMICONDUCTOR_RAW_SUBDIR}/sales"
SEMICONDUCTOR_INVENTORY_RAW_SUBDIR = f"{SEMICONDUCTOR_RAW_SUBDIR}/inventory"
SEMICONDUCTOR_EQUIPMENT_RAW_SUBDIR = f"{SEMICONDUCTOR_RAW_SUBDIR}/equipment"
SEMICONDUCTOR_CAPACITY_RAW_SUBDIR = f"{SEMICONDUCTOR_RAW_SUBDIR}/capacity"
SEMICONDUCTOR_PRICE_RAW_SUBDIR = f"{SEMICONDUCTOR_RAW_SUBDIR}/price"

SEMICONDUCTOR_SALES_CURATED_SUBDIR = SEMICONDUCTOR_SALES_RAW_SUBDIR
SEMICONDUCTOR_INVENTORY_CURATED_SUBDIR = SEMICONDUCTOR_INVENTORY_RAW_SUBDIR
SEMICONDUCTOR_EQUIPMENT_CURATED_SUBDIR = SEMICONDUCTOR_EQUIPMENT_RAW_SUBDIR
SEMICONDUCTOR_CAPACITY_CURATED_SUBDIR = SEMICONDUCTOR_CAPACITY_RAW_SUBDIR
SEMICONDUCTOR_PRICE_CURATED_SUBDIR = SEMICONDUCTOR_PRICE_RAW_SUBDIR


class SemiconductorRawPaths:
    """基于调用方传入的 RAW 根目录解析半导体相关路径。

    `semiconductors` 复数目录是历史快照布局，必须保留以支持离线回放；新端点
    的结构化 RAW 表和新源快照统一放在 `semiconductor` 单数目录。
    """

    def __init__(self, raw_dir: Path | str) -> None:
        self.raw_root = Path(raw_dir)
        self.semiconductor_dir = self.raw_root / SEMICONDUCTOR_RAW_SUBDIR
        self.legacy_semiconductor_dir = self.raw_root / LEGACY_SEMICONDUCTOR_RAW_SUBDIR
        self.legacy_sia_dir = self.raw_root / SIA_RAW_SUBDIR
        self.canonical_sia_dir = self.semiconductor_dir / SIA_RAW_SUBDIR
        self.sia_dir = (
            self.canonical_sia_dir
            if self.canonical_sia_dir.exists() or not self.legacy_sia_dir.exists()
            else self.legacy_sia_dir
        )
        self.canonical_foundry_dir = self.semiconductor_dir / FOUNDRY_RAW_SUBDIR
        self.legacy_foundry_dir = self.legacy_semiconductor_dir / FOUNDRY_RAW_SUBDIR
        self.foundry_dir = (
            self.canonical_foundry_dir
            if self.canonical_foundry_dir.exists() or not self.legacy_foundry_dir.exists()
            else self.legacy_foundry_dir
        )

        self.canonical_inventory_dir = self.semiconductor_dir / INVENTORY_RAW_SUBDIR
        self.legacy_inventory_dir = self.legacy_semiconductor_dir / INVENTORY_RAW_SUBDIR
        self.inventory_dir = (
            self.canonical_inventory_dir
            if self.canonical_inventory_dir.exists() or not self.legacy_inventory_dir.exists()
            else self.legacy_inventory_dir
        )
        self.inventory_sec_dir = self.inventory_dir / "sec_submissions"
        self.inventory_csv = self.inventory_dir / INVENTORY_RAW_FILENAME

        self.canonical_lead_time_dir = self.semiconductor_dir / LEAD_TIME_RAW_SUBDIR
        self.legacy_lead_time_dir = self.raw_root / LEAD_TIME_RAW_SUBDIR
        self.lead_time_dir = (
            self.canonical_lead_time_dir
            if self.canonical_lead_time_dir.exists() or not self.legacy_lead_time_dir.exists()
            else self.legacy_lead_time_dir
        )

        self.canonical_tsmc_monthly_html_dir = self.semiconductor_dir / TSMC_REVENUE_HTML_SUBDIR
        self.legacy_tsmc_monthly_html_dir = self.raw_root / TSMC_REVENUE_HTML_SUBDIR
        self.tsmc_monthly_html_dir = (
            self.canonical_tsmc_monthly_html_dir
            if self.canonical_tsmc_monthly_html_dir.exists()
            or not self.legacy_tsmc_monthly_html_dir.exists()
            else self.legacy_tsmc_monthly_html_dir
        )

        self.seaj_dir = self.semiconductor_dir / SEAJ_RAW_SUBDIR
        self.semi_dir = self.semiconductor_dir / SEMI_RAW_SUBDIR
        self.datatrack_dir = self.semiconductor_dir / DATATRACK_RAW_SUBDIR
        self.taiwan_memory_dir = self.semiconductor_dir / TAIWAN_MEMORY_RAW_SUBDIR
        self.korea_memory_csv = self.semiconductor_dir / "korea_memory_raw.csv"
        self.tsmc_adv_pkg_revenue_csv = self.semiconductor_dir / "tsmc_adv_pkg_revenue_raw.csv"
        self.cowos_estimates_csv = self.semiconductor_dir / "cowos_capacity_estimates_raw.csv"
        self.tsmc_filings_dir = self.semiconductor_dir / "tsmc_filings"
        self.cowos_estimates_sources_dir = self.semiconductor_dir / "cowos_estimates_sources"
