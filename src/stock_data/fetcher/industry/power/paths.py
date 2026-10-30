"""光伏产业 RAW 快照与端点输入文件的统一路径布局。"""

from __future__ import annotations

from pathlib import Path

POWER_RAW_SUBDIR = "power"
POWER_NEA_RAW_SUBDIR = f"{POWER_RAW_SUBDIR}/nea"
POWER_NBS_RAW_SUBDIR = f"{POWER_RAW_SUBDIR}/nbs"
POWER_SILICON_BRANCH_RAW_SUBDIR = f"{POWER_RAW_SUBDIR}/silicon_branch"
POWER_INFOLINK_RAW_SUBDIR = f"{POWER_RAW_SUBDIR}/infolink"


class PowerRawPaths:
    """基于调用方传入的 RAW 根目录解析光伏相关路径。

    新的源端快照统一放在 ``raw/industry/power`` 下；历史数据曾分别落在
    ``energy``、``cn_nea`` 或 ``power`` 的平铺目录中，读取时按新路径优先并
    保留这些历史候选路径，以支持离线回放和渐进迁移。
    """

    def __init__(self, raw_dir: Path | str) -> None:
        self.raw_root = Path(raw_dir)
        self.power_dir = self.raw_root / POWER_RAW_SUBDIR
        self.nea_dir = self.power_dir / "nea"
        self.nbs_dir = self.power_dir / "nbs"
        self.silicon_branch_dir = self.power_dir / "silicon_branch"
        self.infolink_dir = self.power_dir / "infolink"

        self.legacy_nea_dir = self.raw_root / "energy" / "cn_nea"
        self.legacy_nea_root_dir = self.raw_root / "cn_nea"
        self.legacy_nea_flat_dir = self.raw_root / "nea"
        self.legacy_nbs_dir = self.raw_root / "energy" / "cn_nbs"
        self.legacy_silicon_branch_dir = self.power_dir
        self.legacy_energy_dir = self.raw_root / "energy"
        self.legacy_infolink_dir = self.legacy_energy_dir

        self.legacy_nea_dirs = (
            self.legacy_nea_dir,
            self.legacy_nea_root_dir,
            self.legacy_nea_flat_dir,
        )
        self.legacy_nbs_dirs = (self.legacy_nbs_dir,)
        self.legacy_silicon_branch_dirs = (self.legacy_silicon_branch_dir,)
        self.legacy_infolink_dirs = (self.legacy_infolink_dir,)

    @staticmethod
    def _first_existing(candidates: tuple[Path, ...]) -> Path:
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]

    def _resolve_file(
        self,
        filename: str,
        canonical_dir: Path,
        legacy_dirs: tuple[Path, ...],
    ) -> Path:
        return self._first_existing(
            (canonical_dir / filename, *(directory / filename for directory in legacy_dirs))
        )

    @property
    def solar_capacity_csv(self) -> Path:
        """返回 NEA 光伏装机 CSV，优先新布局。"""
        return self._resolve_file("solar_capacity.csv", self.nea_dir, self.legacy_nea_dirs)

    @property
    def nea_bulletins_manifest(self) -> Path:
        """返回 NEA 通报索引缓存，优先新布局。"""
        return self._resolve_file("bulletins_manifest.json.gz", self.nea_dir, self.legacy_nea_dirs)

    @property
    def solar_cell_nbs_csv(self) -> Path:
        """返回 NBS 光伏电池产量 CSV，优先新布局。"""
        return self._resolve_file("nbs_solar_cell_monthly.csv", self.nbs_dir, self.legacy_nbs_dirs)

    @property
    def silicon_wafer_monthly_csv(self) -> Path:
        """返回硅业分会月度 CSV，优先新 ``silicon_branch`` 目录。"""
        return self._resolve_file(
            "silicon_wafer_monthly.csv",
            self.silicon_branch_dir,
            self.legacy_silicon_branch_dirs,
        )

    @property
    def silicon_capacity_annual_csv(self) -> Path:
        """返回年度硅料/硅片产能 CSV，优先新源端目录。"""
        return self._resolve_file(
            "polysilicon_wafer_capacity_annual.csv",
            self.silicon_branch_dir,
            (
                self.power_dir,
                self.legacy_energy_dir,
                self.raw_root,
            ),
        )

    @property
    def polysilicon_inventory_patch_csv(self) -> Path:
        """返回多晶硅库存历史校准补丁 CSV。"""
        return self._resolve_file(
            "polysilicon_inventory_patch.csv",
            self.silicon_branch_dir,
            (
                self.power_dir,
                self.legacy_energy_dir,
                self.raw_root,
            ),
        )

    @property
    def pv_price_chain_csv(self) -> Path:
        """返回 InfoLink 价格链 CSV，优先新布局。"""
        return self._resolve_file(
            "pv_price_chain_weekly.csv", self.infolink_dir, self.legacy_infolink_dirs
        )

    @property
    def infolink_live_spot_price_html(self) -> Path:
        """返回 InfoLink HTML 快照，优先新布局。"""
        return self._resolve_file(
            "infolink_live_spot_price.html", self.infolink_dir, self.legacy_infolink_dirs
        )


__all__ = [
    "POWER_INFOLINK_RAW_SUBDIR",
    "POWER_NBS_RAW_SUBDIR",
    "POWER_NEA_RAW_SUBDIR",
    "POWER_RAW_SUBDIR",
    "POWER_SILICON_BRANCH_RAW_SUBDIR",
    "PowerRawPaths",
]
