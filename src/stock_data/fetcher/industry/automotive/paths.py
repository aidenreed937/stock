"""新能源汽车产业 RAW 快照与输入文件的统一路径布局。"""

from __future__ import annotations

from pathlib import Path

AUTOMOTIVE_RAW_SUBDIR = "automotive"
AUTOMOTIVE_CPCA_RAW_SUBDIR = f"{AUTOMOTIVE_RAW_SUBDIR}/cpca"
AUTOMOTIVE_CABIA_RAW_SUBDIR = f"{AUTOMOTIVE_RAW_SUBDIR}/cabia"


class AutomotiveRawPaths:
    """基于调用方传入的 RAW 根目录解析汽车产业相关路径。

    源端快照统一放在 ``automotive`` 下，同时保留历史 ``cpca`` / ``cabia`` 目录
    作为离线回放输入；标准化 RAW/Curated 表由端点 runner 统一落盘为 Parquet。
    """

    def __init__(self, raw_dir: Path | str) -> None:
        self.raw_root = Path(raw_dir)
        self.automotive_dir = self.raw_root / AUTOMOTIVE_RAW_SUBDIR
        self.cpca_dir = self.automotive_dir / "cpca"
        self.cabia_dir = self.automotive_dir / "cabia"
        self.legacy_cpca_dir = self.raw_root / "cpca"
        self.legacy_cabia_dir = self.raw_root / "cabia"

        self.cpca_dirs = (self.cpca_dir, self.legacy_cpca_dir)
        self.cabia_dirs = (self.cabia_dir, self.legacy_cabia_dir)

    @staticmethod
    def _first_existing(candidates: tuple[Path, ...]) -> Path:
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]

    def _resolve_file(self, filename: str, directories: tuple[Path, ...]) -> Path:
        return self._first_existing(tuple(directory / filename for directory in directories))

    @property
    def cpca_nev_matrix_csv(self) -> Path:
        """返回 CPCA 新能源批发二维矩阵，优先新布局。"""
        return self._resolve_file("cpca_nev_wholesale_matrix.csv", self.cpca_dirs)

    @property
    def cpca_total_matrix_csv(self) -> Path:
        """返回 CPCA 全部批发二维矩阵，优先新布局。"""
        return self._resolve_file("cpca_total_wholesale_matrix.csv", self.cpca_dirs)

    @property
    def live_snapshot(self) -> Path:
        """返回 AkShare 乘联会响应的本地压缩快照路径。"""
        return self.cpca_dir / "nev_sales_live.json.gz"


__all__ = [
    "AUTOMOTIVE_CABIA_RAW_SUBDIR",
    "AUTOMOTIVE_CPCA_RAW_SUBDIR",
    "AUTOMOTIVE_RAW_SUBDIR",
    "AutomotiveRawPaths",
]
