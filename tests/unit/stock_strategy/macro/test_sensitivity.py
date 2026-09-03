"""宏观风控策略敏感性扫描单元测试。

- 配置解析与默认回退；
- ``run_sensitivity_sweep`` 网格排序、CSV Schema 正确（不触碰真实数据/策略）。
"""

from __future__ import annotations

import polars as pl

from stock_strategy.macro.sensitivity import (
    load_sensitivity_config,
    run_sensitivity_sweep,
)


def test_load_sensitivity_config_defaults() -> None:
    """配置缺省回退到模块默认值。"""
    cfg = load_sensitivity_config()
    assert cfg.strategy == "macro_rotation_v5_etf"
    assert isinstance(cfg.overheat_grid, tuple) and cfg.overheat_grid
    assert isinstance(cfg.ma_grid, tuple) and cfg.ma_grid


def test_load_sensitivity_config_from_dict(monkeypatch, tmp_path) -> None:
    """从配置文件的 ``sensitivity`` 段正确读取网格。"""
    cfg_file = tmp_path / "macro_risk.yaml"
    cfg_file.write_text(
        "sensitivity:\n"
        "  strategy: macro_rotation_v5_etf\n"
        "  overheat_grid: [60.0, 65.0]\n"
        "  ma_grid: [20]\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    cfg = load_sensitivity_config(cfg_file)
    assert cfg.overheat_grid == (60.0, 65.0)
    assert cfg.ma_grid == (20,)


def test_run_sensitivity_sweep_grid_and_schema(monkeypatch, tmp_path) -> None:
    """网格扫描按 (overheat, ma) 排序，输出 Schema 正确。"""

    class _FakeRunner:
        def __init__(self, *a, **k) -> None:
            self.backtest_called = False

        def backtest(self, panel, price_panel) -> pl.DataFrame:
            self.backtest_called = True
            return pl.DataFrame(
                {
                    "trade_date": [pl.date(2023, 1, 3), pl.date(2023, 1, 4)],
                    "nav": [1.0, 1.05],
                }
            )

    panel = pl.DataFrame(
        {"trade_date": [pl.date(2023, 1, 3), pl.date(2023, 1, 4), pl.date(2023, 1, 5)]}
    )

    monkeypatch.setattr(
        "stock_strategy.macro.sensitivity.create_strategy", lambda *a, **k: object()
    )
    monkeypatch.setattr("stock_strategy.macro.sensitivity.MacroRiskRunner", _FakeRunner)
    monkeypatch.setattr(
        "stock_strategy.macro.sensitivity.assemble_macro_panel",
        lambda **k: panel,
    )
    monkeypatch.setattr("stock_strategy.macro.sensitivity.load_price_panel", lambda **k: panel)

    result = run_sensitivity_sweep(
        config_path="config/strategy/macro_risk.yaml",
        output_dir=str(tmp_path),
        overheat_grid=(65.0, 60.0),
        ma_grid=(20, 10),
    )

    assert set(result.columns) == {
        "strategy",
        "overheat",
        "ma",
        "cagr",
        "max_dd",
        "sharpe",
    }
    # 排序：overheat 升序、ma 升序
    assert result["overheat"].to_list() == [60.0, 60.0, 65.0, 65.0]
    assert result["ma"].to_list() == [10, 20, 10, 20]
    assert (tmp_path / "overheat_sweep.csv").exists()
    assert result.height == 4
