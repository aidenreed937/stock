from datetime import date

import polars as pl

from stock_analytics.pipelines.macro_risk import MacroRiskPipeline
from stock_analytics.pipelines.macro_risk.config import (
    FactorConfig,
    MacroRiskConfig,
)


def test_macro_risk_pipeline_init() -> None:
    pipeline = MacroRiskPipeline()
    assert "erp" in pipeline.config.factors
    assert "fund_issue_pct" not in pipeline.config.factors
    assert "repurchase" in pipeline.config.factors
    assert "insider_net" in pipeline.config.factors
    assert "cb_price" in pipeline.config.factors
    assert "copper_gold" in pipeline.config.factors
    assert "us_yield_curve" in pipeline.config.factors
    assert "equity_fund_count_pct5y" not in pipeline.config.observations

    assert "breadth" in pipeline.config.dims
    assert "corporate" in pipeline.config.dims
    assert "cross_asset" in pipeline.config.dims
    assert "fear" in pipeline.config.dims
    assert "euphoria" not in pipeline.config.dims
    assert "overheat_index" in pipeline.config.indices
    assert "panic_index" in pipeline.config.indices
    assert pipeline.config.factors["erp"].window == 2500


def test_newlow252_registered_as_independent_observation_only() -> None:
    """52 周新低占比只登记为独立观测因子，不进入广度维度与双轨指数。"""
    pipeline = MacroRiskPipeline()
    cfg = pipeline.config.factors["newlow252_ratio"]
    assert cfg.series == "breadth"
    assert cfg.column == "newlow252_ratio"
    assert cfg.window == 1250
    assert cfg.min_periods == 500
    # raw 方向：高分位 = 新低占比高 = 恐慌端出清广度大
    assert cfg.direction == "raw"

    assert "newlow252_ratio" not in pipeline.config.dims["breadth"]
    assert "newhigh60_ratio" in pipeline.config.dims["breadth"]
    for components in pipeline.config.indices.values():
        assert all(item.dim != "newlow252_ratio" for item in components)


def test_fetch_breadth_projects_newlow252_ratio() -> None:
    """breadth 提取器把 market_daily 的 252 日新低占比投影为 newlow252_ratio。"""
    from stock_analytics.pipelines.macro_risk.data_fetchers import (
        FetchContext,
        fetch_breadth,
    )

    md = pl.DataFrame(
        {
            "trade_date": [date(2026, 10, 27), date(2026, 10, 28)],
            "adv_dec_ratio": [0.8, 1.2],
            "new_high_60d_ratio": [0.013, 0.022],
            "new_low_252d_ratio": [0.1509, 0.0383],
        }
    )
    ctx = FetchContext(cat=None, cat_yf=None, fs=None, md=md)  # type: ignore[arg-type]
    frame = fetch_breadth(ctx)

    assert frame.columns == ["trade_date", "adv_dec", "newhigh60_ratio", "newlow252_ratio"]
    assert frame["newlow252_ratio"].to_list() == [0.1509, 0.0383]


def test_copper_gold_factor_uses_monthly_window_and_asof_series(monkeypatch) -> None:
    """铜金比分位按月频样本计算，并通过月频序列向日历 asof。"""
    from stock_analytics.pipelines.macro_risk.config import FactorConfig

    pipeline = MacroRiskPipeline()
    copper_cfg = pipeline.config.factors["copper_gold"]
    assert copper_cfg.series == "global_macro_monthly"
    assert copper_cfg.window == 60
    assert copper_cfg.min_periods == 36

    monthly_dates = [date(2020 + index // 12, index % 12 + 1, 1) for index in range(40)]
    daily_axis = [date(item.year, item.month, 28) for item in monthly_dates]
    axis = pl.DataFrame({"trade_date": daily_axis})
    monthly = pl.DataFrame(
        {
            "trade_date": monthly_dates,
            "copper_gold_ratio": [float(index + 1) for index in range(40)],
        }
    )
    pipeline.config = MacroRiskConfig(
        factors={
            "copper_gold": FactorConfig(
                series="global_macro_monthly",
                column="copper_gold_ratio",
                window=60,
                min_periods=36,
                direction="raw",
            )
        },
        dims={},
        indices={},
    )
    monkeypatch.setattr(pipeline, "_market_daily", lambda: axis)
    monkeypatch.setattr(pipeline, "_get_raw_series", lambda _name: monthly)

    result = pipeline.run(as_of=daily_axis[-1], output_dir=None)
    assert result.tail(1)["copper_gold_score"][0] is not None


def test_macro_risk_completeness_full() -> None:
    """核心字段齐全时完整性报告 complete=true。"""
    from stock_analytics.pipelines.macro_risk.pipeline import _check_data_completeness

    row = {
        "overheat_index": 69.2,
        "panic_index": 33.9,
        "dim_valuation": 47.2,
        "dim_leverage": 84.9,
        "dim_fear": 28.8,
        "dim_flow": 35.7,
        "dim_crowding": 78.4,
        "dim_breadth": 37.0,
    }
    rep = _check_data_completeness(row)
    assert rep["complete"] is True
    assert rep["missing_fields"] == []
    assert rep["total"] == 8 and rep["available"] == 8


def test_macro_risk_completeness_valuation_gap() -> None:
    """估值冷启动期 dim_valuation 缺失 → complete=false 且列入 missing_fields。"""
    from stock_analytics.pipelines.macro_risk.pipeline import _check_data_completeness

    row = {
        "overheat_index": 85.4,
        "panic_index": 21.9,
        "dim_valuation": None,  # 2015-01~2016-08 冷启动缺口
        "dim_leverage": 90.8,
        "dim_fear": 40.0,
        "dim_flow": 50.0,
        "dim_crowding": 98.3,
        "dim_breadth": 30.0,
    }
    rep = _check_data_completeness(row)
    assert rep["complete"] is False
    assert "dim_valuation" in rep["missing_fields"]
    assert rep["available"] == 7


def test_macro_risk_pipeline_asof_aligns_convertible_bond(monkeypatch) -> None:
    """可转债日频数据落后一个交易日时，向后对齐最后可用值且不前视。"""
    pipeline = MacroRiskPipeline()
    pipeline.config = MacroRiskConfig(
        factors={
            "cb_price": FactorConfig(
                series="convertible_bond",
                column="cb_price_median",
                window=10,
                min_periods=1,
                direction="raw",
            )
        },
        dims={},
        indices={},
    )
    axis_dates = [date(2026, 10, day) for day in range(1, 10)]
    axis = pl.DataFrame({"trade_date": axis_dates})
    convertible_bond = pl.DataFrame(
        {
            "trade_date": axis_dates[:-1],
            "cb_price_median": [100.0 + day for day in range(len(axis_dates) - 1)],
        }
    )

    monkeypatch.setattr(pipeline, "_market_daily", lambda: axis)
    monkeypatch.setattr(pipeline, "_get_raw_series", lambda _name: convertible_bond)

    result = pipeline.run(as_of=date(2026, 10, 9), output_dir=None)
    previous_score = result.filter(pl.col("trade_date") == date(2026, 10, 8))["cb_price_score"][0]
    latest_score = result.filter(pl.col("trade_date") == date(2026, 10, 9))["cb_price_score"][0]

    assert previous_score is not None
    assert latest_score == previous_score


def test_build_inputs_and_watermarks_populated() -> None:
    """Manifest inputs/watermarks 从各因子数据源原始序列正确回填。"""
    from datetime import date

    import polars as pl

    from stock_analytics.pipelines.macro_risk.pipeline import (
        _build_inputs_and_watermarks,
    )

    raw_cache = {
        "valuation": pl.DataFrame(
            {"trade_date": [date(2026, 8, 28), date(2026, 8, 31)], "erp": [1.0, 2.0]}
        ),
        "vix": pl.DataFrame({"trade_date": [date(2026, 8, 31)], "vix": [20.0]}),
    }
    inputs, watermarks = _build_inputs_and_watermarks(raw_cache)

    assert set(inputs) == {"valuation", "vix"}
    assert inputs["valuation"]["latest_date"] == "2026-08-31"
    assert inputs["valuation"]["rows"] == 2
    assert inputs["vix"]["latest_date"] == "2026-08-31"

    assert "analytics.valuation" in watermarks
    assert watermarks["analytics.valuation"]["latest"] == "2026-08-31"
    assert watermarks["analytics.valuation"]["sample_size"] == 2
    assert watermarks["analytics.vix"]["status"] == "ok"


def test_build_inputs_and_watermarks_empty_frame() -> None:
    """空数据源帧 → watermark status=empty、latest=None（不抛异常）。"""

    import polars as pl

    from stock_analytics.pipelines.macro_risk.pipeline import (
        _build_inputs_and_watermarks,
    )

    raw_cache = {
        "vix": pl.DataFrame(schema={"trade_date": pl.Date, "vix": pl.Float64}),
    }
    inputs, watermarks = _build_inputs_and_watermarks(raw_cache)
    assert inputs["vix"]["latest_date"] is None
    assert watermarks["analytics.vix"]["status"] == "empty"
    assert watermarks["analytics.vix"]["latest"] is None


def test_fedfunds_loader_prefers_newer_standard_dataset(tmp_path) -> None:
    """独立 FEDFUNDS 表水位更新时优先使用该表。"""
    from stock_analytics.pipelines.macro_risk.fred import load_fedfunds_series

    root = tmp_path / "fred" / "market=US"
    (root / "fedfunds").mkdir(parents=True)
    (root / "macro_indicators").mkdir(parents=True)
    pl.DataFrame(
        {
            "symbol": ["FEDFUNDS", "FEDFUNDS"],
            "trade_date": [date(2026, 8, 1), date(2026, 9, 1)],
            "value": [3.63, 3.75],
        }
    ).write_parquet(root / "fedfunds" / "data.parquet")
    pl.DataFrame(
        {
            "symbol": ["FEDFUNDS"],
            "trade_date": [date(2026, 8, 1)],
            "value": [3.63],
        }
    ).write_parquet(root / "macro_indicators" / "data.parquet")

    result = load_fedfunds_series(root)
    assert result.source_dataset == "fedfunds"
    assert result.latest_observation_date == date(2026, 9, 1)
    assert result.frame.tail(1)["value"][0] == 3.75


def test_fedfunds_loader_avoids_stale_standard_dataset(tmp_path) -> None:
    """独立表落后时回退到水位更高的聚合表，不能静默使用旧值。"""
    from stock_analytics.pipelines.macro_risk.fred import load_fedfunds_series

    root = tmp_path / "fred" / "market=US"
    (root / "fedfunds").mkdir(parents=True)
    (root / "macro_indicators").mkdir(parents=True)
    for dataset, trade_dates, values in (
        ("fedfunds", [date(2026, 7, 1)], [3.63]),
        ("macro_indicators", [date(2026, 8, 1), date(2026, 9, 1)], [3.63, 3.75]),
    ):
        pl.DataFrame(
            {"symbol": ["FEDFUNDS"] * len(trade_dates), "trade_date": trade_dates, "value": values}
        ).write_parquet(root / dataset / "data.parquet")

    result = load_fedfunds_series(root)
    assert result.source_dataset == "macro_indicators"
    assert result.latest_observation_date == date(2026, 9, 1)
    assert result.frame.tail(1)["value"][0] == 3.75


def test_build_fred_freshness_records_low_frequency_watermark() -> None:
    from stock_analytics.pipelines.macro_risk.fred import FedFundsSnapshot
    from stock_analytics.pipelines.macro_risk.pipeline import _build_fred_freshness

    freshness = _build_fred_freshness(
        date(2026, 9, 30),
        FedFundsSnapshot(-0.13, date(2026, 9, 1), "fedfunds"),
    )
    observation = freshness["fred_observations"]["FEDFUNDS"]
    assert freshness["market_as_of"] == "2026-09-30"
    assert observation["observation_date"] == "2026-09-01"
    assert observation["freshness_days"] == 29
    assert observation["frequency"] == "monthly"
    assert observation["source_dataset"] == "fedfunds"
