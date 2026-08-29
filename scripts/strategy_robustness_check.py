"""宏观策略稳健性审计：参数敏感性网格 + 近期样本外切片。

用途（防过拟合自检）：
1. 参数敏感性：对 panic_threshold / overheat_threshold / ma_window 做扰动网格，
   重跑 V5/V6 输出 CAGR / 最大回撤 / 夏普矩阵，评估绩效对参数选择的依赖程度。
   若配置参数在大范围扰动下绩效塌陷或极度敏感，提示过拟合风险。
2. 近期切片：以 config 固定参数（不重调）展示 2023-01-01 以来表现 vs 全周期，
   提供"未重调参的近期样本外"证据。

用法:
    uv run python scripts/strategy_robustness_check.py [--output-dir data/analytics/macro_strategy/robustness]
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from stock_data.catalog import DataCatalog
from stock_strategy.macro.assembly import assemble_macro_panel, load_price_panel
from stock_strategy.macro.report import compute_metrics
from stock_strategy.macro.runner import MacroRiskRunner
from stock_strategy.pool import create_strategy

DEFAULT_CONFIG_PATH = Path("config/strategy/macro_risk.yaml")
DEFAULT_RISK_ROOT = Path("data/analytics/macro_risk")
DEFAULT_OUTPUT_DIR = Path("data/analytics/macro_strategy/robustness")

# 参数扰动网格（配置值为 panic=75 / overheat=65 / ma_window=20）
PARAM_GRID = {
    "panic_threshold": [70.0, 75.0, 80.0],
    "overheat_threshold": [60.0, 65.0, 70.0],
    "ma_window": [10, 20, 30],
}
CONFIG_PARAMS = {"panic_threshold": 75.0, "overheat_threshold": 65.0, "ma_window": 20}

HOLDOUT_START = date(2023, 1, 1)


def _make_runner(spec: dict[str, Any], **param_overrides: float | int) -> MacroRiskRunner:
    """按 spec 实例化 runner，用参数覆盖替换 thresholds/ma_window。"""
    benchmark = str(spec.get("benchmark_symbol", "000985.CSI"))
    symbols = tuple(spec.get("symbols", [benchmark]))
    raw_weights = spec.get("initial_weights", {s: 1.0 / len(symbols) for s in symbols})
    initial_weights = {str(k): float(v) for k, v in raw_weights.items()}

    friction = dict(spec.get("friction", {}))
    commission_rate = float(friction.get("commission_rate", spec.get("commission_rate", 0.0)))
    slippage_rate = float(friction.get("slippage_rate", spec.get("slippage_rate", 0.0)))
    rebalance_deadband = float(
        friction.get("rebalance_deadband", spec.get("rebalance_deadband", 0.0))
    )

    strategy_kwargs: dict[str, Any] = {
        "symbols": symbols,
        "initial_weights": initial_weights,
        "benchmark_symbol": benchmark,
    }
    for k, v in spec.items():
        if k not in {
            "strategy_class",
            "symbols",
            "initial_weights",
            "benchmark_symbol",
            "friction",
            "thresholds",
        }:
            strategy_kwargs[k] = v
    if "thresholds" in spec and isinstance(spec["thresholds"], dict):
        for tk, tv in spec["thresholds"].items():
            strategy_kwargs[tk] = tv
    strategy_kwargs.update(param_overrides)

    strategy = create_strategy(str(str(spec["strategy_class"])), **strategy_kwargs)
    return MacroRiskRunner(
        strategy,
        symbols=symbols,
        initial_weights=initial_weights,
        strategy_name=spec["strategy_class"],
        data_source="tushare",
        commission_rate=commission_rate,
        slippage_rate=slippage_rate,
        rebalance_deadband=rebalance_deadband,
    )


def _metrics_from_nav(nav: pl.DataFrame) -> dict[str, float]:
    if nav.is_empty() or len(nav) < 2:
        return {"cagr": 0.0, "max_drawdown": 0.0, "sharpe": 0.0}
    m = compute_metrics(nav)
    return {
        "cagr": m["cagr"],
        "max_drawdown": m["max_drawdown"],
        "sharpe": m["sharpe_ratio"],
    }


def run_parameter_sweep(
    spec: dict[str, Any],
    panel: pl.DataFrame,
    price_panel: pl.DataFrame,
) -> list[dict[str, Any]]:
    """对单个策略跑参数网格，返回每组合的绩效行。"""
    rows: list[dict[str, Any]] = []
    for panic in PARAM_GRID["panic_threshold"]:
        for overheat in PARAM_GRID["overheat_threshold"]:
            for ma in PARAM_GRID["ma_window"]:
                runner = _make_runner(
                    spec,
                    panic_threshold=panic,
                    overheat_threshold=overheat,
                    ma_window=ma,
                )
                nav = runner.backtest(panel, price_panel)
                m = _metrics_from_nav(nav)
                rows.append(
                    {
                        "panic": panic,
                        "overheat": overheat,
                        "ma": ma,
                        "is_config": (panic, overheat, ma)
                        == (
                            CONFIG_PARAMS["panic_threshold"],
                            CONFIG_PARAMS["overheat_threshold"],
                            CONFIG_PARAMS["ma_window"],
                        ),
                        **m,
                    }
                )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="宏观策略参数敏感性与近期切片稳健性审计。")
    parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--risk-root", type=str, default=str(DEFAULT_RISK_ROOT))
    parser.add_argument("--config", type=str, default=str(DEFAULT_CONFIG_PATH))
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8")) or {}
    strategies = config.get("strategies", {})
    targets = [k for k in ("macro_rotation_v5", "macro_rotation_v6") if k in strategies]

    catalog = DataCatalog(data_source="tushare")
    sweep_lines: list[str] = []
    holdout_lines: list[str] = []

    for name in targets:
        spec = strategies[name]
        panel = assemble_macro_panel(
            catalog=catalog,
            benchmark_symbol=str(spec["benchmark_symbol"]),
            risk_root=args.risk_root,
        )
        price_panel = load_price_panel(catalog=catalog, symbols=tuple(spec["symbols"]))

        # 1) 参数敏感性网格
        rows = run_parameter_sweep(spec, panel, price_panel)
        cagrs = [r["cagr"] for r in rows]
        cfg = next(r for r in rows if r["is_config"])
        sweep_lines.append(f"## {name}")
        sweep_lines.append("")
        sweep_lines.append("| panic | overheat | ma_window | CAGR | 最大回撤 | 夏普 | 配置值 |")
        sweep_lines.append("| ---: | ---: | ---: | ---: | ---: | ---: | :---: |")
        for r in sorted(rows, key=lambda x: (x["panic"], x["overheat"], x["ma"])):
            mark = "★" if r["is_config"] else ""
            sweep_lines.append(
                f"| {r['panic']:.0f} | {r['overheat']:.0f} | {r['ma']} "
                f"| {r['cagr']:.2%} | {r['max_drawdown']:.2%} | {r['sharpe']:.2f} | {mark} |"
            )
        rank = sorted(cagrs, reverse=True).index(cfg["cagr"]) + 1
        sweep_lines.append("")
        sweep_lines.append(
            f"- CAGR 范围: {min(cagrs):.2%} ~ {max(cagrs):.2%} "
            f"(极差 {max(cagrs) - min(cagrs):.2%})；配置值 {cfg['cagr']:.2%} 位于网格第 {rank}/{len(cagrs)} 名。"
        )
        sweep_lines.append("")

        # 2) 近期样本外切片（固定配置参数，不重调）
        runner = _make_runner(spec)
        nav = runner.backtest(panel, price_panel)
        full = _metrics_from_nav(nav)
        nav_ho = nav.filter(pl.col("trade_date") >= HOLDOUT_START)
        hold = _metrics_from_nav(nav_ho)
        holdout_lines.append(
            f"| {name} | {full['cagr']:.2%} | {full['max_drawdown']:.2%} "
            f"| {hold['cagr']:.2%} | {hold['max_drawdown']:.2%} |"
        )

    lines = [
        "# 宏观策略稳健性审计（参数敏感性 × 近期样本外切片）",
        "",
        f"生成日期: {date.today().isoformat()}",
        "",
        "## 1. 参数敏感性网格（V5 / V6，27 组合/策略）",
        "",
        *sweep_lines,
        "## 2. 近期样本外切片（固定配置参数）",
        "",
        f"以 {HOLDOUT_START.isoformat()} 为界，配置参数保持不变（未针对近期重调），",
        "展示策略在最近 ~3.7 年独立样本上的表现 vs 全周期：",
        "",
        "| 策略 | 全周期 CAGR | 全周期回撤 | 2023后 CAGR | 2023后回撤 |",
        "| :--- | ---: | ---: | ---: | ---: |",
        *holdout_lines,
        "",
        "## 3. 解读与局限",
        "",
        "- 参数网格覆盖 panic ∈ {70,75,80} × overheat ∈ {60,65,70} × MA ∈ {10,20,30}，"
        "配置值 (75/65/20) 以 ★ 标注；",
        "- 若配置值 CAGR 显著高于网格中位数且相邻参数绩效大幅塌陷，提示对参数的过拟合依赖；",
        "- 近期切片为描述性证据：策略未随近期行情重调参数，但切片内表现仍受同一样本内阈值设计影响；",
        "- 本审计不替代真正的滚动样本外验证（walk-forward），仅作为过拟合风险的量化参考。",
        "",
    ]
    report = Path(output_dir) / "robustness_report.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"稳健性审计报告: {report}")


if __name__ == "__main__":
    main()
