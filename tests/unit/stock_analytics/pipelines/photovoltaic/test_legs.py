"""光伏深研线状态/防守特征面板管线单元测试（纯逻辑，mock 数据文件）。

覆盖：
- config 从 YAML 加载；
- cycle_state 状态机四态判定（核心规则，对齐 industry_solar_cycle_position）；
- rolling 分位与月频腿（release_date 生效、无前视）；
- pipeline run 落盘 parquet + manifest（tmp_path 假数据）。
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

from stock_analytics.pipelines.photovoltaic.config import (
    CycleStateConfig,
    PhotovoltaicLegsConfig,
    load_photovoltaic_legs_config,
)
from stock_analytics.pipelines.photovoltaic.legs import (
    _monthly_pct,
    _rolling_pct,
    _state_row,
    build_cycle_state,
)
from stock_analytics.pipelines.photovoltaic.pipeline import run_photovoltaic_legs


def test_load_config_from_yaml() -> None:
    config = load_photovoltaic_legs_config("config/analytics/photovoltaic_legs.yaml")
    assert isinstance(config, PhotovoltaicLegsConfig)
    assert config.industry_codes == ("630500",)
    assert config.cycle_state is not None
    assert config.cycle_state.glut_yoy_threshold == 0.30
    assert config.cycle_state.flood_months == 24
    assert config.fin_defense is not None
    assert config.price_patch is not None
    assert config.price_patch.gate_threshold == 20.0
    assert config.lifecycle_weights == {"上行": 1.0, "过剩": 0.0, "下行": 0.8, "底部右侧": 0.5}


# ---------------------------------------------------------------------------
# cycle_state 状态机四态判定（对齐 industry_solar_cycle_position._state_row）
# ---------------------------------------------------------------------------


def _state(
    util: float | None = 60.0,
    u6: float | None = 0.0,
    cy: float | None = 0.0,
    flood24: float | None = 0.0,
    py: float | None = 0.0,
    sc: float | None = 0.0,
) -> str | None:
    return _state_row(util, u6, cy, flood24, py, sc, CycleStateConfig())


def test_state_glut_when_cap_yoy_high() -> None:
    # 扩产潮 cap_yoy>=30% → 过剩（2022-2023 扩产潮）
    assert _state(cy=0.35) == "过剩"


def test_state_downswing_when_flood_aftermath() -> None:
    # 扩产潮余波（24 个月内出现过 >=30%）→ 结构性下行（2024-2025）
    assert _state(cy=0.05, flood24=0.35) == "下行"


def test_state_upswing_when_high_util_no_flood() -> None:
    # 高利用率 + 无扩产潮 → 上行（2020-2021）
    assert _state(util=80.0, cy=0.05, flood24=0.05) == "上行"


def test_state_bottom_right_when_low_util_recovering() -> None:
    # 低利用率 + 方向回升 → 底部右侧（2026 起）
    assert _state(util=40.0, u6=2.0, cy=0.05, flood24=0.05) == "底部右侧"
    # 低利用率 + 剪刀差转正 → 底部右侧
    assert _state(util=40.0, u6=-1.0, cy=0.05, flood24=0.05, sc=5.0) == "底部右侧"


def test_state_downswing_when_low_util_still_deteriorating() -> None:
    # 低利用率 + 无回升信号 → 仍下行
    assert _state(util=40.0, u6=-1.0, cy=0.05, flood24=0.05, sc=-5.0) == "下行"


def test_state_mid_util_rising_upswing_else_down() -> None:
    # 中位利用率 45-70：方向回升且剪刀差不极端 → 上行
    assert _state(util=55.0, u6=1.0, cy=0.05, flood24=0.05, sc=0.0) == "上行"
    # 中位利用率 + 剪刀差过深 → 下行
    assert _state(util=55.0, u6=1.0, cy=0.05, flood24=0.05, sc=-30.0) == "下行"


def test_state_requires_core_inputs() -> None:
    # 缺关键输入（cy 或 util 或 flood24）→ None（无判定）
    assert _state(cy=None) is None
    assert _state(util=None) is None
    assert _state(flood24=None) is None


# ---------------------------------------------------------------------------
# rolling 分位与月频腿（release_date 生效、无前视）
# ---------------------------------------------------------------------------


def test_rolling_pct_bounds_and_monotone() -> None:
    s = pl.Series("v", [float(i) for i in range(50)])
    pct = _rolling_pct(s, window=36)
    assert pct.min() >= 0.0
    assert pct.max() <= 100.0
    assert len(pct) == 50
    # 单调递增序列：分位应趋于高位且不降（同值并列取 <= 口径）
    assert pct[-1] >= pct[0]


def test_monthly_pct_uses_release_date_and_forward() -> None:
    rows = []
    for i in range(48):
        last = date(2019, 1, 31) + timedelta(days=31 * i)
        rows.append((last, last + timedelta(days=10), float(i) + 1.0))
    df = pl.DataFrame(
        rows,
        schema={"trade_date": pl.Date, "release_date": pl.Date, "value": pl.Float64},
        orient="row",
    )
    leg = _monthly_pct(df, "value", window_months=36)
    # 输出列 = release_date 别名 trade_date + pct（生效日语义）
    assert set(leg.columns) == {"trade_date", "pct"}
    assert leg["pct"].min() >= 0.0
    assert leg["pct"].max() <= 100.0
    assert not leg.is_empty()


# ---------------------------------------------------------------------------
# build_cycle_state（tmp runtime 假数据）
# ---------------------------------------------------------------------------


class _FakeRuntime:
    """鸭子类型 DataRuntimeContext：data_root 指向 tmp_path。"""

    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root


def _write_curated(runtime: _FakeRuntime, name: str, df: pl.DataFrame) -> None:
    out = runtime.data_root / "curated" / "industry"
    out.mkdir(parents=True, exist_ok=True)
    df.write_parquet(out / f"{name}.parquet")


def _month_series(start: date, n: int) -> list[date]:
    return [date(2019, 1, 31) + timedelta(days=31 * i) for i in range(n)]


def _cycle_inputs(n: int = 60) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    months = _month_series(date(2019, 1, 1), n)
    ps = pl.DataFrame(
        {
            "report_month": months,
            "release_date": [d + timedelta(days=10) for d in months],
            "capacity_annual_w_tons": [1.0 + 0.2 * (i % 12) for i in range(n)],
            "production_w_tons": [1.0 + 0.1 * (i % 12) for i in range(n)],
        }
    )
    sw = pl.DataFrame(
        {
            "report_month": months,
            "derived_polysilicon_utilization_rate": [50.0 + (i % 20) for i in range(n)],
        }
    )
    sd = pl.DataFrame(
        {
            "report_month": months,
            "scissors_spread_yoy": [float(i % 5 - 2) / 100.0 for i in range(n)],
        }
    )
    return ps, sw, sd


def test_build_cycle_state_from_fake_data(tmp_path: Path) -> None:
    rt = _FakeRuntime(tmp_path)
    ps, sw, sd = _cycle_inputs()
    _write_curated(rt, "polysilicon_supply_monthly", ps)
    _write_curated(rt, "silicon_wafer_monthly", sw)
    _write_curated(rt, "solar_supply_demand", sd)

    states = build_cycle_state(rt, CycleStateConfig())
    assert not states.is_empty()
    assert set(states.columns) == {"release_date", "state"}
    assert set(states["state"].unique().to_list()) <= {"上行", "过剩", "下行", "底部右侧"}
    # release_date 严格升序无重复
    assert states["release_date"].is_sorted()
    assert states["release_date"].n_unique() == len(states)


# ---------------------------------------------------------------------------
# pipeline run 落盘（tmp runtime + 假 curated 数据）
# ---------------------------------------------------------------------------


def test_pipeline_run_writes_artifacts(tmp_path: Path) -> None:
    # 日频日历
    mart_dir = tmp_path / "curated" / "mart"
    mart_dir.mkdir(parents=True, exist_ok=True)
    cal_dates = [date(2019, 1, 1) + timedelta(days=i) for i in range(1200)]
    pl.DataFrame({"trade_date": cal_dates}).write_parquet(mart_dir / "global_macro_daily.parquet")

    # 630500 行业面板（close 用递增序列）
    panel_dates = [date(2019, 1, 1) + timedelta(days=i) for i in range(1200)]
    pl.DataFrame(
        {
            "trade_date": panel_dates,
            "industry_code": ["630500"] * len(panel_dates),
            "close": [100.0 + i for i in range(len(panel_dates))],
        }
    ).write_parquet(mart_dir / "industry_l2_panel_daily.parquet")

    # cycle / fin / price 数据源
    rt = _FakeRuntime(tmp_path)
    ps, sw, sd = _cycle_inputs()
    _write_curated(rt, "polysilicon_supply_monthly", ps)
    _write_curated(rt, "silicon_wafer_monthly", sw)
    _write_curated(rt, "solar_supply_demand", sd)
    # price 源（组件周价，递增 → 无回撤）
    price_dates = [date(2019, 1, 1) + timedelta(days=7 * i) for i in range(200)]
    _write_curated(
        rt,
        "solar_price_chain",
        pl.DataFrame(
            {
                "trade_date": price_dates,
                "module_price_cny_watt": [1.0 + 0.01 * i for i in range(200)],
            }
        ),
    )
    # fin 源：成分股聚合表（放空 → fin 特征全 0）
    const_dir = tmp_path / "curated" / "lixinger" / "market=CN" / "sw_2021_constituents"
    const_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "symbol": pl.Series([], dtype=pl.Utf8),
            "industryCode": pl.Series([], dtype=pl.Utf8),
        }
    ).write_parquet(const_dir / "data.parquet")

    out_root = tmp_path / "analytics"
    result = run_photovoltaic_legs(
        config_path="config/analytics/photovoltaic_legs.yaml",
        output_dir=out_root,
        storage_dir=tmp_path,
    )
    assert result.panel is not None
    assert not result.panel.is_empty()
    assert result.manifest["artifact_type"] == "photovoltaic_legs"
    assert (result.paths.run_dir / "photovoltaic_legs.parquet").exists()
    assert (result.paths.run_dir / "manifest.json").exists()
    # latest 指针存在（目录或软链）
    assert (out_root / "latest").exists()


def test_config_default_when_yaml_missing(tmp_path: Path) -> None:
    missing = tmp_path / "nope.yaml"
    config = load_photovoltaic_legs_config(missing)
    assert isinstance(config, PhotovoltaicLegsConfig)
    assert config.industry_codes == ("630500",)


def test_build_fin_defense_triggers_on_loss_and_growth_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from stock_analytics.pipelines.photovoltaic.config import FinDefenseConfig
    from stock_analytics.pipelines.photovoltaic.legs import build_fin_defense

    cal = pl.DataFrame({"trade_date": [date(2026, 4, 30), date(2026, 8, 31), date(2026, 9, 1)]})

    # Case 1: TTM 亏损，即使同比改善，依然触发防守 (pos=1.0)
    fake_const_loss = pl.DataFrame(
        {
            "year": [2026, 2026],
            "quarter": [1, 2],
            "np_ttm": [-337.0, -377.0],
            "np": [0.02, -0.11],
        }
    )
    monkeypatch.setattr(
        "stock_analytics.pipelines.photovoltaic.legs._const_series",
        lambda rt, ind: fake_const_loss,
    )
    res_loss = build_fin_defense(None, "630500", FinDefenseConfig(), cal)  # type: ignore[arg-type]
    assert (res_loss["pos"] == 1.0).all()

    # Case 2: TTM 盈利且同比增长，不触发防守 (pos=0.0)
    fake_const_healthy = pl.DataFrame(
        {
            "year": [2026, 2026],
            "quarter": [1, 2],
            "np_ttm": [300.0, 350.0],
            "np": [0.15, 0.20],
        }
    )
    monkeypatch.setattr(
        "stock_analytics.pipelines.photovoltaic.legs._const_series",
        lambda rt, ind: fake_const_healthy,
    )
    res_healthy = build_fin_defense(None, "630500", FinDefenseConfig(), cal)  # type: ignore[arg-type]
    assert (res_healthy["pos"] == 0.0).all()
