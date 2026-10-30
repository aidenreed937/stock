"""半导体深研线建腿管线单元测试（纯逻辑，mock DataCatalog）。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from stock_analytics.pipelines.semiconductor.config import (
    MonthlySource,
    QuarterlySource,
    ScissorsConfig,
    SemiconductorLegsConfig,
    StructuralConfig,
    load_semiconductor_legs_config,
)
from stock_analytics.pipelines.semiconductor.legs import (
    build_monthly_leg,
    build_quarterly_leg,
    build_semiconductor_legs_panel,
)
from stock_analytics.pipelines.semiconductor.pipeline import run_semiconductor_legs


class _FakeCatalog:
    """鸭子类型 DataCatalog：load_dataset 返回预置 DataFrame 或抛异常。"""

    def __init__(self, datasets: dict[str, pl.DataFrame]) -> None:
        self._datasets = datasets

    def load_dataset(self, name: str) -> pl.DataFrame:
        if name not in self._datasets:
            raise KeyError(f"fake dataset {name} missing")
        return self._datasets[name]


def _monthly_frame(
    start: date,
    n: int,
    *,
    col: str = "value",
    yoy: bool = False,
    release_offset_days: int = 10,
) -> pl.DataFrame:
    """构造月频源帧：trade_date=月末，release_date=月末+offset，值线性递增。

    yoy=True 时额外提供已算好的 yoy_growth 列。
    """
    rows = []
    for i in range(n):
        y = start.year + (start.month - 1 + i) // 12
        m = (start.month - 1 + i) % 12 + 1
        last = (
            date(y, m + 1, 1).replace(day=1) - __import__("datetime").timedelta(days=1)
            if m < 12
            else date(y + 1, 1, 1) - __import__("datetime").timedelta(days=1)
        )
        td = last
        rd = last + __import__("datetime").timedelta(days=release_offset_days)
        rows.append((td, rd, float(i) + 1.0))
    df = pl.DataFrame(
        rows, schema={"trade_date": pl.Date, "release_date": pl.Date, col: pl.Float64}, orient="row"
    )
    if yoy:
        df = df.with_columns((pl.col(col) / pl.col(col).shift(12)).alias("yoy_growth"))
    return df


def _calendar(start: date, n_days: int) -> pl.DataFrame:
    return pl.DataFrame(
        {"trade_date": [start + __import__("datetime").timedelta(days=i) for i in range(n_days)]}
    )


def test_load_config_from_yaml() -> None:
    config = load_semiconductor_legs_config("config/analytics/semiconductor_legs.yaml")
    assert isinstance(config, SemiconductorLegsConfig)
    assert config.industry_codes == ("270100",)
    assert config.scissors is not None
    assert [d.source for d in config.scissors.demand_sources] == [
        "semiconductor_lead",
        "semiconductor_sales",
    ]
    assert config.scissors.supply.source == "semiconductor_equipment"
    assert config.structural is not None
    assert config.structural.ai_capex.source == "cloud_capex_quarterly"
    assert config.structural.legs is not None
    assert "ai_fcf_health" in config.structural.legs
    assert "ai_marginal_roi" in config.structural.legs
    assert config.structural.legs["ai_fcf_health"].column == "fcf_conversion_rate"
    assert config.structural.legs["ai_marginal_roi"].column == "marginal_roi_proxy"


def test_build_monthly_leg_forward_fill_and_range() -> None:
    """月频腿：release_date 生效、日频前向填充、0-100 分位。"""
    start = date(2018, 1, 31)
    n = 60
    src = _monthly_frame(start, n, col="tsmc_revenue_3mma_usd")
    cat = _FakeCatalog({"semiconductor_lead": src})
    cal = _calendar(date(2018, 1, 1), 1200)

    leg = build_monthly_leg(
        MonthlySource(
            source="semiconductor_lead", column="tsmc_revenue_3mma_usd", window_months=36
        ),
        cal,
        cat,
    )
    assert {"trade_date", "direction_score"}.issubset(leg.columns)
    assert not leg.is_empty()
    assert leg["direction_score"].min() >= 0.0
    assert leg["direction_score"].max() <= 100.0
    # 前向填充生效：日期严格升序、无重复；分位非平凡（多个不同值）
    sorted_leg = leg.sort("trade_date")
    assert sorted_leg["trade_date"].is_sorted()
    assert sorted_leg["trade_date"].n_unique() == len(sorted_leg)
    assert len(set(sorted_leg["direction_score"].to_list())) > 3


def test_build_quarterly_leg_uses_yoy_growth_when_available() -> None:
    start = date(2016, 1, 1)
    n = 60
    src = _monthly_frame(start, n, col="total_capex_billion_usd", yoy=True)
    cat = _FakeCatalog({"cloud_capex_quarterly": src})
    cal = _calendar(date(2016, 1, 1), 1200)

    leg = build_quarterly_leg(
        QuarterlySource(
            source="cloud_capex_quarterly", column="total_capex_billion_usd", window_quarters=12
        ),
        cal,
        cat,
    )
    assert not leg.is_empty()
    assert leg["direction_score"].min() >= 0.0
    assert leg["direction_score"].max() <= 100.0


def test_build_quarterly_leg_falls_back_when_release_dates_are_all_null() -> None:
    """release_date 列存在但全空时，季度腿应按 trade_date 生效。"""
    start = date(2016, 1, 1)
    src = _monthly_frame(start, 60, col="total_capex_billion_usd", yoy=True).with_columns(
        pl.lit(None, dtype=pl.Date).alias("release_date")
    )
    cat = _FakeCatalog({"cloud_capex_quarterly": src})
    cal = _calendar(start, 1200)

    leg = build_quarterly_leg(
        QuarterlySource(
            source="cloud_capex_quarterly", column="total_capex_billion_usd", window_quarters=12
        ),
        cal,
        cat,
    )

    assert not leg.is_empty()
    assert leg["trade_date"].min() == date(2017, 1, 31)


def test_missing_source_returns_empty_leg() -> None:
    cal = _calendar(date(2020, 1, 1), 100)
    cat = _FakeCatalog({})
    leg = build_monthly_leg(MonthlySource(source="nope", column="x", window_months=36), cal, cat)
    assert leg.is_empty()


def _make_config() -> SemiconductorLegsConfig:
    return SemiconductorLegsConfig(
        industry_codes=("270100",),
        scissors=ScissorsConfig(
            demand_sources=(
                MonthlySource("semi_lead", "tsmc_revenue_3mma_usd", 36),
                MonthlySource("semi_sales", "global_sales_usd", 36),
            ),
            supply=MonthlySource("semi_equip", "billings_3mma_jpy", 36),
        ),
        structural=StructuralConfig(
            ai_capex=QuarterlySource("cloud_capex", "total_capex_billion_usd", 12),
        ),
    )


def test_build_semiconductor_legs_panel_assembly() -> None:
    start = date(2018, 1, 31)
    n = 60
    cat = _FakeCatalog(
        {
            "semi_lead": _monthly_frame(start, n, col="tsmc_revenue_3mma_usd"),
            "semi_sales": _monthly_frame(start, n, col="global_sales_usd"),
            "semi_equip": _monthly_frame(start, n, col="billings_3mma_jpy"),
            "cloud_capex": _monthly_frame(start, n, col="total_capex_billion_usd", yoy=True),
        }
    )
    cal = _calendar(date(2018, 1, 1), 1500)

    panel = build_semiconductor_legs_panel(_make_config(), cal, cat)
    assert set(panel.columns) == {
        "trade_date",
        "industry_code",
        "demand_score",
        "supply_score",
        "scissors_score",
        "ai_capex_score",
    }
    assert set(panel["industry_code"].unique().to_list()) == {"270100"}
    assert len(panel) == 1 * len(cal)
    # 剪刀差 = demand − supply
    sample = panel.filter(pl.col("industry_code") == "270100").drop_nulls("scissors_score")
    assert not sample.is_empty()
    assert (
        sample["demand_score"] - sample["supply_score"] - sample["scissors_score"]
    ).abs().max() < 1e-6


def test_panel_missing_structural_legs_are_null() -> None:
    start = date(2018, 1, 31)
    n = 60
    cat = _FakeCatalog(
        {
            "semi_lead": _monthly_frame(start, n, col="tsmc_revenue_3mma_usd"),
            "semi_sales": _monthly_frame(start, n, col="global_sales_usd"),
            "semi_equip": _monthly_frame(start, n, col="billings_3mma_jpy"),
        }
    )  # 缺 cloud_capex
    cal = _calendar(date(2018, 1, 1), 1500)
    panel = build_semiconductor_legs_panel(_make_config(), cal, cat)
    assert panel["ai_capex_score"].null_count() == len(panel)
    # 剪刀差仍有效（demand/supply 有）
    assert panel["scissors_score"].null_count() < len(panel)


def test_pipeline_run_writes_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """管线 run 落盘 parquet + manifest，并更新 latest。"""
    start = date(2018, 1, 31)
    n = 60
    datasets = {
        "semiconductor_lead": _monthly_frame(start, n, col="tsmc_revenue_3mma_usd"),
        "semiconductor_sales": _monthly_frame(start, n, col="global_sales_usd"),
        "semiconductor_equipment": _monthly_frame(start, n, col="billings_3mma_jpy"),
        "cloud_capex_quarterly": _monthly_frame(start, n, col="total_capex_billion_usd", yoy=True),
    }
    fake_cat = _FakeCatalog(datasets)

    # 写日频日历到 tmp runtime
    mart_dir = tmp_path / "curated" / "mart"
    mart_dir.mkdir(parents=True, exist_ok=True)
    _calendar(date(2018, 1, 1), 1500).write_parquet(mart_dir / "global_macro_daily.parquet")

    import stock_analytics.pipelines.semiconductor.legs as legs_mod
    import stock_analytics.pipelines.semiconductor.pipeline as pipe_mod

    monkeypatch.setattr(pipe_mod, "DataCatalog", lambda **_: fake_cat)
    monkeypatch.setattr(legs_mod, "DataCatalog", lambda **_: fake_cat)

    out_root = tmp_path / "analytics"
    result = run_semiconductor_legs(
        config_path="config/analytics/semiconductor_legs.yaml",
        output_dir=out_root,
        storage_dir=tmp_path,
    )
    assert result.panel is not None
    assert not result.panel.is_empty()
    assert result.manifest["artifact_type"] == "semiconductor_legs"
    # 落盘产物
    assert (result.paths.run_dir / "semiconductor_legs.parquet").exists()
    assert (result.paths.run_dir / "manifest.json").exists()
    # latest 指针
    latest_dir = out_root / "latest"
    assert latest_dir.exists() or (out_root / "latest").is_symlink()


def test_build_quarterly_leg_dimensionless_metrics() -> None:
    """无量纲比率/转化率指标直接做分位，不进行二次 YoY。"""
    start = date(2018, 1, 1)
    n = 30
    src = _monthly_frame(start, n, col="fcf_conversion_rate", yoy=False)
    cat = _FakeCatalog({"cloud_fundamentals_quarterly": src})
    cal = _calendar(start, 1200)

    leg = build_quarterly_leg(
        QuarterlySource(
            source="cloud_fundamentals_quarterly",
            column="fcf_conversion_rate",
            window_quarters=12,
        ),
        cal,
        cat,
    )
    assert not leg.is_empty()
    assert leg["direction_score"].min() >= 0.0
    assert leg["direction_score"].max() <= 100.0


def test_build_semiconductor_legs_panel_with_multiple_structural_legs() -> None:
    """多结构腿组装面板，所有声明的结构腿均输出对应 _score 列。"""
    start = date(2018, 1, 31)
    n = 60
    cat = _FakeCatalog(
        {
            "semi_lead": _monthly_frame(start, n, col="tsmc_revenue_3mma_usd"),
            "semi_sales": _monthly_frame(start, n, col="global_sales_usd"),
            "semi_equip": _monthly_frame(start, n, col="billings_3mma_jpy"),
            "cloud_capex": _monthly_frame(start, n, col="total_capex_billion_usd", yoy=True),
            "cloud_fund": _monthly_frame(start, n, col="fcf_conversion_rate", yoy=False),
        }
    )
    cal = _calendar(date(2018, 1, 1), 1500)

    cfg = SemiconductorLegsConfig(
        industry_codes=("270100",),
        scissors=ScissorsConfig(
            demand_sources=(MonthlySource("semi_lead", "tsmc_revenue_3mma_usd", 36),),
            supply=MonthlySource("semi_equip", "billings_3mma_jpy", 36),
        ),
        structural=StructuralConfig(
            ai_capex=QuarterlySource("cloud_capex", "total_capex_billion_usd", 12),
            legs={
                "ai_capex": QuarterlySource("cloud_capex", "total_capex_billion_usd", 12),
                "ai_fcf_health": QuarterlySource("cloud_fund", "fcf_conversion_rate", 12),
            },
        ),
    )

    panel = build_semiconductor_legs_panel(cfg, cal, cat)
    expected_cols = {
        "trade_date",
        "industry_code",
        "demand_score",
        "supply_score",
        "scissors_score",
        "ai_capex_score",
        "ai_fcf_health_score",
    }
    assert expected_cols.issubset(panel.columns)
    assert panel["ai_fcf_health_score"].null_count() < len(panel)
