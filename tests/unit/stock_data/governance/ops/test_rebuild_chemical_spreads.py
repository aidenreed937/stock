"""chemical_spreads 配置驱动重算与物化工具测试。

引擎计算本身由 ``test_spread_engine.py`` 覆盖；这里只验证物化工具的落盘契约：
预览不写盘、写盘前备份原文件、目标表为引擎输出。
"""

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from stock_data.fetcher.industry.chemicals.collectors.spreads import ChemicalSpreadCalculator
from stock_data.fetcher.industry.chemicals.schemas import SPREAD_SCHEMA
from stock_data.governance.ops.rebuild_chemical_spreads import rebuild_chemical_spreads


def _computed_frame() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "trade_date": date(2026, 10, 19),
                "product_name": "纯碱",
                "symbol": "SA",
                "process_type": "联碱法双吨",
                "product_price_cny": 1050.0,
                "byproduct_price_cny": 780.0,
                "raw_material_cost_cny": 700.0,
                "spread_margin_cny": 680.0,
                "cash_breakeven_cost_cny": 370.0,
                "margin_regime": "high_profit",
                "source": "config_computed",
                "release_date": date(2026, 10, 19),
                "collected_at": "2026-10-20T00:00:00+00:00",
            },
            {
                "trade_date": date(2026, 10, 19),
                "product_name": "尿素",
                "symbol": "UR",
                "process_type": "煤制尿素",
                "product_price_cny": 1732.5,
                "byproduct_price_cny": 0.0,
                "raw_material_cost_cny": 1170.0,
                "spread_margin_cny": 405.3,
                "cash_breakeven_cost_cny": 1327.0,
                "margin_regime": "high_profit",
                "source": "config_computed",
                "release_date": date(2026, 10, 19),
                "collected_at": "2026-10-20T00:00:00+00:00",
            },
        ],
        schema=SPREAD_SCHEMA,
    )


@pytest.fixture
def patched_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ChemicalSpreadCalculator, "build_historical_spreads", lambda self: _computed_frame()
    )


@pytest.mark.usefixtures("patched_engine")
def test_preview_does_not_touch_target(tmp_path: Path) -> None:
    curated_dir = tmp_path / "curated" / "industry"
    target = curated_dir / "chemical_spreads.parquet"

    report = rebuild_chemical_spreads(tmp_path / "raw" / "industry", curated_dir, apply=False)

    assert report["applied"] is False
    assert report["rows"] == 2
    assert report["products"] == 2
    assert not target.exists()


@pytest.mark.usefixtures("patched_engine")
def test_apply_backs_up_existing_and_writes_computed_rows(tmp_path: Path) -> None:
    curated_dir = tmp_path / "curated" / "industry"
    curated_dir.mkdir(parents=True)
    target = curated_dir / "chemical_spreads.parquet"
    pl.DataFrame(
        {"product_name": ["纯碱"], "trade_date": ["2019-01-04"], "process_type": ["联碱法双吨"]}
    ).write_parquet(target)

    report = rebuild_chemical_spreads(tmp_path / "raw" / "industry", curated_dir, apply=True)

    assert report["applied"] is True
    backup = target.with_suffix(".bak.parquet")
    assert backup.exists()
    # 备份保留原始存量内容，目标表替换为引擎计算结果
    assert pl.read_parquet(backup)["trade_date"].to_list() == ["2019-01-04"]
    written = pl.read_parquet(target)
    assert written.columns == list(SPREAD_SCHEMA)
    assert written.height == 2
    assert set(written["product_name"].to_list()) == {"纯碱", "尿素"}


@pytest.mark.usefixtures("patched_engine")
def test_apply_on_empty_dir_skips_backup(tmp_path: Path) -> None:
    curated_dir = tmp_path / "curated" / "industry"

    rebuild_chemical_spreads(tmp_path / "raw" / "industry", curated_dir, apply=True)

    target = curated_dir / "chemical_spreads.parquet"
    assert target.exists()
    assert not target.with_suffix(".bak.parquet").exists()
