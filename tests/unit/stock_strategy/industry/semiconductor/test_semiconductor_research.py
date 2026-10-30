"""半导体深研线回测/IC 验证层单元测试（纯逻辑，mock 数据）。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from stock_strategy.industry.semiconductor.backtest import (
    position_weight,
    run_backtest,
)
from stock_strategy.industry.semiconductor.ic import (
    attach_f60,
    current_cross_section,
    overall_ic,
    spearman_ic,
    yearly_ic,
)
from stock_strategy.industry.semiconductor.metrics import compute_metrics


def test_position_weight_buy_hold_always_one() -> None:
    assert position_weight("buy_hold", -10.0, 90.0) == 1.0
    assert position_weight("buy_hold", None, None) == 1.0


def test_position_weight_scissors_neg() -> None:
    assert position_weight("scissors_neg", -5.0, 50.0) == 0.0
    assert position_weight("scissors_neg", 10.0, 50.0) == 1.0
    # 缺失剪刀差按中性 50 -> 不清仓
    assert position_weight("scissors_neg", None, 50.0) == 1.0


def test_position_weight_inv_high() -> None:
    assert position_weight("inv_high", 50.0, 80.0) == 0.3
    assert position_weight("inv_high", 50.0, 60.0) == 1.0


def test_position_weight_scissors_inv() -> None:
    # 双触发 -> 空仓
    assert position_weight("scissors_inv", -5.0, 80.0) == 0.0
    # 单触发 -> 0.3
    assert position_weight("scissors_inv", -5.0, 50.0) == 0.3
    assert position_weight("scissors_inv", 10.0, 80.0) == 0.3
    # 无触发 -> 1.0
    assert position_weight("scissors_inv", 10.0, 50.0) == 1.0


def test_compute_metrics_known_nav() -> None:
    # 常数净值（无波动、无增长）-> CAGR 0、Sharpe 0、MaxDD 0
    nav = [1.0] * 252
    m = compute_metrics(nav)
    assert m["cagr"] == 0.0
    assert m["max_dd"] == 0.0
    assert m["sharpe"] == 0.0

    # 简单线性上涨 -> MaxDD 0、CAGR > 0
    nav_up = [1.0 + 0.001 * i for i in range(252)]
    mu = compute_metrics(nav_up)
    assert mu["max_dd"] == 0.0
    assert mu["cagr"] > 0.0

    # 先涨后跌 -> MaxDD > 0
    nav_dd = list(range(1, 101)) + list(range(100, 50, -1))
    md = compute_metrics([v / 100.0 for v in nav_dd])
    assert md["max_dd"] > 0.0


def _make_panel() -> pl.DataFrame:
    """构造假面板：close 单调递增（便于 f60 正相关），带剪刀差与库存列。"""
    import datetime

    n = 1000
    days = [date(2020, 1, 1) + datetime.timedelta(days=i) for i in range(n)]
    ai_capex = [float(i) for i in range(n)]  # 0..n-1 递增
    # close 日收益率随 ai_capex 递增 -> f60(未来60日复合) 与 ai_capex 正相关
    close = [100.0]
    for i in range(1, n):
        daily_ret = 0.005 + 0.0002 * ai_capex[i]
        close.append(close[-1] * (1.0 + daily_ret))
    scissors = [50.0 + i * 0.05 for i in range(n)]
    inventory = [50.0] * n
    return pl.DataFrame(
        {
            "trade_date": days,
            "close": close,
            "scissors_score": scissors,
            "inventory_score": inventory,
            "ai_capex_score": ai_capex,
        }
    )


def test_spearman_ic_positive_correlation() -> None:
    df = _make_panel()
    framed = attach_f60(df)
    ic = spearman_ic(framed, "ai_capex_score")
    assert ic is not None
    assert ic > 0.0  # close 单调增 + ai_capex 单调增 -> 正 IC


def test_spearman_ic_constant_returns_none() -> None:
    df = pl.DataFrame(
        {
            "trade_date": [date(2020, 1, 1)] * 40,
            "close": [100.0] * 40,
            "ai_capex_score": [50.0] * 40,
            "f60": [0.0] * 40,
        }
    )
    assert spearman_ic(df, "ai_capex_score") is None  # 常数输入


def test_overall_and_yearly_ic() -> None:
    df = _make_panel()
    framed = attach_f60(df)
    overall = overall_ic(framed, ["ai_capex_score"])
    assert "ai_capex_score" in overall
    yearly = yearly_ic(framed, ["ai_capex_score"])
    assert yearly["year"].min() == 2020
    cur = current_cross_section(framed, ["ai_capex_score"])
    assert len(cur) == 1


def test_run_backtest_modes() -> None:
    df = _make_panel()
    result = run_backtest(df)
    assert len(result) == 4
    cols = result.columns
    assert "variante" in cols
    assert "全周期Sharpe" in cols and "样本外Sharpe" in cols
    # buy_hold 恒为 1.0 权重
    bh = result.filter(pl.col("variante") == "buy_hold").to_dicts()[0]
    assert bh["全周期MaxDD%"] == pytest.approx(0.0, abs=0.01)  # 单调上涨无回撤


def test_load_research_config_from_yaml() -> None:
    from stock_strategy.industry.semiconductor.config import (
        load_semiconductor_research_config,
    )

    cfg = load_semiconductor_research_config("config/strategy/semiconductor_research.yaml")
    assert cfg.industry == "270100"
    assert cfg.oos_start == date(2022, 1, 1)
    assert cfg.fwd_horizon == 60
    assert cfg.ic_legs == ("ai_capex_score",)
    assert cfg.defense.doi_ge == 70.0
    assert cfg.defense.drawdown_weight == 0.3


def test_defense_config_overrides_thresholds() -> None:
    from stock_strategy.industry.semiconductor.config import DefenseConfig

    # 更保守的防守：DOI≥60 即降仓
    d = DefenseConfig(doi_ge=60.0)
    assert position_weight("inv_high", 50.0, 65.0, d) == 0.3  # 原 70 阈值下是 1.0
    assert position_weight("inv_high", 50.0, 65.0) == 1.0  # 默认阈值 70 不清


def test_attach_f60_custom_horizon() -> None:
    from stock_strategy.industry.semiconductor.ic import attach_f60

    df = _make_panel()
    f30 = attach_f60(df, fwd=30)
    assert "f60" in f30.columns
    assert f30["f60"].null_count() == 30  # 最后 30 天 f60 为 null
    f60 = attach_f60(df, fwd=60)
    assert f60["f60"].null_count() == 60


def test_sweep_drawdown_weight_rows() -> None:
    from stock_strategy.industry.semiconductor.sensitivity import sweep_drawdown_weight

    df = _make_panel()
    res = sweep_drawdown_weight(df, weights=(0.1, 0.3, 0.5, 0.7))
    assert len(res) == 4
    assert set(res.columns) == {
        "weight",
        "全CAGR%",
        "全MaxDD%",
        "全Sharpe",
        "外CAGR%",
        "外MaxDD%",
        "外Sharpe",
        "24+CAGR%",
        "24+MaxDD%",
        "24+Sharpe",
    }
    assert res["weight"].to_list() == [0.1, 0.3, 0.5, 0.7]


def test_sweep_doi_threshold_rows() -> None:
    from stock_strategy.industry.semiconductor.sensitivity import sweep_doi_threshold

    df = _make_panel()
    res = sweep_doi_threshold(df, thresholds=(60, 70, 80))
    assert len(res) == 3
    assert res["th"].to_list() == [60, 70, 80]


def test_validation_module_imports() -> None:
    from stock_strategy.industry.semiconductor import (
        run_validation,
        sweep_doi_threshold,
        sweep_drawdown_weight,
    )

    assert callable(run_validation)
    assert callable(sweep_drawdown_weight)
    assert callable(sweep_doi_threshold)


def test_load_panel_uses_storage_dir_for_semiconductor_legs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from stock_strategy.industry.semiconductor.data import load_semiconductor_panel

    mart_dir = tmp_path / "curated" / "mart"
    mart_dir.mkdir(parents=True)
    pl.DataFrame(
        {
            "trade_date": [date(2020, 1, 1), date(2020, 1, 2)],
            "industry_code": ["270100", "270100"],
            "close": [100.0, 101.0],
        }
    ).write_parquet(mart_dir / "industry_l2_panel_daily.parquet")

    captured: dict[str, Path | None] = {}

    def _fake_load_latest(*, artifact_root: Path | str | None = None) -> pl.DataFrame:
        captured["artifact_root"] = Path(artifact_root) if artifact_root is not None else None
        return pl.DataFrame(
            {
                "trade_date": [date(2020, 1, 1), date(2020, 1, 2)],
                "industry_code": ["270100", "270100"],
                "demand_score": [60.0, 61.0],
                "supply_score": [40.0, 41.0],
                "scissors_score": [20.0, 20.0],
                "ai_capex_score": [70.0, 71.0],
            }
        )

    import stock_analytics.pipelines.semiconductor as semi_pipe

    monkeypatch.setattr(semi_pipe, "load_latest_semiconductor_legs", _fake_load_latest)

    panel = load_semiconductor_panel(storage_dir=tmp_path)

    assert captured["artifact_root"] == tmp_path / "analytics" / "semiconductor"
    assert panel["demand_score"].to_list() == [60.0, 61.0]
    assert "inventory_score" in panel.columns
