"""宏观风控多策略跨周期稳定性审计引擎。

负责生产级执行：
1. 跨 6 大宏观范式分段回溯切片对账；
2. 历史 4 大极端危机压力测试 (Stress Testing)；
3. 任意时点入场滚动 1 年 (252D) 与 3 年 (756D) 胜率与回撤分布统计；
4. 输出标准化 CSV、高清 4 合 1 对比图与 Markdown 审计研报；
5. 提供策略退化回归断言门禁 (Regression Guardrails)。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import sqrt
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import polars as pl

from stock_core.utils.logger import logger
from stock_data.catalog import DataCatalog
from stock_strategy.macro_assembly import assemble_macro_panel, load_price_panel
from stock_strategy.macro_audit_render import (
    render_audit_markdown,
    render_stability_charts,
)
from stock_strategy.macro_report import (
    _BENCHMARKS,
    _TRADING_DAYS_PER_YEAR,
    _runner_for,
    load_all_strategy_specs,
    nav_from_close,
)

# 6 大宏观范式定义
MACRO_REGIMES: list[tuple[str, date, date, str]] = [
    ("范式一：杠杆牛熊", date(2015, 1, 5), date(2015, 12, 31), "配资杠杆狂热 -> 破位暴跌"),
    ("范式二：供给侧蓝筹", date(2016, 1, 4), date(2017, 12, 29), "三去一降一补+白马价值风格"),
    ("范式三：去杠杆慢熊", date(2018, 1, 2), date(2018, 12, 28), "中美贸易摩擦+信用收紧出清"),
    ("范式四：公募抱团牛", date(2019, 1, 2), date(2021, 2, 18), "核心资产抱团+创业板主升"),
    ("范式五：存量红利防守", date(2021, 2, 19), date(2024, 1, 31), "高估值泡沫出清+红利防御"),
    ("范式六：政策新质牛", date(2024, 2, 1), date(2026, 8, 28), "政策底托底+科技弹性爆发"),
]

# 4 大极端危机压力测试情景
STRESS_TEST_PERIODS: list[tuple[str, date, date, str]] = [
    ("2015 杠杆股灾", date(2015, 6, 15), date(2015, 8, 26), "千股跌停与去杠杆多杀多"),
    ("2018 慢熊主跌段", date(2018, 1, 29), date(2018, 10, 19), "贸易摩擦升级与股权质押爆雷"),
    ("2020 疫情首波冲击", date(2020, 1, 23), date(2020, 3, 23), "全球流动性危机与海外熔断"),
    ("2024 微盘流动性踩踏", date(2024, 1, 2), date(2024, 2, 5), "量化DMA与微盘踩踏极端杀跌"),
]


@dataclass(frozen=True)
class StabilityAuditResult:
    """稳定性审计结果容器。"""

    wide_nav: pl.DataFrame
    regime_df: pd.DataFrame
    stress_df: pd.DataFrame
    rolling_df: pd.DataFrame
    report_path: Path
    chart_path: Path | None


def compute_slice_metrics(
    df_slice: pl.DataFrame,
    columns: list[str],
) -> dict[str, dict[str, float | None]]:
    """计算切片区间标准化绩效指标。"""
    stats_dict: dict[str, dict[str, float | None]] = {}
    n_days = max(len(df_slice) - 1, 0)
    for col in columns:
        vals = df_slice[col].to_list()
        if not vals or len(vals) < 2:
            continue
        first_val = float(vals[0])
        if first_val <= 0:
            continue
        norm_vals = [float(v) / first_val for v in vals]
        total_ret = norm_vals[-1] - 1.0
        cagr = (norm_vals[-1] ** (_TRADING_DAYS_PER_YEAR / n_days) - 1.0) if n_days > 0 else None
        daily = [norm_vals[i] / norm_vals[i - 1] - 1.0 for i in range(1, len(norm_vals))]
        vol = None
        if len(daily) > 1:
            mean = sum(daily) / len(daily)
            var = sum((d - mean) ** 2 for d in daily) / (len(daily) - 1)
            vol = sqrt(var) * sqrt(_TRADING_DAYS_PER_YEAR)
        sharpe = cagr / vol if cagr is not None and vol and vol > 0 else None

        peak = norm_vals[0]
        max_dd = 0.0
        for v in norm_vals:
            peak = max(peak, v)
            max_dd = max(max_dd, 1.0 - v / peak)
        calmar = cagr / max_dd if cagr is not None and max_dd > 0 else None

        stats_dict[col] = {
            "total_return": total_ret,
            "cagr": cagr,
            "max_drawdown": -max_dd,
            "annual_volatility": vol,
            "sharpe": sharpe,
            "calmar": calmar,
        }
    return stats_dict


def compute_rolling_stats(wide_pl: pl.DataFrame, window_days: int = 252) -> pd.DataFrame:
    """计算滚动持有期分布指标。"""
    n_rows = len(wide_pl)
    cols = [c for c in wide_pl.columns if c != "trade_date"]
    benchmark = "中证全指" if "中证全指" in cols else (cols[0] if cols else "")

    records: dict[str, dict[str, list[float]]] = {
        c: {"returns": [], "excess": [], "max_dds": []} for c in cols
    }

    for i in range(window_days, n_rows):
        sub = wide_pl[i - window_days : i + 1]
        stats = compute_slice_metrics(sub, cols)
        bench_ret = float(stats.get(benchmark, {}).get("total_return") or 0.0)

        for c in cols:
            ret = float(stats.get(c, {}).get("total_return") or 0.0)
            mdd = float(stats.get(c, {}).get("max_drawdown") or 0.0)
            records[c]["returns"].append(ret)
            records[c]["excess"].append(ret - bench_ret)
            records[c]["max_dds"].append(mdd)

    summary: list[dict[str, Any]] = []
    for c in cols:
        rets = np.array(records[c]["returns"])
        excess = np.array(records[c]["excess"])
        mdds = np.array(records[c]["max_dds"])
        if len(rets) == 0:
            continue

        summary.append(
            {
                "标的/策略": c,
                "滚动窗口": f"{window_days} 交易日",
                "测试窗口总数": len(rets),
                "正收益胜率": float(np.mean(rets > 0)),
                "跑赢基准(全指)概率": float(np.mean(excess > 0)),
                "中位数收益率": float(np.median(rets)),
                "收益率 25% 分位": float(np.percentile(rets, 25)),
                "收益率 75% 分位": float(np.percentile(rets, 75)),
                "最差区间收益": float(np.min(rets)),
                "最佳区间收益": float(np.max(rets)),
                "平均最大回撤": float(np.mean(mdds)),
                "极端最深回撤": float(np.min(mdds)),
            }
        )
    return pd.DataFrame(summary)


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

    for symbol, label in _BENCHMARKS:
        close = catalog.load_bars(
            symbol=symbol,
            dataset="index_daily_bar",
            columns=["trade_date", "close"],
        )
        full_series[label] = nav_from_close(close, start_date=start_d, end_date=end_d)

    # 合并宽表
    wide_df: pl.DataFrame | None = None
    for name, nav_df in full_series.items():
        s = nav_df.rename({"nav": name})
        wide_df = s if wide_df is None else wide_df.join(s, on="trade_date", how="inner")

    if wide_df is None:
        raise RuntimeError("未能生成任何策略回测数据")

    wide_df = wide_df.sort("trade_date")
    wide_df.write_csv(output_dir / "stability_nav_wide.csv")
    all_cols = [c for c in wide_df.columns if c != "trade_date"]

    # 1. 6 大范式切片
    regime_rows: list[dict[str, Any]] = []
    for r_name, r_start, r_end, _r_desc in MACRO_REGIMES:
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
                    "区间累计收益": st.get("total_return"),
                    "年化收益(CAGR)": st.get("cagr"),
                    "区间最大回撤": st.get("max_drawdown"),
                    "年化波动率": st.get("annual_volatility"),
                    "夏普比率": st.get("sharpe"),
                }
            )

    regime_df = pd.DataFrame(regime_rows)
    regime_df.to_csv(output_dir / "regime_comparison.csv", index=False)

    # 2. 4 大危机压力测试
    stress_rows: list[dict[str, Any]] = []
    for s_name, s_start, s_end, s_desc in STRESS_TEST_PERIODS:
        sub_df = wide_df.filter((pl.col("trade_date") >= s_start) & (pl.col("trade_date") <= s_end))
        if sub_df.is_empty():
            continue
        stats = compute_slice_metrics(sub_df, all_cols)
        for col in all_cols:
            st = stats.get(col, {})
            stress_rows.append(
                {
                    "压力测试情景": s_name,
                    "危机区间": f"{s_start} ~ {s_end}",
                    "场景特征": s_desc,
                    "标的/策略": col,
                    "区间跌幅": st.get("total_return"),
                    "区间最深回撤": st.get("max_drawdown"),
                }
            )

    stress_df = pd.DataFrame(stress_rows)
    stress_df.to_csv(output_dir / "stress_test_comparison.csv", index=False)

    # 3. 滚动持有期分析
    r1 = compute_rolling_stats(wide_df, window_days=252)
    r3 = compute_rolling_stats(wide_df, window_days=756)
    rolling_df = pd.concat([r1, r3], ignore_index=True)
    rolling_df.to_csv(output_dir / "rolling_stability_stats.csv", index=False)

    # 4. 图表生成
    chart_file: Path | None = None
    if generate_charts:
        chart_file = render_stability_charts(wide_df, regime_df, stress_df, r3, output_dir)

    # 5. Markdown 报告渲染
    report_file = output_dir / "strategy_stability_report.md"
    render_audit_markdown(
        wide_df=wide_df,
        regime_df=regime_df,
        stress_df=stress_df,
        rolling_df=rolling_df,
        chart_file=chart_file,
        report_file=report_file,
    )

    logger.info("多策略稳定性审计完成，产物输出至: %s", output_dir)
    return StabilityAuditResult(
        wide_nav=wide_df,
        regime_df=regime_df,
        stress_df=stress_df,
        rolling_df=rolling_df,
        report_path=report_file,
        chart_path=chart_file,
    )


def assert_stability_guardrails(result: StabilityAuditResult) -> None:
    """策略稳定性退化回归断言（CI 门禁）。"""
    rolling = result.rolling_df
    # 1. 验证 V4 滚动 3 年跑赢全指胜率必须 >= 80%
    v4_r3 = rolling[
        (rolling["标的/策略"] == "macro_rotation_v4") & (rolling["滚动窗口"] == "756 交易日")
    ]
    if not v4_r3.empty:
        win_rate = float(v4_r3["跑赢基准(全指)概率"].iloc[0])
        if win_rate < 0.80:
            raise AssertionError(f"macro_rotation_v4 滚动 3Y 胜率退化: {win_rate:.2%} < 80%")

    # 2. 验证 V6 2024 微盘踩踏最大回撤必须 >= -10% (即跌幅不得超过 10%)
    stress = result.stress_df
    v6_2024 = stress[
        (stress["标的/策略"] == "macro_rotation_v6")
        & (stress["压力测试情景"] == "2024 微盘流动性踩踏")
    ]
    if not v6_2024.empty:
        max_dd = float(v6_2024["区间最深回撤"].iloc[0])
        if max_dd < -0.10:
            raise AssertionError(
                f"macro_rotation_v6 在 2024 微盘踩踏中回撤恶化: {max_dd:.2%} < -10%"
            )


__all__ = [
    "MACRO_REGIMES",
    "STRESS_TEST_PERIODS",
    "StabilityAuditResult",
    "assert_stability_guardrails",
    "compute_rolling_stats",
    "compute_slice_metrics",
    "run_full_stability_audit",
]
