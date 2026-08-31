"""IRENA 数据集下载与本地 RAW 快照客户端 (IrenaClient)。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Final

import requests

from stock_data.fetcher.energy.common import DEFAULT_RAW_ENERGY_DIR

logger = logging.getLogger(__name__)

DEFAULT_IRENA_RAW_DIR: Final[Path] = DEFAULT_RAW_ENERGY_DIR / "irena"


class IrenaClient:
    """负责从 IRENA 官方抓取/下载数据集并管理 RAW 快照。"""

    def __init__(self, raw_dir: Path | None = None) -> None:
        self.raw_dir = raw_dir or DEFAULT_IRENA_RAW_DIR
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def get_raw_csv_files(self) -> list[Path]:
        """获取本地所有 IRENA 原始 CSV 快照文件。"""
        if not self.raw_dir.exists():
            return []
        files = list(self.raw_dir.glob("*.csv"))
        files.sort()
        return files

    def download_from_pxweb(
        self, filename: str = "renewable_capacity_historical.csv"
    ) -> Path | None:
        """通过 IRENA PxWeb API 批量下载 2000-2025 年全球全量细分装机数据并落盘至 RAW 目录。"""
        table_url = (
            "https://pxweb.irena.org/api/v1/en/IRENASTAT/"
            "Power Capacity and Generation/Country_ELECCAP_2026_H1_v-PX 1.px"
        )
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Content-Type": "application/json",
        }

        try:
            logger.info("正在获取 IRENA PxWeb 数据集维度元数据...")
            meta_resp = requests.get(table_url, headers=headers, timeout=15)
            if meta_resp.status_code != 200:
                logger.warning("获取 IRENA 元数据失败: status=%d", meta_resp.status_code)
                return None

            meta = meta_resp.json()
            vars_dict = {v["code"]: v for v in meta["variables"]}
            countries = vars_dict["Country/area"]["values"]
            technologies = vars_dict["Technology"]["values"]
            grid_types = vars_dict["Grid connection"]["values"]
            years = vars_dict["Year"]["values"]

            logger.info(
                "IRENA 维度解析成功: %d 个国家, %d 种技术, %d 个年份, 开始分批拉取...",
                len(countries),
                len(technologies),
                len(years),
            )

            import csv
            import io

            chunk_size = 4
            all_rows: list[list[str]] = []
            header_saved = False
            out_file = self.raw_dir / filename

            for i in range(0, len(technologies), chunk_size):
                tech_chunk = technologies[i : i + chunk_size]
                logger.debug(
                    "正在拉取技术切片 [%d-%d/%d]...",
                    i + 1,
                    min(i + chunk_size, len(technologies)),
                    len(technologies),
                )
                query: dict[str, Any] = {
                    "query": [
                        {
                            "code": "Country/area",
                            "selection": {"filter": "item", "values": countries},
                        },
                        {
                            "code": "Technology",
                            "selection": {"filter": "item", "values": tech_chunk},
                        },
                        {
                            "code": "Grid connection",
                            "selection": {"filter": "item", "values": grid_types},
                        },
                        {"code": "Year", "selection": {"filter": "item", "values": years}},
                    ],
                    "response": {"format": "csv"},
                }
                r = requests.post(table_url, headers=headers, json=query, timeout=40)
                if r.status_code == 200:
                    reader = list(csv.reader(io.StringIO(r.text)))
                    if reader:
                        if not header_saved:
                            all_rows.append(reader[0])
                            header_saved = True
                        all_rows.extend(reader[1:])
                else:
                    logger.warning("技术切片拉取失败: %d", r.status_code)

            if len(all_rows) > 1:
                with open(out_file, "w", encoding="utf-8", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerows(all_rows)
                logger.info(
                    "IRENA 全量数据集已成功写入 RAW 快照: %s (共 %d 行)",
                    out_file.name,
                    len(all_rows) - 1,
                )
                return out_file
            return None
        except Exception as e:
            logger.error("IRENA PxWeb 下载异常: %s", e)
            return None

    def fetch_or_load_dataset(self) -> list[Path]:
        """获取数据集文件，本地无快照时自动触发 PxWeb 批量下载。"""
        existing_files = self.get_raw_csv_files()
        if existing_files:
            return existing_files

        # 本地缺失时自动触发 PxWeb 全量下载
        logger.info("本地未发现 IRENA RAW 快照，尝试自动从官方 PxWeb 接口下载全量历史数据...")
        downloaded = self.download_from_pxweb()
        if downloaded and downloaded.exists():
            return [downloaded]

        return existing_files
