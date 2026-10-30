"""纯碱 (Soda Ash / SA) 全景基本面对账管线运行入口。

核心管线依托 ``stock_analytics.pipelines.soda_ash``（配置驱动 +
ArtifactStore runs/latest + manifest.json + 数据驱动研报，含周期股交易门禁）。
产物统一落盘至 ``data/analytics/soda_ash``。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from stock_analytics.pipelines.soda_ash import (
    calculate_implied_shipment_rate,
    run_soda_ash_pipeline,
)

__all__ = ["SodaAshMvpPipeline", "calculate_implied_shipment_rate"]

_DEFAULT_OUT_DIR = Path("data/analytics/soda_ash")


class SodaAshMvpPipeline:
    """兼容壳：委托新管线并把产物复制回旧扁平路径。"""

    def __init__(
        self,
        config_dir: Path | str | None = None,
        raw_dir: Path | str | None = None,
        curated_dir: Path | str | None = None,
        out_dir: Path | str = _DEFAULT_OUT_DIR,
    ) -> None:
        del config_dir, raw_dir, curated_dir  # 兼容旧签名；路径已由 soda_ash.yaml 接管
        self.out_dir = Path(out_dir)

    def run(self) -> tuple[Any, Path, Path]:
        """运行新管线并把产物发布到旧路径（soda_ash_mvp_panorama.csv/md）。"""
        result = run_soda_ash_pipeline(output_dir=self.out_dir)
        run_dir = result.paths.run_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)

        csv_path = self.out_dir / "soda_ash_mvp_panorama.csv"
        md_path = self.out_dir / "soda_ash_mvp_panorama.md"
        shutil.copy2(run_dir / "soda_ash_panorama.csv", csv_path)
        shutil.copy2(run_dir / "soda_ash_panorama.md", md_path)
        company_src = run_dir / "soda_ash_company_panel.csv"
        if company_src.exists():
            shutil.copy2(company_src, self.out_dir / "soda_ash_company_panel.csv")
        return result.panorama, csv_path, md_path


if __name__ == "__main__":
    pipeline = SodaAshMvpPipeline()
    _, csv_p, md_p = pipeline.run()
    print(f"纯碱 MVP 管线运行完成:\n- CSV: {csv_p}\n- MD:  {md_p}")
