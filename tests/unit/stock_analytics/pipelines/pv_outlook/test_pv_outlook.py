"""光伏景气前瞻仪表盘 (pv_outlook) 管线单元测试。

数据构造遵循 Ground Truth First：全部输入为 tmp 目录下的最小 Parquet 黄金表，
通过 DataRuntimeContext 指向 tmp 数据根，不依赖真实数据与网络。
"""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from stock_analytics.pipelines.pv_outlook.config import (
    DEFAULT_CONFIG_PATH,
    PvOutlookConfig,
    load_pv_outlook_config,
)
from stock_analytics.pipelines.pv_outlook.facts import (
    build_gap_matrix,
    load_price_chain,
)
from stock_analytics.pipelines.pv_outlook.report import render_pv_outlook_markdown
from stock_analytics.pipelines.pv_outlook.scoring import build_outlook_snapshot
from stock_data.core.runtime import DataRuntimeContext

_WEEKLY_COLUMNS = [
    "report_date",
    "trade_date",
    "polysilicon_price_cny_kg",
    "wafer_price_cny_piece",
    "cell_price_cny_watt",
    "module_price_cny_watt",
    "module_price_yoy",
    "module_price_mom",
    "price_cycle_stage",
    "unit",
    "source",
    "source_url",
    "release_date",
    "data_status",
    "collected_at",
]


def _write_industry_table(tmp_path, name: str, df: pl.DataFrame) -> None:
    table_dir = tmp_path / "curated" / "industry"
    table_dir.mkdir(parents=True, exist_ok=True)
    df.write_parquet(table_dir / f"{name}.parquet")


def _make_price_chain(n_weeks: int = 16, module_up: bool = True) -> pl.DataFrame:
    """构造周度价格链：多晶硅/硅片/电池/组件，组件价格随时间上行或下行。"""
    rows = []
    base = date(2026, 5, 1)
    for i in range(n_weeks):
        report = base + timedelta(weeks=i)
        step = i * (0.002 if module_up else -0.002)
        rows.append(
            {
                "report_date": report,
                "trade_date": report,
                "polysilicon_price_cny_kg": 40.0,
                "wafer_price_cny_piece": 1.1,
                "cell_price_cny_watt": 0.31,
                "module_price_cny_watt": round(0.70 + step, 4),
                "module_price_yoy": 0.025 if module_up else -0.02,
                "module_price_mom": 0.001,
                "price_cycle_stage": "bottom_rebound" if module_up else "downtrend",
                "unit": "元",
                "source": "InfoLink",
                "source_url": "",
                "release_date": report,
                "data_status": "actual",
                "collected_at": str(report),
            }
        )
    return pl.DataFrame(rows, schema=_WEEKLY_COLUMNS)


def _make_solar_capacity(latest_month: str, value: float, prev_value: float) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "report_month": ["2026-05", latest_month],
            "trade_date": [date(2026, 5, 31), date(2026, 6, 30)],
            "monthly_new_capacity_gw": [prev_value, value],
            "monthly_new_capacity_3mma": [20.0, 20.0],
            "cumulative_capacity_gw": [100.0, 120.0],
            "yoy_growth": [0.1, 0.1],
            "yoy_growth_3mma": [0.1, 0.1],
            "mom_growth_3mma": [0.05, 0.05],
            "unit": "GW",
            "source": "NEA",
            "source_url": "",
            "release_date": [date(2026, 6, 25), date(2026, 7, 25)],
            "data_status": ["actual", "actual"],
            "collected_at": ["2026-07-25", "2026-07-25"],
        }
    )


def _make_inventory(latest_month: str, value: float, prev_value: float) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "report_month": ["2026-05", latest_month],
            "trade_date": [date(2026, 5, 31), date(2026, 6, 30)],
            "inventory_w_tons": [prev_value, value],
            "inventory_change_w_tons": [0.0, value - prev_value],
            "inventory_weeks": [6.0, 6.0],
            "inventory_status": ["high", "high"],
            "unit": "万吨",
            "source": "硅业分会",
            "source_url": "",
            "release_date": [date(2026, 6, 8), date(2026, 7, 8)],
            "data_status": ["actual", "actual"],
            "collected_at": ["2026-07-08", "2026-07-08"],
        }
    )


def test_load_config_defaults() -> None:
    """默认配置可加载且关键参数正确。"""
    config = load_pv_outlook_config(DEFAULT_CONFIG_PATH)
    assert isinstance(config, PvOutlookConfig)
    assert config.artifact_root == "data/analytics/pv_outlook"
    assert config.spread.wafers_per_piece == 6.6
    assert config.scoring.spread_lookback_weeks == 12
    assert len(config.datasets) >= 5


def test_load_config_missing_file_falls_back(tmp_path) -> None:
    """配置文件缺失时回退全默认值。"""
    config = load_pv_outlook_config(tmp_path / "nope.yaml")
    assert config.title == "光伏景气前瞻仪表盘 (组件/辅材/硅料)"
    assert len(config.datasets) == 8


def test_price_chain_spreads(tmp_path) -> None:
    """价差计算正确：组件毛利空间 = 组件价 - 电池价。"""
    df = _make_price_chain(n_weeks=16, module_up=True)
    _write_industry_table(tmp_path, "solar_price_chain", df)
    runtime = DataRuntimeContext.from_root(tmp_path)
    config = load_pv_outlook_config(tmp_path / "nope.yaml")
    out = load_price_chain(runtime, config)
    assert len(out) == 16
    latest = out.tail(1)
    expected_module_spread = latest["module_price_cny_watt"][0] - latest["cell_price_cny_watt"][0]
    assert abs(latest["spread_module_cny_watt"][0] - expected_module_spread) < 1e-9
    # 电池片毛利空间: 0.31 - 1.1/6.6
    assert abs(latest["spread_cell_cny_watt"][0] - (0.31 - 1.1 / 6.6)) < 1e-9


def test_gap_matrix_status_ok_lagging_missing(tmp_path) -> None:
    """缺口矩阵状态判定：周度正常/月度滞后/缺失三态。"""
    as_of = date(2026, 9, 3)
    # 周度价格链滞后 30 天（release_lag 14 天 → lagging）
    chain = _make_price_chain(n_weeks=12)
    _write_industry_table(tmp_path, "solar_price_chain", chain)
    # 装机最新 2026-08（as_of 9/3 减 40 天 → 期望 2026-07，ok）
    _write_industry_table(tmp_path, "solar_capacity", _make_solar_capacity("2026-08", 20.0, 18.0))
    runtime = DataRuntimeContext.from_root(tmp_path)
    config = load_pv_outlook_config(tmp_path / "nope.yaml")
    gaps = build_gap_matrix(runtime, config, as_of, price_chain=chain)
    by_name = {r["dataset"]: r for r in gaps.to_dicts()}
    assert by_name["solar_capacity"]["status"] == "ok"
    assert by_name["polysilicon_inventory_monthly"]["status"] == "missing"
    # 价格链: 最新报告日 = 2026-05-01+11周 = 2026-07-17，距 as_of 48 天 > 14 → lagging
    assert by_name["solar_price_chain"]["status"] == "lagging"


def test_outlook_snapshot_up_and_down(tmp_path) -> None:
    """前瞻读数：组件价上行+装机环比回升+库存去库 → 综合状态偏改善。"""
    as_of = date(2026, 9, 3)
    _write_industry_table(
        tmp_path, "solar_price_chain", _make_price_chain(n_weeks=16, module_up=True)
    )
    _write_industry_table(tmp_path, "solar_capacity", _make_solar_capacity("2026-08", 22.0, 12.0))
    _write_industry_table(
        tmp_path, "polysilicon_inventory_monthly", _make_inventory("2026-07", 30.0, 39.0)
    )
    runtime = DataRuntimeContext.from_root(tmp_path)
    config = load_pv_outlook_config(tmp_path / "nope.yaml")
    chain = load_price_chain(runtime, config)
    snap = build_outlook_snapshot(runtime, config, chain, as_of)
    stage = snap.filter(pl.col("维度") == "前瞻状态")["状态"][0]
    assert stage in ("边际改善（左侧后段）", "边际改善与需求走弱并存")
    # 价格链行应标记组件毛利空间改善
    spread_row = snap.filter(pl.col("维度") == "组件毛利空间(元/W)")
    assert spread_row["方向"][0] == "改善"


def test_outlook_snapshot_deteriorating(tmp_path) -> None:
    """前瞻读数：组件价下行+装机环比下滑+库存累库 → 综合状态偏下行。"""
    as_of = date(2026, 9, 3)
    _write_industry_table(
        tmp_path, "solar_price_chain", _make_price_chain(n_weeks=16, module_up=False)
    )
    _write_industry_table(tmp_path, "solar_capacity", _make_solar_capacity("2026-08", 12.0, 18.0))
    _write_industry_table(
        tmp_path, "polysilicon_inventory_monthly", _make_inventory("2026-07", 52.0, 30.0)
    )
    runtime = DataRuntimeContext.from_root(tmp_path)
    config = load_pv_outlook_config(tmp_path / "nope.yaml")
    chain = load_price_chain(runtime, config)
    snap = build_outlook_snapshot(runtime, config, chain, as_of)
    stage = snap.filter(pl.col("维度") == "前瞻状态")["状态"][0]
    assert stage in ("景气仍下行（底部待确认）", "政策底已现、市场底待验证")


def test_render_markdown_contains_gap_and_source_sections(tmp_path) -> None:
    """报告包含缺口矩阵与外部核验章节（来源标注）。"""
    from stock_analytics.pipelines.pv_outlook.config import ExternalFact

    as_of = date(2026, 9, 3)
    _write_industry_table(
        tmp_path, "solar_price_chain", _make_price_chain(n_weeks=16, module_up=True)
    )
    runtime = DataRuntimeContext.from_root(tmp_path)
    config = PvOutlookConfig(
        external_facts=(
            ExternalFact(
                fact="多晶硅 N 型致密料报价 38-43 元/千克，成交清淡",
                source="Mysteel 光伏产业链周报",
                published_date=date(2026, 9, 4),
            ),
        )
    )
    chain = load_price_chain(runtime, config)
    snap = build_outlook_snapshot(runtime, config, chain, as_of)
    gaps = build_gap_matrix(runtime, config, as_of, price_chain=chain)
    md = render_pv_outlook_markdown(config, as_of, snap, chain, gaps)
    assert "## 四、数据缺口矩阵" in md
    assert "## 五、外部事实核验" in md
    assert "Mysteel 光伏产业链周报" in md
    assert "2026-09-04" in md
    assert "本地缺失" in md or "滞后" in md or "缺失" in md


def test_negative_spread_improving_and_deteriorating(tmp_path) -> None:
    """负毛利空间（亏损收窄为改善，亏损扩大为走弱）。"""
    as_of = date(2026, 9, 3)
    # 构造亏损收窄场景: 组件价从 0.60 升至 0.64，电池价稳定 0.65，毛利空间从 -0.05 收窄至 -0.01
    rows = []
    base = date(2026, 5, 1)
    for i in range(16):
        report = base + timedelta(weeks=i)
        module_p = 0.60 if i == 0 else (0.64 if i == 15 else 0.62)
        rows.append(
            {
                "report_date": report,
                "trade_date": report,
                "polysilicon_price_cny_kg": 40.0,
                "wafer_price_cny_piece": 1.1,
                "cell_price_cny_watt": 0.65,
                "module_price_cny_watt": module_p,
                "module_price_yoy": 0.01,
                "module_price_mom": 0.001,
                "price_cycle_stage": "bottom",
                "unit": "元",
                "source": "InfoLink",
                "source_url": "",
                "release_date": report,
                "data_status": "actual",
                "collected_at": str(report),
            }
        )
    chain_df = pl.DataFrame(rows, schema=_WEEKLY_COLUMNS)
    _write_industry_table(tmp_path, "solar_price_chain", chain_df)
    runtime = DataRuntimeContext.from_root(tmp_path)
    config = load_pv_outlook_config(tmp_path / "nope.yaml")
    chain = load_price_chain(runtime, config)
    snap = build_outlook_snapshot(runtime, config, chain, as_of)
    module_row = snap.filter(pl.col("维度") == "组件毛利空间(元/W)").to_dicts()[0]
    # -0.01 > -0.05，亏损收窄判定为改善
    assert module_row["方向"] == "改善"
    assert module_row["状态"] == "改善"


def test_scissors_spread_crossing_zero_delta(tmp_path) -> None:
    """供需剪刀差跨 0 轴变化时方向判定不颠倒。"""
    as_of = date(2026, 9, 3)
    _write_industry_table(tmp_path, "solar_price_chain", _make_price_chain(n_weeks=16))
    # 供给从增速慢于需求(-5pct)变为快于需求(+5pct)，走阔恶化
    sd_worsen = pl.DataFrame(
        {
            "report_month": ["2026-06", "2026-07"],
            "trade_date": [date(2026, 6, 30), date(2026, 7, 31)],
            "scissors_spread_yoy": [-0.05, 0.05],
            "domestic_absorption_ratio": [60.0, 55.0],
        }
    )
    _write_industry_table(tmp_path, "solar_supply_demand", sd_worsen)
    runtime = DataRuntimeContext.from_root(tmp_path)
    config = load_pv_outlook_config(tmp_path / "nope.yaml")
    chain = load_price_chain(runtime, config)
    snap = build_outlook_snapshot(runtime, config, chain, as_of)
    scissor_row = snap.filter(pl.col("维度") == "剪刀差同比(pct)").to_dicts()[0]
    assert scissor_row["方向"] == "过剩走阔"
    assert scissor_row["状态"] == "仍过剩"

    # 反向：供给从快于需求(+5pct)变为慢于需求(-5pct)，过剩收窄
    sd_improve = pl.DataFrame(
        {
            "report_month": ["2026-06", "2026-07"],
            "trade_date": [date(2026, 6, 30), date(2026, 7, 31)],
            "scissors_spread_yoy": [0.05, -0.05],
            "domestic_absorption_ratio": [55.0, 65.0],
        }
    )
    _write_industry_table(tmp_path, "solar_supply_demand", sd_improve)
    snap_improve = build_outlook_snapshot(runtime, config, chain, as_of)
    scissor_row2 = snap_improve.filter(pl.col("维度") == "剪刀差同比(pct)").to_dicts()[0]
    assert scissor_row2["方向"] == "过剩收窄"
    assert scissor_row2["状态"] == "需求修复"


def test_load_price_chain_self_heals_null_derivatives(tmp_path) -> None:
    """底层价格链尾部 yoy/mom 为 null 时 load_price_chain 自动补齐。"""
    rows = []
    base = date(2025, 1, 1)
    for i in range(60):
        report = base + timedelta(weeks=i)
        rows.append(
            {
                "report_date": report,
                "trade_date": report,
                "polysilicon_price_cny_kg": 40.0,
                "wafer_price_cny_piece": 1.1,
                "cell_price_cny_watt": 0.31,
                "module_price_cny_watt": 0.70 + i * 0.001,
                # 尾部两行特意设为 None 模拟断档
                "module_price_yoy": None if i >= 58 else 0.02,
                "module_price_mom": None if i >= 58 else 0.001,
                "price_cycle_stage": "bottom",
                "unit": "元",
                "source": "InfoLink",
                "source_url": "",
                "release_date": report,
                "data_status": "actual",
                "collected_at": str(report),
            }
        )
    df = pl.DataFrame(rows, schema=_WEEKLY_COLUMNS)
    _write_industry_table(tmp_path, "solar_price_chain", df)
    runtime = DataRuntimeContext.from_root(tmp_path)
    config = load_pv_outlook_config(tmp_path / "nope.yaml")
    chain = load_price_chain(runtime, config)
    # 最后两行已被自愈补齐
    assert chain["module_price_mom"][-1] is not None
    assert chain["module_price_yoy"][-1] is not None
    assert chain["module_price_yoy"][-2] is not None


def test_customs_trade_gacc_watermark_recognized(tmp_path) -> None:
    """GACC 海关出口表正常识别光伏行水位。"""
    as_of = date(2026, 8, 15)
    customs_df = pl.DataFrame(
        {
            "report_month": ["2026-06", "2026-07"],
            "trade_date": [date(2026, 6, 30), date(2026, 7, 31)],
            "product_key": ["solar_cell", "solar_cell"],
            "product_name": ["光伏电池及组件", "光伏电池及组件"],
            "export_value_usd": [1e8, 1.2e8],
        }
    )
    _write_industry_table(tmp_path, "customs_trade_gacc", customs_df)
    runtime = DataRuntimeContext.from_root(tmp_path)
    config = load_pv_outlook_config(tmp_path / "nope.yaml")
    gaps = build_gap_matrix(runtime, config, as_of, price_chain=pl.DataFrame())
    by_name = {r["dataset"]: r for r in gaps.to_dicts()}
    assert by_name["customs_trade_gacc"]["status"] == "ok"
    assert by_name["customs_trade_gacc"]["latest_period"] == "2026-07"


def test_pipeline_run_end_to_end(tmp_path) -> None:
    """端到端测试 PvOutlookPipeline.run() 产物生成与 Manifest。"""
    from stock_analytics.pipelines.pv_outlook.pipeline import PvOutlookPipeline

    as_of = date(2026, 9, 3)
    _write_industry_table(tmp_path, "solar_price_chain", _make_price_chain(n_weeks=16))
    _write_industry_table(tmp_path, "solar_capacity", _make_solar_capacity("2026-08", 20.0, 18.0))
    _write_industry_table(
        tmp_path, "polysilicon_inventory_monthly", _make_inventory("2026-07", 30.0, 35.0)
    )
    runtime = DataRuntimeContext.from_root(tmp_path)
    config = load_pv_outlook_config(tmp_path / "nope.yaml")
    out_dir = tmp_path / "artifacts" / "pv_outlook"
    pipeline = PvOutlookPipeline(runtime=runtime, config=config)
    res = pipeline.run(as_of=as_of, output_dir=out_dir)

    assert res.as_of_date == as_of
    assert len(res.snapshot) > 0
    assert len(res.gap_matrix) == 8
    assert "光伏景气前瞻仪表盘" in res.report_markdown
    assert (res.paths.run_dir / "manifest.json").exists()
    assert (res.paths.run_dir / "pv_outlook_snapshot.parquet").exists()
    assert (res.paths.run_dir / "gap_matrix.parquet").exists()
    assert (res.paths.run_dir / "pv_outlook_report.md").exists()
