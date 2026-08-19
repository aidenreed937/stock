"""数据运行时目录上下文。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stock_data.core.settings import DataSettings


@dataclass(frozen=True, slots=True)
class DataRuntimeContext:
    """一次运行中共享的 RAW、Curated、缓存与数据根目录。"""

    data_root: Path
    raw_root: Path
    curated_root: Path
    cache_root: Path

    @classmethod
    def from_settings(cls, settings: DataSettings | None = None) -> DataRuntimeContext:
        """从配置创建目录上下文。"""
        if settings is None:
            from stock_data.core.settings import data_settings

            settings = data_settings

        return cls(
            data_root=settings.data_dir,
            raw_root=settings.raw_data_dir,
            curated_root=settings.curated_data_dir,
            cache_root=settings.cache_dir,
        )

    @classmethod
    def from_root(cls, data_root: Path | str) -> DataRuntimeContext:
        """从统一数据根目录创建上下文。"""
        root = Path(data_root)
        return cls(
            data_root=root,
            raw_root=root / "raw",
            curated_root=root / "curated",
            cache_root=root / "cache",
        )

    def ensure_directories(self) -> None:
        """确保运行所需的目录存在。"""
        for path in (self.data_root, self.raw_root, self.curated_root, self.cache_root):
            path.mkdir(parents=True, exist_ok=True)
