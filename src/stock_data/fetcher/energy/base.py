"""全球能源数据采集器抽象基类。"""

from __future__ import annotations

import abc
import logging
from pathlib import Path
from typing import Any

from stock_data.fetcher.energy.common import (
    DEFAULT_CURATED_ENERGY_DIR,
    DEFAULT_RAW_ENERGY_DIR,
    save_raw_energy_snapshot,
)

logger = logging.getLogger(__name__)


class EnergyFetcherBase(abc.ABC):
    """全球能源多源采集器基类。"""

    source_name: str = "GENERIC_ENERGY"

    def __init__(
        self,
        raw_dir: Path | str = DEFAULT_RAW_ENERGY_DIR,
        curated_dir: Path | str = DEFAULT_CURATED_ENERGY_DIR,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.curated_dir = Path(curated_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.curated_dir.mkdir(parents=True, exist_ok=True)

    def save_raw(
        self,
        filename: str,
        content: str | bytes | dict[str, Any] | list[Any],
    ) -> Path:
        """保存原始抓取快照到 RAW 分源目录。"""
        return save_raw_energy_snapshot(
            source_name=self.source_name,
            snapshot_filename=filename,
            content=content,
            base_dir=self.raw_dir,
        )

    @abc.abstractmethod
    def collect(self) -> list[Any]:
        """执行采集并返回规范化记录列表。"""
        raise NotImplementedError
