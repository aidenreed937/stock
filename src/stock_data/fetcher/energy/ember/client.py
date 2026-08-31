"""Ember 开放数据集网络下载与 RAW 快照客户端。"""

from __future__ import annotations

import logging
from pathlib import Path

import requests

from stock_data.fetcher.energy.common import (
    DEFAULT_RAW_ENERGY_DIR,
    save_raw_energy_snapshot,
)
from stock_data.fetcher.energy.ember.constants import EMBER_YEARLY_FULL_URL

logger = logging.getLogger(__name__)


class EmberClient:
    """Ember 官方开放数据集下载客户端。"""

    def __init__(self, raw_dir: Path | str = DEFAULT_RAW_ENERGY_DIR) -> None:
        self.raw_dir = Path(raw_dir)
        self.ember_raw_dir = self.raw_dir / "ember"
        self.ember_raw_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot_file = self.ember_raw_dir / "yearly_full_release.csv"

    def fetch_yearly_data(self, force: bool = False) -> str:
        """获取 Ember 年度全量历史数据 CSV 文本内容。

        优先读取本地已存在的 RAW 快照；若不存在或 force=True 则从官方 CDN 下载。
        """
        if not force and self.snapshot_file.exists() and self.snapshot_file.stat().st_size > 1024:
            logger.info("读取本地 Ember 缓存快照: %s", self.snapshot_file)
            return self.snapshot_file.read_text(encoding="utf-8")

        logger.info("开始从 Ember 官方 CDN 下载全球全量发电数据集: %s", EMBER_YEARLY_FULL_URL)
        try:
            r = requests.get(EMBER_YEARLY_FULL_URL, timeout=60)
            if r.status_code == 200:
                content = r.text
                save_raw_energy_snapshot(
                    source_name="ember",
                    snapshot_filename="yearly_full_release.csv",
                    content=content,
                    base_dir=self.raw_dir,
                )
                logger.info(
                    "成功下载并保存 Ember RAW 快照: %s (大小: %.1f KB)",
                    self.snapshot_file,
                    len(content) / 1024.0,
                )
                return content
            logger.error("下载 Ember 数据集失败, HTTP status=%d", r.status_code)
        except Exception as e:
            logger.error("请求 Ember 官方 CDN 异常: %s", e)
            if self.snapshot_file.exists():
                logger.info("降级读取本地已有快照: %s", self.snapshot_file)
                return self.snapshot_file.read_text(encoding="utf-8")

        return ""
