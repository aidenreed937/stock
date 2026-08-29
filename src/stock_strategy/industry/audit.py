"""申万行业多策略跨周期稳定性审计引擎。

负责生产级执行：
1. 跨 6 大宏观范式分段回溯切片对账；
2. 历史 4 大极端危机压力测试 (Stress Testing)；
3. 任意时点入场滚动 1 年 (252D) 与 3 年 (756D) 胜率与回撤分布统计；
4. 输出标准化 CSV、高清 4 合 1 对比图与 Markdown 审计研报；
5. 提供策略退化回归断言门禁 (Regression Guardrails)。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import polars as pl
import yaml

from stock_core.utils.logger import logger
from stock_data.catalog import DataCatalog
from stock_strategy.industry.assembly import (
    assemble_industry_panel,
    load_industry_price_panel,
)
from stock_strategy.industry.audit_calc import (
    compute_rolling_stats,
    compute_slice_metrics,
    compute_stress_test,
)
from stock_strategy.industry.audit_render import (
    render_industry_audit_markdown,
    render_industry_stability_charts,
)
from stock_strategy.industry.report import (
    load_all_industry_strategy_specs,
    load_industry_benchmarks,
    nav_from_close,
)
from stock_strategy.industry.runner import IndustryStrategyRunner
from stock_strategy.pool import create_strategy

_DEFAULT_OUTPUT_DIR = Path("data/analytics/industry_strategy/audit")
_DEFAULT_CONFIG_PATH = Path("config/strategy/industry_rotation.yaml")


def load_macro_regimes(
    config_path: Path | str = _DEFAULT_CONFIG_PATH,
) -> list[tuple[str, date, date, str]]:
    """读取 6 大跨周期历史宏观范式切片。"""
    try:
        payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        if isinstance(payload, dict) and "macro_regimes" in payload:
            items = payload["macro_regimes"]
            if isinstance(items, list):
                res = []
                for r in items:
                    if (
                        isinstance(r, dict)
                        and "name" in r
                        and "start_date" in r
                        and "end_date" in r
                    ):
                        s_d = date.fromisoformat(str(r["start_date"]))
                        e_d = date.fromisoformat(str(r["end_date"]))
                        res.append((str(r["name"]), s_d, e_d, str(r.get("description", ""))))
                if res:
                    return res
    except Exception as exc:
        logger.warning(f"读取宏观范式切片失败: {exc}")
    return []


def load_stress_tests(
    config_path: Path | str = _DEFAULT_CONFIG_PATH,
) -> list[tuple[str, date, date, str]]:
    """读取历史极端危机压力测试情景。"""
    try:
        payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        if isinstance(payload, dict) and "stress_tests" in payload:
            items = payload["stress_tests"]
            if isinstance(items, list):
                res = []
                for st in items:
                    if (
                        isinstance(st, dict)
                        and "name" in st
                        and "start_date" in st
                        and "end_date" in st
                    ):
                        s_d = date.fromisoformat(str(st["start_date"]))
                        e_d = date.fromisoformat(str(st["end_date"]))
                        res.append((str(st["name"]), s_d, e_d, str(st.get("description", ""))))
                if res:
                    return res
    except Exception as exc:
        logger.warning(f"读取压力测试情景失败: {exc}")
    return []


def run_industry_strategy_audit(
    *,
    config_path: Path | str = _DEFAULT_CONFIG_PATH,
    factor_root: Path | str = "data/analytics/industry_structure",
    macro_risk_root: Path | str = "data/analytics/macro_risk",
    output_dir: Path | str = _DEFAULT_OUTPUT_DIR,
    assert_guardrails: bool = False,
) -> dict[str, Any]:
    """执行申万行业策略跨周期稳定性审计全流程。"""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    catalog = DataCatalog(data_source="tushare")

    benchmarks = load_industry_benchmarks(config_path)
    specs = load_all_industry_strategy_specs(config_path)
    macro_regimes = load_macro_regimes(config_path)
    stress_tests = load_stress_tests(config_path)

    # 1. 装配全周期面板
    panel = assemble_industry_panel(
        catalog=catalog,
        factor_root=factor_root,
        macro_risk_root=macro_risk_root,
    )
    price_panel = load_industry_price_panel(catalog=catalog)

    min_panel_d = panel["trade_date"].min()
    max_panel_d = panel["trade_date"].max()
    actual_start: date | None = min_panel_d if isinstance(min_panel_d, date) else None
    actual_end: date | None = max_panel_d if isinstance(max_panel_d, date) else None

    # 2. 执行全周期回测并对齐宽表
    wide_map: dict[str, pl.DataFrame] = {}

    for symbol, label in benchmarks:
        bars = catalog.load_bars(symbol=symbol, dataset="index_daily_bar")
        b_nav = nav_from_close(bars, start_date=actual_start, end_date=actual_end)
        if not b_nav.is_empty():
            wide_map[label] = b_nav

    for key, spec in specs.items():
        cls_name = str(spec.get("strategy_class", ""))
        friction = spec.get("friction", {})
        comm = float(friction.get("commission_rate", 0.0001))
        slip = float(friction.get("slippage_rate", 0.0005))
        dead = float(friction.get("rebalance_deadband", 0.03))

        kwargs = {
            k: v
            for k, v in spec.items()
            if k not in ("strategy_class", "friction", "description", "name")
        }
        strat = create_strategy(cls_name, **kwargs)
        runner = IndustryStrategyRunner(
            strat,
            strategy_name=key,
            commission_rate=comm,
            slippage_rate=slip,
            rebalance_deadband=dead,
        )
        s_nav = runner.backtest(panel, price_panel)
        if not s_nav.is_empty():
            wide_map[key] = s_nav

    base_dates = panel["trade_date"].unique(maintain_order=True).sort()
    wide_df = pl.DataFrame({"trade_date": base_dates})
    for name, df in wide_map.items():
        sub = df.select(["trade_date", pl.col("nav").alias(name)])
        wide_df = wide_df.join(sub, on="trade_date", how="left")

    cols = [c for c in wide_df.columns if c != "trade_date"]

    # 3. 计算 6 大宏观范式切片指标
    regime_rows: list[dict[str, Any]] = []
    for r_name, r_start, r_end, r_desc in macro_regimes:
        slice_df = wide_df.filter(
            (pl.col("trade_date") >= r_start) & (pl.col("trade_date") <= r_end)
        )
        if slice_df.is_empty():
            continue
        slice_stats = compute_slice_metrics(slice_df, cols)
        for c in cols:
            st = slice_stats[c]
            regime_rows.append(
                {
                    "macro_regime": r_name,
                    "description": r_desc,
                    "strategy": c,
                    "total_return": round(st["total_return"] * 100.0, 2),
                    "cagr": round(st["cagr"] * 100.0, 2),
                    "max_drawdown": round(abs(st["max_drawdown"]) * 100.0, 2),
                    "sharpe": round(st["sharpe"], 2),
                }
            )
    regime_df = pd.DataFrame(regime_rows)
    regime_df.to_csv(out_dir / "audit_regimes.csv", index=False)

    # 4. 计算 4 大极端危机压力测试
    stress_df = compute_stress_test(wide_df, cols, stress_tests)
    stress_df.to_csv(out_dir / "audit_stress_test.csv", index=False)

    # 5. 计算滚动 1 年与 3 年胜率
    r1_df = compute_rolling_stats(wide_df, cols, window=252)
    r1_df.to_csv(out_dir / "audit_rolling_1y.csv", index=False)

    r3_df = compute_rolling_stats(wide_df, cols, window=756)
    r3_df.to_csv(out_dir / "audit_rolling_3y.csv", index=False)

    # 6. 执行门禁断言 (Regression Guardrails)
    guardrails = _evaluate_guardrails(regime_df, stress_df, r1_df, r3_df)

    # 7. 渲染图表与研报
    chart_p = render_industry_stability_charts(wide_df, regime_df, stress_df, r3_df, out_dir)
    md_p = out_dir / "strategy_stability_report.md"
    render_industry_audit_markdown(
        regime_df, stress_df, r1_df, r3_df, guardrails, md_p, chart_path=chart_p
    )

    if assert_guardrails:
        failed = [g for g in guardrails if not g["passed"]]
        if failed:
            msg = f"行业策略审计断言失败: {len(failed)} 个门禁未达标: {failed}"
            logger.error(msg)
            raise RuntimeError(msg)

    return {
        "regime_df": regime_df,
        "stress_df": stress_df,
        "rolling_1y_df": r1_df,
        "rolling_3y_df": r3_df,
        "guardrails": guardrails,
        "report_markdown": str(md_p),
        "chart_png": str(chart_p),
    }


def _evaluate_guardrails(
    regime_df: pd.DataFrame,
    stress_df: pd.DataFrame,
    r1_df: pd.DataFrame,
    r3_df: pd.DataFrame,
) -> list[dict[str, Any]]:
    """评估行业策略防退化 CI 门禁断言。"""
    guards: list[dict[str, Any]] = []

    # 门禁 1: 滚动 3 年平均年化复合收益率 (CAGR) 显著跑赢大盘 (全指仅 0.34%)
    if not r3_df.empty:
        for strat in [
            "industry_momentum",
            "industry_reversal",
            "industry_scissors",
            "industry_meta_router",
        ]:
            sub = r3_df[r3_df["strategy"] == strat]
            if not sub.empty:
                cagr_m = float(sub["cagr_mean"].iloc[0])
                guards.append(
                    {
                        "metric": f"{strat} 滚动3Y平均年化",
                        "threshold": ">= 2.5%",
                        "actual": f"{cagr_m:+.2f}%",
                        "passed": cagr_m >= 2.5,
                    }
                )

    # 门禁 2: 滚动 3 年持有正收益胜率 >= 50%
    if not r3_df.empty:
        for strat in [
            "industry_momentum",
            "industry_reversal",
            "industry_scissors",
            "industry_meta_router",
        ]:
            sub = r3_df[r3_df["strategy"] == strat]
            if not sub.empty:
                wr = float(sub["win_rate"].iloc[0])
                guards.append(
                    {
                        "metric": f"{strat} 滚动3Y胜率",
                        "threshold": ">= 50.0%",
                        "actual": f"{wr:.1f}%",
                        "passed": wr >= 50.0,
                    }
                )

    # 门禁 3: 危机压力测试最深回撤控制在 60% 以内
    if not stress_df.empty:
        for strat in ["industry_reversal", "industry_scissors", "industry_meta_router"]:
            sub = stress_df[stress_df["strategy"] == strat]
            if not sub.empty:
                max_dd = float(sub["max_drawdown"].max())
                guards.append(
                    {
                        "metric": f"{strat} 危机最深回撤",
                        "threshold": "<= 60.0%",
                        "actual": f"{max_dd:.1f}%",
                        "passed": max_dd <= 60.0,
                    }
                )

    return guards


__all__ = ["load_macro_regimes", "load_stress_tests", "run_industry_strategy_audit"]
