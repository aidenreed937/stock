"""国家能源局 (NEA) 官网通报克制爬虫与 RAW 快照归档。"""

from __future__ import annotations

import gzip
import json
import logging
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from stock_data.fetcher.energy.cn_nea.constants import (
    NEA_BASE_URL,
    NEA_HEADERS,
    NEA_HISTORICAL_URLS,
    NEA_SCAN_CHANNELS,
)
from stock_data.fetcher.energy.cn_nea.parser import extract_period_from_title
from stock_data.fetcher.energy.common import (
    DEFAULT_RAW_ENERGY_DIR,
    now_utc_iso,
    save_raw_energy_snapshot,
)

logger = logging.getLogger(__name__)


class CnNeaCrawler:
    """国家能源局《全国电力工业统计数据》轻量与克制爬虫。"""

    def __init__(
        self,
        raw_dir: Path | str = DEFAULT_RAW_ENERGY_DIR,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.nea_raw_dir = self.raw_dir / "cn_nea"
        self.nea_raw_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_file = self.nea_raw_dir / "bulletins_manifest.json.gz"

    def fetch_bulletins(self) -> list[dict[str, Any]]:
        """扫描官网发布列表，下载新通报 HTML 快照并返回通报列表。

        Returns:
            list[dict[str, Any]]: 包含 period, html_content, url, collected_at 的字典列表
        """
        manifest = self._load_manifest()
        newly_fetched = False

        # 1. 扫描官网各发布频道 (抓取最新通报)
        for scan_url in NEA_SCAN_CHANNELS:
            try:
                logger.info("正在扫描国家能源局官网发布列表: %s", scan_url)
                r = requests.get(scan_url, headers=NEA_HEADERS, timeout=10)
                if r.status_code != 200:
                    continue
                r.encoding = "utf-8"
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    title = a.get_text(strip=True)
                    if "全国电力统计数据" in title or "全国电力工业统计数据" in title:
                        href = str(a["href"]).strip()
                        full_url = (
                            href
                            if href.startswith("http")
                            else f"{NEA_BASE_URL}/{href.lstrip('/')}"
                        )
                        period, _ = extract_period_from_title(title)
                        if period and period not in manifest:
                            if self._download_and_record_bulletin(
                                period, title, full_url, manifest
                            ):
                                newly_fetched = True
            except Exception as e:
                logger.debug("扫描频道异常 (%s): %s", scan_url, e)

        # 2. 补齐已验证的历史各月份通报直链
        for hist_url in NEA_HISTORICAL_URLS:
            try:
                # 简单根据 URL 快速探测是否需要下载
                doc_html = self._download_article_html(hist_url)
                if doc_html:
                    soup = BeautifulSoup(doc_html, "html.parser")
                    title_el = soup.find(["h1", "title", "h2"])
                    title = title_el.get_text(strip=True) if title_el else ""
                    period, _ = extract_period_from_title(title)
                    if not period:
                        period, _ = extract_period_from_title(doc_html[:300])
                    if period and period not in manifest:
                        filename = f"power_stats_{period.replace('-', '_')}.html"
                        save_raw_energy_snapshot(
                            source_name="cn_nea",
                            snapshot_filename=filename,
                            content=doc_html,
                            base_dir=self.raw_dir,
                        )
                        manifest[period] = {
                            "period": period,
                            "title": title,
                            "url": hist_url,
                            "filename": filename,
                            "collected_at": now_utc_iso(),
                        }
                        newly_fetched = True
            except Exception as e:
                logger.debug("历史直链拉取跳过 (%s): %s", hist_url, e)

        if newly_fetched:
            self._save_manifest(manifest)

        # 加载本地所有已归档的 HTML 快照
        return self._load_all_local_snapshots(manifest)

    def _download_and_record_bulletin(
        self,
        period: str,
        title: str,
        url: str,
        manifest: dict[str, dict[str, Any]],
    ) -> bool:
        """下载单篇通报并写入 RAW 快照与 manifest。"""
        doc_html = self._download_article_html(url)
        if not doc_html:
            return False
        filename = f"power_stats_{period.replace('-', '_')}.html"
        save_raw_energy_snapshot(
            source_name="cn_nea",
            snapshot_filename=filename,
            content=doc_html,
            base_dir=self.raw_dir,
        )
        manifest[period] = {
            "period": period,
            "title": title,
            "url": url,
            "filename": filename,
            "collected_at": now_utc_iso(),
        }
        logger.info("已下载并归档国家能源局通报 [%s]: %s", period, filename)
        return True

    def _download_article_html(self, url: str) -> str | None:
        """下载单个通报正文 HTML。"""
        try:
            res = requests.get(url, headers=NEA_HEADERS, timeout=10)
            if res.status_code == 200:
                res.encoding = "utf-8"
                return res.text
        except Exception as e:
            logger.warning("下载通报页面失败 (%s): %s", url, e)
        return None

    def _load_all_local_snapshots(
        self,
        manifest: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """从本地磁盘读取所有 HTML 快照内容。"""
        results: list[dict[str, Any]] = []

        # 1. 优先根据 manifest 读取
        for period, meta in manifest.items():
            fn = meta.get("filename")
            if fn:
                p = self.nea_raw_dir / fn
                if p.exists():
                    results.append(
                        {
                            "period": period,
                            "url": meta.get("url", ""),
                            "html_content": p.read_text(encoding="utf-8"),
                            "collected_at": meta.get("collected_at", ""),
                        }
                    )

        # 2. 补漏: 扫描目录下的其他 power_stats_*.html
        for html_file in self.nea_raw_dir.glob("power_stats_*.html"):
            stem = html_file.stem
            # 解析 power_stats_YYYY_MM
            parts = stem.split("_")
            if len(parts) >= 4:
                p_str = f"{parts[2]}-{parts[3]}"
                if not any(r["period"] == p_str for r in results):
                    results.append(
                        {
                            "period": p_str,
                            "url": "",
                            "html_content": html_file.read_text(encoding="utf-8"),
                            "collected_at": now_utc_iso(),
                        }
                    )

        results.sort(key=lambda x: x["period"])
        return results

    def _load_manifest(self) -> dict[str, dict[str, Any]]:
        """读取通报元数据索引。"""
        if not self.manifest_file.exists():
            return {}
        try:
            with gzip.open(self.manifest_file, "rt", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    return loaded
                return {}
        except Exception:
            return {}

    def _save_manifest(self, data: dict[str, dict[str, Any]]) -> None:
        """持久化通报元数据索引。"""
        try:
            with gzip.open(self.manifest_file, "wt", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("保存 NEA manifest 异常: %s", e)
