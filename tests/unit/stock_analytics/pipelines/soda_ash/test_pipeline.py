"""纯碱全景管线运行与 ArtifactStore 落盘测试。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from stock_analytics.pipelines.soda_ash.config import InputsConfig, SodaAshConfig
from stock_analytics.pipelines.soda_ash.pipeline import (
    SodaAshPipeline,
    load_latest_soda_ash_panorama,
)
from stock_data.core.runtime import DataRuntimeContext


class FakeCatalog:
    """鸭子类型 DataCatalog。"""

    def __init__(self, datasets: dict[str, pl.DataFrame]) -> None:
        self._datasets = datasets

    def load_dataset(self, dataset: str) -> pl.DataFrame:
        if dataset not in self._datasets:
            raise KeyError(f"fake dataset missing: {dataset}")
        return self._datasets[dataset]


def _write_nbs_csv(path: Path, header: str, rows: list[str]) -> None:
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")


def test_pipeline_run_writes_artifacts_and_latest(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    nbs_dir = tmp_path / "nbs"
    nbs_dir.mkdir(parents=True)
    _write_nbs_csv(
        nbs_dir / "soda.csv",
        "report_month,output_current,output_yoy",
        ["2024-01,200.0,5.0", "2024-02,210.0,6.0"],
    )
    _write_nbs_csv(
        nbs_dir / "glass.csv",
        "report_month,output_current,output_yoy",
        ["2024-01,7000.0,3.0", "2024-02,7100.0,4.0"],
    )
    capacity_path = tmp_path / "capacity.yaml"
    capacity_path.write_text(
        "projects:\n  - company: 远兴能源\n    plant_name: 阿拉善一期\n"
        "    capacity_w_tons: 150.0\n    technology: 天然碱\n    status: 已投产\n"
        "    actual_start: '2023-06'\n    source: 公告\n",
        encoding="utf-8",
    )

    datasets = {
        "customs_trade_gacc": pl.DataFrame(
            {
                "period": ["2024-01-10", "2024-02-10"],
                "hs_code": ["28362000", "28362000"],
                "product_key": ["soda_ash", "soda_ash"],
                "export_quantity": [10.0, 20.0],
                "export_value_usd": [1000.0, 2000.0],
                "yoy_growth": [1.0, 2.0],
            }
        ),
        "futures_inventory": pl.DataFrame(
            {
                "trade_date": ["2024-01-31", "2024-02-29"],
                "symbol": ["SA", "SA"],
                "inventory": [100.0, 120.0],
            }
        ),
        "chemical_weekly_survey": pl.DataFrame(
            {
                "report_date": ["2024-01-26", "2024-02-23"],
                "product_name": ["纯碱", "纯碱"],
                "factory_inventory_w_tons": [90.0, 95.0],
                "weekly_output_w_tons": [50.0, 50.0],
                "shipment_rate_pct": [99.0, 98.0],
                "operating_rate_pct": [80.0, 80.0],
            }
        ),
        "chemical_spreads": pl.DataFrame(
            {
                "trade_date": ["2024-01-31", "2024-02-29"],
                "symbol": ["SA", "SA"],
                "product_price_cny": [1800.0, 1780.0],
                "byproduct_price_cny": [800.0, 800.0],
                "spread_margin_cny": [50.0, 40.0],
                "margin_regime": ["near_breakeven", "near_breakeven"],
            }
        ),
        "futures_daily": pl.DataFrame(
            {
                "trade_date": ["2024-01-31", "2024-02-29"],
                "symbol": ["SA", "SA"],
                "settle": [1700.0, 1700.0],
            }
        ),
        "futures_hold_rank": pl.DataFrame(
            {
                "trade_date": ["2024-01-31", "2024-02-29"],
                "symbol": ["SA", "SA"],
                "top20_net_long_vol": [1000.0, 1100.0],
                "smart_money_bias": ["neutral", "neutral"],
            }
        ),
        "chemical_spot_price": pl.DataFrame(
            {
                "trade_date": ["2024-02-29"],
                "symbol": ["SA"],
                "spot_price_cny": [1780.0],
            }
        ),
        "mart/soda_ash_company_panel": pl.DataFrame(
            {
                "trade_date": ["2024-02-29"],
                "symbol": ["600328.SH"],
                "company_name": ["中盐化工"],
                "process_type": ["solvay_and_hou"],
                "fin_report_date": ["2023-09-30"],
                "total_revenue": [1.0e10],
                "net_profit_attr_p": [-2.0e8],
                "assets_impair_loss": [1.0e7],
                "inventories": [1.0e9],
                "soda_revenue_share_approx": [0.49],
                "close": [8.0],
                "total_mv": [8.0e10],
                "pb": [0.79],
                "pb_percentile_10y": [1.7],
                "pe_ttm": [-20.0],
                "valuation_regime": ["deep_value_trough"],
            }
        ),
    }
    fake_cat = FakeCatalog(datasets)
    config = SodaAshConfig(
        artifact_root=str(tmp_path / "analytics"),
        inputs=InputsConfig(
            capacity_projects=str(capacity_path),
            trading_gates="config/industry/chemicals/soda_ash/trading_gates.yaml",
            nbs_soda_ash_csv=str(nbs_dir / "soda.csv"),
            nbs_plate_glass_csv=str(nbs_dir / "glass.csv"),
        ),
    )
    pipeline = SodaAshPipeline(
        runtime=DataRuntimeContext.from_root(data_dir),
        config=config,
        catalog_factory=lambda source: fake_cat,
    )

    result = pipeline.run(update_latest=True)

    assert result.as_of_date.isoformat() == "2024-02-01"
    assert (result.paths.run_dir / "soda_ash_panorama.parquet").exists()
    assert (result.paths.run_dir / "soda_ash_panorama.csv").exists()
    assert (result.paths.run_dir / "soda_ash_panorama.md").exists()
    assert (result.paths.run_dir / "soda_ash_company_panel.parquet").exists()
    assert (result.paths.run_dir / "manifest.json").exists()
    assert result.manifest["artifact_type"] == "soda_ash_panorama"
    assert result.manifest["trading_gates"]["left_side_odds"]["triggered"] is True

    latest_dir = result.paths.latest_dir
    assert (latest_dir / "soda_ash_panorama.parquet").exists()
    loaded = load_latest_soda_ash_panorama(tmp_path / "analytics")
    assert len(loaded) == 2
    assert "inventory_flow_regime" in loaded.columns


def test_pipeline_raises_without_core_input(tmp_path: Path) -> None:
    config = SodaAshConfig(
        artifact_root=str(tmp_path / "analytics"),
        inputs=InputsConfig(nbs_soda_ash_csv=str(tmp_path / "missing.csv")),
    )
    pipeline = SodaAshPipeline(
        runtime=DataRuntimeContext.from_root(tmp_path / "data"),
        config=config,
        catalog_factory=lambda source: FakeCatalog({}),
    )
    with pytest.raises(FileNotFoundError, match="缺失"):
        pipeline.run(update_latest=False)


def test_pipeline_as_of_clips_panorama_and_seasonal_gate(tmp_path: Path) -> None:
    """--as-of 贯通：截断全景表，使季节性门禁基准回到目标月而非最新完整月。"""
    data_dir = tmp_path / "data"
    nbs_dir = tmp_path / "nbs"
    nbs_dir.mkdir(parents=True)
    _write_nbs_csv(
        nbs_dir / "soda.csv",
        "report_month,output_current,output_yoy",
        ["2024-01,200.0,5.0", "2024-02,210.0,6.0", "2024-03,220.0,7.0"],
    )
    _write_nbs_csv(
        nbs_dir / "glass.csv",
        "report_month,output_current,output_yoy",
        ["2024-01,7000.0,3.0", "2024-02,7100.0,4.0", "2024-03,7200.0,5.0"],
    )
    config = SodaAshConfig(
        artifact_root=str(tmp_path / "analytics"),
        inputs=InputsConfig(
            nbs_soda_ash_csv=str(nbs_dir / "soda.csv"),
            nbs_plate_glass_csv=str(nbs_dir / "glass.csv"),
        ),
    )
    pipeline = SodaAshPipeline(
        runtime=DataRuntimeContext.from_root(data_dir),
        config=config,
        catalog_factory=lambda source: FakeCatalog({}),
    )

    result = pipeline.run(
        as_of=date(2024, 1, 31),
        build_company_fallback=False,
        update_latest=False,
    )

    # 全景表被截断到 as_of 月（2024-01），门禁基准随之回退
    assert len(result.panorama) == 1
    gates = result.manifest["trading_gates"]
    assert gates["as_of_month"] == "2024-01"
    right = gates["right_side_confirmation"]
    # 1 月处于春节前后淡季黑洞期 → 季节性一票否决右侧追高
    assert "淡季被动累库黑洞期" in right["cond_seasonal_desc"]
    assert "季节性规则拦截" in right["suggestion"]
