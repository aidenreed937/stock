"""云计算产业 RAW 快照与结构化事实的统一路径布局。"""

from __future__ import annotations

from pathlib import Path

CLOUD_RAW_SUBDIR = "cloud"
SEC_EDGAR_RAW_SUBDIR = "sec_edgar"
CLOUD_CAPEX_RAW_FILENAME = "cloud_capex_quarterly.parquet"


class CloudRawPaths:
    """基于调用方传入的 RAW 根目录解析云 CapEx 相关路径。"""

    def __init__(self, raw_dir: Path | str) -> None:
        self.raw_root = Path(raw_dir)
        self.cloud_dir = self.raw_root / CLOUD_RAW_SUBDIR
        self.sec_edgar_dir = self.cloud_dir / SEC_EDGAR_RAW_SUBDIR
        self.cloud_capex_raw = self.cloud_dir / CLOUD_CAPEX_RAW_FILENAME


__all__ = [
    "CLOUD_CAPEX_RAW_FILENAME",
    "CLOUD_RAW_SUBDIR",
    "SEC_EDGAR_RAW_SUBDIR",
    "CloudRawPaths",
]
