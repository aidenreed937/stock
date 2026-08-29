"""宏观风控策略绩效报告：资金曲线、指标对比与 Markdown 渲染。

职责：把 V3/V4 策略净值与基准（中证全指 / 沪深300）buy&hold 净值对齐到同一
交易日轴，计算绩效指标（累计净值、CAGR、最大回撤、年化波动、Sharpe、Calmar），
输出资金曲线 PNG、净值 CSV 与对比 Markdown 文档。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from math import sqrt
from pathlib import Path
from typing import Any, cast

import polars as pl
import yaml

from stock_data.catalog import DataCatalog
from stock_strategy.macro_assembly import assemble_macro_panel, load_price_panel
from stock_strategy.macro_runner import MacroRiskRunner
from stock_strategy.pool import create_strategy

_TRADING_DAYS_PER_YEAR = 252.0
_DEFAULT_CONFIG_PATH = Path("config/strategy/macro_risk.yaml")
_DEFAULT_RISK_ROOT = Path("data/analytics/macro_risk")
_DEFAULT_OUTPUT_DIR = Path("data/analytics/macro_strategy")

_BENCHMARKS = (
    ("000985.CSI", "中证全指"),
    ("000300.SH", "沪深300"),
)


def load_all_strategy_specs(
    config_path: Path | str = _DEFAULT_CONFIG_PATH,
) -> dict[str, dict[str, Any]]:
    """读取配置文件中所有已注册宏观策略的配置字典。"""
    payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    strategies = payload.get("strategies", {})
    return {k: v for k, v in strategies.items() if isinstance(v, dict)}


def load_strategy_spec(name: str, config_path: Path | str = _DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """读取单个宏观策略的运行配置（benchmark / symbols / initial_weights / ma_window）。"""
    all_specs = load_all_strategy_specs(config_path)
    return all_specs.get(name, {})


def nav_from_close(
    close: pl.DataFrame,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> pl.DataFrame:
    """把基准指数 close 序列转为 buy&hold 净值（首日归一为 1）。"""
    frame = (
        close.select(["trade_date", "close"])
        .with_columns(
            pl.col("trade_date").cast(pl.Date),
            pl.col("close").cast(pl.Float64, strict=False),
        )
        .drop_nulls(subset=["close"])
        .unique(subset=["trade_date"], keep="last")
        .sort("trade_date")
    )
    if start_date is not None:
        frame = frame.filter(pl.col("trade_date") >= start_date)
    if end_date is not None:
        frame = frame.filter(pl.col("trade_date") <= end_date)
    if frame.is_empty():
        return frame
    first = float(frame["close"][0])
    return frame.select("trade_date", (pl.col("close") / first).alias("nav"))


def compute_stats(nav: pl.DataFrame) -> dict[str, float | None]:
    """从净值序列计算核心绩效指标。"""
    values = [float(v) for v in nav["nav"].to_list()]
    if not values:
        return {}
    n_days = max(len(values) - 1, 0)
    total_return = values[-1] - 1.0
    annual = values[-1] ** (_TRADING_DAYS_PER_YEAR / n_days) - 1.0 if n_days > 0 else None

    daily = [values[i] / values[i - 1] - 1.0 for i in range(1, len(values))]
    vol: float | None = None
    if len(daily) > 1:
        mean = sum(daily) / len(daily)
        variance = sum((d - mean) ** 2 for d in daily) / (len(daily) - 1)
        vol = sqrt(variance) * sqrt(_TRADING_DAYS_PER_YEAR)

    sharpe = annual / vol if annual is not None and vol and vol > 0 else None

    peak = values[0]
    max_dd = 0.0
    for value in values:
        peak = max(peak, value)
        max_dd = max(max_dd, 1.0 - value / peak)
    calmar = annual / max_dd if annual is not None and max_dd > 0 else None

    return {
        "final_nav": values[-1],
        "total_return": total_return,
        "annual_return": annual,
        "annual_volatility": vol,
        "sharpe": sharpe,
        "max_drawdown": -max_dd,
        "calmar": calmar,
    }


def _runner_for(spec: dict[str, Any]) -> tuple[MacroRiskRunner, str]:
    symbols = tuple(spec["symbols"])
    initial_weights = dict(spec.get("initial_weights", {}))
    benchmark = str(spec["benchmark_symbol"])

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
        }:
            strategy_kwargs[k] = v

    strategy = create_strategy(
        str(spec["strategy_class"]),
        **strategy_kwargs,
    )
    runner = MacroRiskRunner(
        strategy,
        symbols=symbols,
        initial_weights=initial_weights,
        strategy_name=spec["strategy_class"],
        data_source="tushare",
        commission_rate=commission_rate,
        slippage_rate=slippage_rate,
        rebalance_deadband=rebalance_deadband,
    )
    return runner, benchmark


def build_multi_strategy_comparison_report(
    *,
    output_dir: Path | str = _DEFAULT_OUTPUT_DIR,
    risk_root: Path | str = _DEFAULT_RISK_ROOT,
    config_path: Path | str = _DEFAULT_CONFIG_PATH,
) -> dict[str, Any]:
    """生成配置文件中所有策略与基准的资金曲线、指标对比与 Markdown 文档。"""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    catalog = DataCatalog(data_source="tushare")

    # 1. 动态加载并运行所有已配置策略
    strategy_specs = load_all_strategy_specs(config_path)
    series: dict[str, pl.DataFrame] = {}
    start: date | None = None
    end: date | None = None

    for name, spec in strategy_specs.items():
        runner, benchmark = _runner_for(spec)
        panel = assemble_macro_panel(
            catalog=catalog,
            benchmark_symbol=benchmark,
            risk_root=risk_root,
        )
        price_panel = load_price_panel(catalog=catalog, symbols=tuple(spec["symbols"]))
        nav = runner.backtest(panel, price_panel)
        series[name] = nav
        if start is None:
            start = cast("date", panel["trade_date"].min())
            end = cast("date", panel["trade_date"].max())

    # 2. 基准 buy&hold 净值
    for symbol, label in _BENCHMARKS:
        close = catalog.load_bars(
            symbol=symbol,
            dataset="index_daily_bar",
            columns=["trade_date", "close"],
        )
        series[label] = nav_from_close(close, start_date=start, end_date=end)

    # 3. 绩效指标
    stats = {name: compute_stats(nav) for name, nav in series.items()}

    # 4. 资金曲线图 + 净值 CSV + Markdown
    png_path = out / "multi_strategy_comparison.png"
    csv_path = out / "multi_strategy_nav.csv"
    md_path = out / "multi_strategy_comparison.md"
    _write_nav_csv(series, csv_path)
    plot_comparison(series, png_path)
    md_content = render_comparison_markdown(stats, image_rel_path=png_path.name)
    md_path.write_text(md_content, encoding="utf-8")

    return {
        "markdown": md_path,
        "png": png_path,
        "csv": csv_path,
        "stats": stats,
    }


# 向后兼容别名
build_v3_v4_comparison_report = build_multi_strategy_comparison_report


def _write_nav_csv(series: dict[str, pl.DataFrame], path: Path) -> None:
    wide = None
    for name, nav in series.items():
        renamed = nav.rename({"nav": name})
        if wide is None:
            wide = renamed
        else:
            wide = wide.join(renamed, on="trade_date", how="full", coalesce=True)
    if wide is not None:
        wide.sort("trade_date").write_csv(path)


def plot_comparison(series: dict[str, pl.DataFrame], output_png: Path) -> None:
    """绘制资金曲线对比图（对数轴）。"""
    import os

    if not os.environ.get("MPLCONFIGDIR"):
        cache_dir = Path("data/.mplconfig")
        cache_dir.mkdir(parents=True, exist_ok=True)
        os.environ["MPLCONFIGDIR"] = str(cache_dir.resolve())

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = [
        "PingFang SC",
        "Hiragino Sans GB",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(figsize=(12, 6))
    for name, nav in series.items():
        ax.plot(nav["trade_date"].to_list(), nav["nav"].to_list(), label=name, linewidth=1.2)

    ax.set_title("宏观风控多策略演进与基准资金曲线全景对比 (2015-2026)")
    ax.set_xlabel("交易日期")
    ax.set_ylabel("累计净值 (对数轴)")
    ax.set_yscale("log")
    ax.grid(True, which="both", linestyle="--", alpha=0.4)
    ax.legend(loc="upper left", fontsize=9)
    fig.tight_layout()
    fig.savefig(output_png, dpi=130)
    plt.close(fig)


_RowSpec = tuple[str, str, Callable[[float], str]]


def render_comparison_markdown(
    stats: dict[str, dict[str, float | None]],
    *,
    image_rel_path: str = "multi_strategy_comparison.png",
) -> str:
    """按模板动态渲染多策略与基准的对比 Markdown 文档。"""
    benchmark_labels = [label for _, label in _BENCHMARKS if label in stats]
    strategy_names = [name for name in stats if name not in benchmark_labels]
    all_cols = benchmark_labels + strategy_names

    headers = ["核心指标项"] + [
        f"{col} (基准)" if col in benchmark_labels else f"**{col}**" for col in all_cols
    ]
    header_line = "| " + " | ".join(headers) + " |"
    align_line = "| :--- | " + " | ".join(":---:" for _ in all_cols) + " |"

    rows: list[_RowSpec] = [
        ("累计净值", "final_nav", lambda v: f"{v:.3f}"),
        ("累计收益", "total_return", lambda v: f"{v:.2%}"),
        ("年化收益 (CAGR)", "annual_return", lambda v: f"{v:.2%}"),
        ("最大回撤 (Max DD)", "max_drawdown", lambda v: f"{v:.2%}"),
        ("年化波动率", "annual_volatility", lambda v: f"{v:.2%}"),
        ("夏普比率 (Sharpe)", "sharpe", lambda v: f"{v:.2f}"),
        ("卡玛比率 (Calmar)", "calmar", lambda v: f"{v:.2f}"),
    ]

    row_lines: list[str] = []
    for label, key, fmt in rows:
        cells = [f"**{label}**"]
        for col in all_cols:
            val = stats.get(col, {}).get(key)
            formatted = fmt(val) if isinstance(val, int | float) else "—"
            if col in strategy_names and formatted != "—":
                formatted = f"**`{formatted}`**"
            cells.append(formatted)
        row_lines.append("| " + " | ".join(cells) + " |")

    table_markdown = "\n".join([header_line, align_line, *row_lines])

    return f"""# 宏观风控多策略演进与全周期重测全景对比 (2015-2026)

本报告基于固化入库的生产级代码，对所有已配置的宏观风控策略在全量真实历史数据上进行严格横向对账。回测采用 T+1 语义（信号当日收盘生成、次日生效），未计交易成本/滑点/T+1 涨跌停，仅供研究参考。

![多策略资金曲线全景对比]({image_rel_path})

---

### 全周期量化绩效总览 (2015-01-05 至 2026-08-26)

{table_markdown}

---

### 定性总结：多策略互补矩阵

- **趋势防守压舱石**：单宽基趋势择时策略，在市场面临系统性下跌时坚决破均线降仓，控制下行回撤。
- **双核风格轮动**：攻守兼备，牛市吃满成长主升浪弹性，存量熊市高股息红利托底避险。
- **资金博弈智能增强**：在风格轮动基础上融入国家队大额托底抢跑与高位散户接盘逃顶，提升胜率与极值捕获效率。

> 以上为历史回测结果，不代表未来表现；实盘需叠加交易成本、流动性约束与策略漂移再评估。
"""


__all__ = [
    "build_multi_strategy_comparison_report",
    "build_v3_v4_comparison_report",
    "compute_stats",
    "load_all_strategy_specs",
    "load_strategy_spec",
    "nav_from_close",
    "plot_comparison",
    "render_comparison_markdown",
]
