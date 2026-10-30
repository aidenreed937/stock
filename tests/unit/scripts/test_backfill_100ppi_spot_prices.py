"""backfill_100ppi_spot_prices 脚本单元测试。"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.backfill_100ppi_spot_prices import run_backfill


def test_run_backfill_offline(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    curated_dir = tmp_path / "curated"

    ppi_dir = raw_dir / "chemicals" / "100ppi"
    ppi_dir.mkdir(parents=True, exist_ok=True)

    fake_snapshot = {
        "symbol": "UR",
        "product_name": "尿素",
        "ppid": 89,
        "spec": "中小颗粒",
        "region": "山东省",
        "unit": "元/吨",
        "source": "100ppi",
        "source_url": "https://www.100ppi.com/graph/cindex.php?f=graph_ave&ppid=89&type=1&mode=3",
        "collected_at": "2026-09-16T00:00:00Z",
        "count": 2,
        "dates": ["2026-09-14", "2026-09-15"],
        "prices": [1800.0, 1802.5],
    }
    (ppi_dir / "UR.json").write_text(json.dumps(fake_snapshot), encoding="utf-8")

    curated_df, summary = run_backfill(
        raw_dir=raw_dir,
        curated_dir=curated_dir,
        symbols=["UR"],
        use_network=False,
    )

    assert len(curated_df) == 2
    assert "UR" in summary
    assert summary["UR"]["status"] == "SUCCESS"
    assert summary["UR"]["latest_price"] == 1802.5
    assert (curated_dir / "chemical_spot_price.parquet").exists()
