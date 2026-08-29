"""宏观风控多策略跨周期稳定性审计引擎。

负责生产级执行：
1. 跨 6 大宏观范式分段回溯切片对账；
2. 历史 4 大极端危机压力测试 (Stress Testing)；
3. 任意时点入场滚动 1 年 (252D) 与 3 年 (756D) 胜率与回撤分布统计；
4. 双引擎熊市区间识别 (价格回撤 + 宏观因子共振) 与策略表现/回本时长统计；
5. 输出标准化 CSV、高清 4 合 1 对比图与 Markdown 审计研报；
6. 提供策略退化回归断言门禁 (Regression Guardrails)。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import polars as pl
import yaml

from stock_core.utils.logger import logger
from stock_data.catalog import DataCatalog
from stock_strategy.macro.assembly import assemble_macro_panel, load_price_panel
from stock_strategy.macro.audit_calc import (
    compute_bear_regimes,
    compute_rolling_stats,
    compute_slice_metrics,
    compute_stress_test,
)
from stock_strategy.macro.audit_render import (
    render_audit_markdown,
    render_stability_charts,
)
from stock_strategy.macro.report import (
    _runner_for,
    load_all_strategy_specs,
    load_benchmarks,
    nav_from_close,
)


def _load_risk_factors(risk_root: Path) -> pl.DataFrame:
    """加载宏观风控因子产物（熊市因子共振识别用），缺失时返回空表。"""
    try:
        from stock_analytics.pipelines.macro_risk import load_latest_risk_factors

        _, factors, _ = load_latest_risk_factors(risk_root)
        return factors if factors is not None else pl.DataFrame()
    except Exception as exc:  # noqa: BLE001
        logger.warning("加载宏观风控因子产物失败，熊市因子共振识别将跳过: %s", exc)
        return pl.DataFrame()


# 默认 6 大宏观范式定义（配置缺失时的默认回退）
_DEFAULT_MACRO_REGIMES: list[tuple[str, date, date, str]] = [
    ("范式一：杠杆牛熊", date(2015, 1, 5), date(2015, 12, 31), "配资杠杆狂热 -> 破位暴跌"),
    ("范式二：供给侧蓝筹", date(2016, 1, 4), date(2017, 12, 29), "三去一降一补+白马价值风格"),
    ("范式三：去杠杆慢熊", date(2018, 1, 2), date(2018, 12, 28), "中美贸易摩擦+信用收紧出清"),
    ("范式四：公募抱团牛", date(2019, 1, 2), date(2021, 2, 18), "核心资产抱团+创业板主升"),
    ("范式五：存量红利防守", date(2021, 2, 19), date(2024, 1, 31), "高估值泡沫出清+红利防御"),
    ("范式六：政策新质牛", date(2024, 2, 1), date(2026, 8, 28), "政策底托底+科技弹性爆发"),
]

# 默认 4 大极端危机压力测试情景
_DEFAULT_STRESS_TESTS: list[tuple[str, date, date, str]] = [
    ("2015 杠杆股灾", date(2015, 6, 15), date(2015, 8, 26), "千股跌停与去杠杆多杀多"),
    ("2018 慢熊主跌段", date(2018, 1, 29), date(2018, 10, 19), "贸易摩擦升级与股权质押爆雷"),
    ("2020 疫情首波冲击", date(2020, 1, 23), date(2020, 3, 23), "全球流动性危机与海外熔断"),
    ("2024 微盘流动性踩踏", date(2024, 1, 2), date(2024, 2, 5), "量化DMA与微盘踩踏极端杀跌"),
]

MACRO_REGIMES = _DEFAULT_MACRO_REGIMES
STRESS_TEST_PERIODS = _DEFAULT_STRESS_TESTS


def load_macro_regimes(
    config_path: Path | str = "config/strategy/macro_risk.yaml",
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
    except Exception:
        pass
    return list(_DEFAULT_MACRO_REGIMES)


def load_stress_tests(
    config_path: Path | str = "config/strategy/macro_risk.yaml",
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
    except Exception:
        pass
    return list(_DEFAULT_STRESS_TESTS)


@dataclass(frozen=True)
class StabilityAuditResult:
    """稳定性审计结果容器。"""

    wide_nav: pl.DataFrame
    regime_df: pd.DataFrame
    stress_df: pd.DataFrame
    rolling_df: pd.DataFrame
    bear_df: pd.DataFrame
    report_path: Path
    chart_path: Path | None


def run_full_stability_audit(
    *,
    config_path: Path | str = "config/strategy/macro_risk.yaml",
    risk_root: Path | str = "data/analytics/macro_risk",
    output_dir: Path | str = "data/analytics/macro_strategy/audit",
    data_source: str = "tushare",
    generate_charts: bool = True,
) -> StabilityAuditResult:
    """运行全套生产级多策略跨周期稳定性审计。"""
    config_path = Path(config_path)
    risk_root = Path(risk_root)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    catalog = DataCatalog(data_source=data_source)
    strategy_specs = load_all_strategy_specs(config_path)

    full_series: dict[str, pl.DataFrame] = {}
    start_d: date | None = None
    end_d: date | None = None

    for name, spec in strategy_specs.items():
        runner, benchmark = _runner_for(spec)
        panel = assemble_macro_panel(
            catalog=catalog,
            benchmark_symbol=benchmark,
            risk_root=risk_root,
        )
        price_panel = load_price_panel(catalog=catalog, symbols=tuple(spec["symbols"]))
        nav = runner.backtest(panel, price_panel)
        full_series[name] = nav
        if start_d is None and not panel.is_empty():
            min_date = panel["trade_date"].min()
            max_date = panel["trade_date"].max()
            if isinstance(min_date, date):
                start_d = min_date
            if isinstance(max_date, date):
                end_d = max_date

    benchmarks_list = load_benchmarks(config_path)
    for symbol, label in benchmarks_list:
        close = catalog.load_bars(
            symbol=symbol,
            dataset="index_daily_bar",
            columns=["trade_date", "close"],
        )
        full_series[label] = nav_from_close(close, start_date=start_d, end_date=end_d)

    wide_df: pl.DataFrame | None = None
    for name, nav_df in full_series.items():
        s = nav_df.rename({"nav": name})
        wide_df = s if wide_df is None else wide_df.join(s, on="trade_date", how="inner")

    if wide_df is None:
        raise RuntimeError("未能生成任何策略回测数据")

    wide_df = wide_df.sort("trade_date")
    wide_df.write_csv(output_dir / "stability_nav_wide.csv")
    all_cols = [c for c in wide_df.columns if c != "trade_date"]

    macro_regimes = load_macro_regimes(config_path)
    regime_rows: list[dict[str, Any]] = []
    for r_name, r_start, r_end, _r_desc in macro_regimes:
        sub_df = wide_df.filter((pl.col("trade_date") >= r_start) & (pl.col("trade_date") <= r_end))
        if sub_df.is_empty():
            continue
        stats = compute_slice_metrics(sub_df, all_cols)
        for col in all_cols:
            st = stats.get(col, {})
            regime_rows.append(
                {
                    "宏观范式": r_name,
                    "时间区间": f"{r_start} ~ {r_end}",
                    "标的/策略": col,
                    "区间累计收益": st.get("total_return", 0.0),
                    "年化收益(CAGR)": st.get("annualized_return", 0.0),
                    "区间最大回撤": st.get("max_drawdown", 0.0),
                    "年化波动率": st.get("volatility", 0.0),
                    "夏普比率": st.get("sharpe", 0.0),
                }
            )
    regime_df = pd.DataFrame(regime_rows)
    regime_df.to_csv(output_dir / "regime_comparison.csv", index=False)

    stress_tests = load_stress_tests(config_path)
    stress_df = compute_stress_test(wide_df, all_cols, stress_tests)
    stress_df.to_csv(output_dir / "stress_test_comparison.csv", index=False)

    rolling_df = compute_rolling_stats(wide_df, all_cols, windows=(252, 756))
    rolling_df.to_csv(output_dir / "rolling_stability_stats.csv", index=False)

    # 双引擎熊市区间识别（价格回撤 + 因子共振）
    risk_factors = _load_risk_factors(risk_root)
    bear_df = compute_bear_regimes(wide_df, risk_factors, all_cols)
    bear_df.to_csv(output_dir / "bear_regime_comparison.csv", index=False)

    chart_path: Path | None = None
    r3_subset = rolling_df[rolling_df["滚动窗口"].str.contains("3 年")].copy()
    if generate_charts:
        chart_path = render_stability_charts(
            wide_df=wide_df,
            regime_df=regime_df,
            stress_df=stress_df,
            r3=r3_subset,
            output_dir=output_dir,
        )

    report_path = output_dir / "strategy_stability_report.md"
    render_audit_markdown(
        wide_df=wide_df,
        regime_df=regime_df,
        stress_df=stress_df,
        rolling_df=rolling_df,
        bear_df=bear_df,
        chart_file=chart_path,
        report_file=report_path,
    )

    logger.info("多策略稳定性审计完成，产物输出至: %s", output_dir)
    return StabilityAuditResult(
        wide_nav=wide_df,
        regime_df=regime_df,
        stress_df=stress_df,
        rolling_df=rolling_df,
        bear_df=bear_df,
        report_path=report_path,
        chart_path=chart_path,
    )


def assert_stability_guardrails(result: StabilityAuditResult) -> None:
    """执行策略防退化回归门禁断言 (CI Guardrails)。"""
    stress_df = result.stress_df
    if not stress_df.empty:
        for strat in ["macro_rotation_v4", "macro_rotation_v4_etf", "macro_rotation_v6"]:
            sub = stress_df[
                (stress_df["压力测试情景"].str.contains("2024")) & (stress_df["标的/策略"] == strat)
            ]
            if not sub.empty:
                mdd = float(sub["区间最深回撤"].iloc[0])
                if mdd < -0.15:
                    raise AssertionError(f"{strat} 在 2024 危机回撤退化: {mdd:.2%}")

    rolling_df = result.rolling_df
    if not rolling_df.empty:
        for strat in ["macro_rotation_v4", "macro_rotation_v4_etf"]:
            sub_r = rolling_df[
                (
                    rolling_df["滚动窗口"].str.contains("3 年")
                    | rolling_df["滚动窗口"].str.contains("756")
                )
                & (rolling_df["标的/策略"] == strat)
            ]
            if not sub_r.empty:
                win_bench = float(sub_r["跑赢基准(全指)概率"].iloc[0])
                if win_bench < 0.80:
                    raise AssertionError(f"{strat} 3年跑赢全指概率胜率退化: {win_bench:.2%}")
                if "正收益胜率" in sub_r.columns:
                    win_pos = float(sub_r["正收益胜率"].iloc[0])
                    if win_pos < 0.65:
                        raise AssertionError(f"{strat} 3年绝对正收益胜率退化: {win_pos:.2%}")


__all__ = [
    "MACRO_REGIMES",
    "STRESS_TEST_PERIODS",
    "StabilityAuditResult",
    "assert_stability_guardrails",
    "compute_rolling_stats",
    "compute_slice_metrics",
    "compute_stress_test",
    "load_macro_regimes",
    "load_stress_tests",
    "run_full_stability_audit",
]
