"""宏观风控策略参数敏感性扫描（SOP S3 敏感性件）。

对关键策略参数做网格扫描，确认结论不是"卡点凑出来的"（防过拟合护栏）。

默认扫描：``overheat_threshold``（过热阈值）× ``ma_window``（趋势均线窗口）
网格下计算策略回测指标（CAGR / 最大回撤 / Sharpe），验证核心结论在该参数邻域
是否稳健。扫描网格与目标策略来自 ``config/strategy/macro_risk.yaml`` 的
``sensitivity`` 段（缺省回退到模块默认，不为研究参数在代码里散落硬编码）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from stock_data.catalog import DataCatalog
from stock_strategy.macro.assembly import assemble_macro_panel, load_price_panel
from stock_strategy.macro.report import compute_metrics
from stock_strategy.macro.runner import MacroRiskRunner
from stock_strategy.pool import create_strategy

_DEFAULT_CONFIG_PATH = Path("config/strategy/macro_risk.yaml")
_DEFAULT_RISK_ROOT = Path("data/analytics/macro_risk")
_DEFAULT_OUTPUT_DIR = Path("data/analytics/macro_strategy/robustness")
_DEFAULT_STRATEGY = "macro_rotation_v5_etf"

_SWEEP_SCHEMA = {
    "strategy": pl.String,
    "overheat": pl.Float64,
    "ma": pl.Int64,
    "cagr": pl.Float64,
    "max_dd": pl.Float64,
    "sharpe": pl.Float64,
}


@dataclass(frozen=True)
class SensitivityConfig:
    """参数敏感性扫描配置（``config/strategy/macro_risk.yaml`` 的 ``sensitivity`` 段）。"""

    strategy: str = _DEFAULT_STRATEGY
    overheat_grid: tuple[float, ...] = (55.0, 60.0, 62.0, 64.0, 65.0, 66.0, 70.0)
    ma_grid: tuple[int, ...] = (10, 20, 30)
    risk_root: str = str(_DEFAULT_RISK_ROOT)
    output_dir: str = str(_DEFAULT_OUTPUT_DIR)


def load_sensitivity_config(
    config_path: Path | str = _DEFAULT_CONFIG_PATH,
) -> SensitivityConfig:
    """读取敏感性扫描配置，缺省回退到模块默认。"""
    defaults = SensitivityConfig()
    try:
        payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            se = payload.get("sensitivity", {})
            if isinstance(se, dict):
                return SensitivityConfig(
                    strategy=str(se.get("strategy", defaults.strategy)),
                    overheat_grid=tuple(
                        float(v) for v in se.get("overheat_grid", defaults.overheat_grid)
                    ),
                    ma_grid=tuple(int(v) for v in se.get("ma_grid", defaults.ma_grid)),
                    risk_root=str(se.get("risk_root", defaults.risk_root)),
                    output_dir=str(se.get("output_dir", defaults.output_dir)),
                )
    except (OSError, ValueError, TypeError):
        pass
    return defaults


def _runner_for_sweep(spec: dict[str, Any], *, overheat: float, ma: int) -> MacroRiskRunner:
    """由策略配置实例化带指定 (overheat_threshold, ma_window) 的运行器。"""
    symbols = tuple(spec["symbols"])
    raw_weights = spec.get("initial_weights", {s: 1.0 / len(symbols) for s in symbols})
    initial_weights = {str(k): float(v) for k, v in raw_weights.items()}

    strategy_kwargs: dict[str, Any] = {
        "symbols": symbols,
        "initial_weights": dict(initial_weights),
        "benchmark_symbol": str(spec["benchmark_symbol"]),
        "overheat_threshold": overheat,
        "ma_window": ma,
    }
    if "thresholds" in spec and isinstance(spec["thresholds"], dict):
        for tk, tv in spec["thresholds"].items():
            strategy_kwargs[tk] = tv
    strategy_kwargs["overheat_threshold"] = overheat
    strategy_kwargs["ma_window"] = ma

    friction = dict(spec.get("friction", {}))
    strategy = create_strategy(str(spec["strategy_class"]), **strategy_kwargs)
    return MacroRiskRunner(
        strategy,
        symbols=symbols,
        initial_weights=dict(initial_weights),
        strategy_name=spec["strategy_class"],
        data_source="tushare",
        commission_rate=float(friction.get("commission_rate", 0.0)),
        slippage_rate=float(friction.get("slippage_rate", 0.0)),
        rebalance_deadband=float(friction.get("rebalance_deadband", 0.0)),
    )


def run_sensitivity_sweep(
    *,
    config_path: Path | str = _DEFAULT_CONFIG_PATH,
    risk_root: Path | str = _DEFAULT_RISK_ROOT,
    output_dir: Path | str = _DEFAULT_OUTPUT_DIR,
    overheat_grid: tuple[float, ...] | None = None,
    ma_grid: tuple[int, ...] | None = None,
    data_source: str = "tushare",
) -> pl.DataFrame:
    """执行 overheat × ma 参数网格扫描，输出 Sweep CSV（列同既有 ``overheat_sweep.csv``）。

    Returns:
        形如 ``{strategy, overheat, ma, cagr, max_dd, sharpe}`` 的扫描结果表。
    """
    cfg = load_sensitivity_config(config_path)
    overheat_grid = overheat_grid or cfg.overheat_grid
    ma_grid = ma_grid or cfg.ma_grid

    payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    strategies = payload.get("strategies", {})
    spec = strategies.get(cfg.strategy, {})
    if not spec:
        raise ValueError(f"配置中缺少策略: {cfg.strategy}")

    catalog = DataCatalog(data_source=data_source)
    panel = assemble_macro_panel(
        catalog=catalog,
        benchmark_symbol=str(spec["benchmark_symbol"]),
        risk_root=risk_root,
        extra_factor_cols=spec.get("panel_extra_cols", ()),
    )
    price_panel = load_price_panel(catalog=catalog, symbols=tuple(spec["symbols"]))

    rows: list[dict[str, Any]] = []
    for overheat in overheat_grid:
        for ma in ma_grid:
            runner = _runner_for_sweep(spec, overheat=float(overheat), ma=int(ma))
            nav = runner.backtest(panel, price_panel)
            metrics = compute_metrics(nav)
            rows.append(
                {
                    "strategy": cfg.strategy,
                    "overheat": float(overheat),
                    "ma": int(ma),
                    "cagr": float(metrics["cagr"]),
                    "max_dd": float(metrics["max_drawdown"]),
                    "sharpe": float(metrics["sharpe_ratio"]),
                }
            )

    result = pl.DataFrame(rows, schema=_SWEEP_SCHEMA).sort(["overheat", "ma"])
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    result.write_csv(out / "overheat_sweep.csv")
    return result


__all__ = [
    "SensitivityConfig",
    "load_sensitivity_config",
    "run_sensitivity_sweep",
]
