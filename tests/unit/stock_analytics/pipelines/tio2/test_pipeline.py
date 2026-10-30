"""钛白粉全景管线运行与 ArtifactStore 落盘测试。"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from stock_analytics.pipelines.tio2.config import InputsConfig, Tio2Config
from stock_analytics.pipelines.tio2.pipeline import (
    Tio2Pipeline,
    load_latest_tio2_panorama,
)
from stock_data.core.runtime import DataRuntimeContext


class FakeCatalog:
    """鸭子类型 DataCatalog。"""

    def __init__(self, datasets: dict[str, pl.DataFrame]) -> None:
        self._datasets = datasets

    def load_dataset(self, dataset: str) -> pl.DataFrame:
        if dataset not in self._datasets:
            return pl.DataFrame()
        return self._datasets[dataset]


def test_pipeline_run_writes_artifacts_and_latest(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    artifact_root = tmp_path / "artifacts" / "tio2"

    capacity_path = tmp_path / "capacity.yaml"
    capacity_path.write_text(
        "projects:\n  - company: 龙佰集团\n    plant_name: 攀枝花氯化法\n"
        "    capacity_w_tons: 20.0\n    technology: 氯化法\n    status: 已投产\n"
        "    actual_start: '2024-01'\n    source: 公告\n",
        encoding="utf-8",
    )

    datasets = {
        "customs_trade_gacc": pl.DataFrame(
            {
                "period": ["2024-01-10", "2024-02-10"],
                "hs_code": ["32061110", "32061110"],
                "product_key": ["tio2", "tio2"],
                "export_quantity": [120000.0, 130000.0],
                "export_value_usd": [2.5e8, 2.7e8],
                "yoy_growth": [15.0, 18.0],
            }
        ),
        "chemical_spot_price": pl.DataFrame(
            {
                "trade_date": ["2024-01-31", "2024-02-29"],
                "symbol": ["TiO2", "TiO2"],
                "spot_price_cny": [16000.0, 16200.0],
            }
        ),
        "chemical_spreads": pl.DataFrame(
            {
                "trade_date": ["2024-01-31", "2024-02-29"],
                "symbol": ["TiO2", "TiO2"],
                "product_price_cny": [16000.0, 16200.0],
                "spread_margin_cny": [1500.0, 1700.0],
                "margin_regime": ["profitable", "profitable"],
            }
        ),
        "mart/industry_l2_daily": pl.DataFrame(
            {
                "trade_date": ["2024-01-31", "2024-02-29"],
                "industry_code": ["220200", "220200"],
                "close": [3500.0, 3600.0],
                "pb_ew_percentile_10y": [18.0, 19.0],
                "pe_ttm_ew_percentile_5y": [25.0, 26.0],
            }
        ),
        "mart/tio2_company_panel": pl.DataFrame(
            {
                "trade_date": ["2024-01-31", "2024-02-29"],
                "symbol": ["002601.SZ", "002601.SZ"],
                "company_name": ["龙佰集团", "龙佰集团"],
                "process_type": ["chloride_and_sulfate", "chloride_and_sulfate"],
                "role": ["integrated_oligopoly_leader", "integrated_oligopoly_leader"],
                "close": [17.5, 18.0],
                "pb": [1.4, 1.45],
                "pb_percentile_10y": [12.0, 14.0],
                "pe_ttm": [13.0, 13.5],
                "valuation_regime": ["deep_value_trough", "fair_expansion"],
                "net_profit_attr_p": [1.5e9, 1.5e9],
            }
        ),
    }

    config = Tio2Config(
        artifact_root=str(artifact_root),
        inputs=InputsConfig(
            capacity_projects=str(capacity_path),
            trading_gates="config/industry/chemicals/tio2/trading_gates.yaml",
            customs_trade_dataset="customs_trade_gacc",
            chemical_spot_price_dataset="chemical_spot_price",
            chemical_spreads_dataset="chemical_spreads",
            company_panel_dataset="mart/tio2_company_panel",
            industry_l2_daily_dataset="mart/industry_l2_daily",
        ),
    )

    runtime = DataRuntimeContext.from_root(str(data_dir))
    pipeline = Tio2Pipeline(
        runtime=runtime,
        config=config,
        catalog_factory=lambda source: FakeCatalog(datasets),
    )

    result = pipeline.run(update_latest=True, build_company_fallback=False)

    assert result.as_of_date is not None
    assert len(result.panorama) == 2
    assert "export_qty_tons" in result.panorama.columns
    assert "tio2_spot_price_cny" in result.panorama.columns
    assert "inventory_flow_regime" in result.panorama.columns

    # 验证 Artifact 落盘与 manifest
    run_dir = result.paths.run_dir
    assert (run_dir / "tio2_panorama.parquet").exists()
    assert (run_dir / "tio2_panorama.csv").exists()
    assert (run_dir / "tio2_panorama.md").exists()
    assert (run_dir / "company_projections.parquet").exists()
    assert (run_dir / "lb_profit_sensitivity.parquet").exists()
    assert (run_dir / "zh_profit_sensitivity.parquet").exists()
    assert (run_dir / "manifest.json").exists()

    latest_dir = result.paths.latest_dir
    assert (latest_dir / "tio2_panorama.parquet").exists()
    assert (latest_dir / "company_projections.parquet").exists()
    assert (latest_dir / "manifest.json").exists()

    # 验证 manifest 包含 company_projections (2 家标的 * 4 大基准或 5 大情景含副业压力测试)
    assert "company_projections" in result.manifest
    assert len(result.manifest["company_projections"]) in (8, 10)
    assert result.company_projections is not None
    assert len(result.company_projections) in (8, 10)

    # 验证 load_latest_tio2_panorama 便捷函数
    latest_df = load_latest_tio2_panorama(artifact_root)
    assert len(latest_df) == 2


def test_pipeline_empty_panorama_renders_no_data_report(tmp_path: Path) -> None:
    """空全景不注入占位数据：渲染“无数据”报告并标记 manifest data_status=empty。"""
    data_dir = tmp_path / "data"
    artifact_root = tmp_path / "artifacts" / "tio2"

    capacity_path = tmp_path / "capacity.yaml"
    capacity_path.write_text("projects: []\n", encoding="utf-8")

    config = Tio2Config(
        artifact_root=str(artifact_root),
        inputs=InputsConfig(
            capacity_projects=str(capacity_path),
            trading_gates="config/industry/chemicals/tio2/trading_gates.yaml",
            customs_trade_dataset="customs_trade_gacc",
            customs_trade_fallback="customs_trade",
            chemical_spot_price_dataset="chemical_spot_price",
            chemical_spreads_dataset="chemical_spreads",
            company_panel_dataset="mart/tio2_company_panel",
            industry_l2_daily_dataset="mart/industry_l2_daily",
        ),
    )

    pipeline = Tio2Pipeline(
        runtime=DataRuntimeContext.from_root(str(data_dir)),
        config=config,
        catalog_factory=lambda source: FakeCatalog({}),
    )
    result = pipeline.run(update_latest=True, build_company_fallback=False)

    assert result.panorama.is_empty()
    assert "无数据" in result.report_markdown
    assert result.manifest["data_status"] == "empty"

    latest_md = result.paths.latest_dir / "tio2_panorama.md"
    assert latest_md.exists()
    assert "无数据" in latest_md.read_text(encoding="utf-8")
