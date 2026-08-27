"""因子组合回测报告渲染（markdown + json）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from stock_strategy.portfolio.backtester import BacktestResult


@dataclass(frozen=True, slots=True)
class BacktestMeta:
    """回测报告的来源与口径元信息。"""

    as_of_date: date
    factor_pool: tuple[str, ...]
    source_run: str


def _fmt(value: float | None, digits: int = 4) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def build_backtest_report(
    meta: BacktestMeta,
    result: BacktestResult,
    *,
    rebalance_days: int,
    top_n: int,
    window_days: int,
    price_col: str,
) -> tuple[str, dict[str, Any]]:
    """组装回测报告 markdown 与 json。"""
    nav = result.nav
    stats = result.stats
    bench_stats = result.benchmark_stats

    report_json = {
        "as_of_date": meta.as_of_date.isoformat(),
        "factor_pool": list(meta.factor_pool),
        "factor_source_run": meta.source_run,
        "rebalance_days": rebalance_days,
        "top_n": top_n,
        "window_days": window_days,
        "price_col": price_col,
        "data_note": "净值基于未复权收盘价，close 成交、次日生效；"
        "未建模交易成本/T+1/涨跌停；样本内回测与观察池幸存者偏差，仅供研究参考。",
        "stats": stats,
        "benchmark_stats": bench_stats,
        "nav": [
            {
                "trade_date": str(value["trade_date"]),
                "nav": float(value["nav"]),
                "benchmark_nav": float(value["benchmark_nav"]),
            }
            for value in nav.join(
                result.benchmark_nav.rename({"nav": "benchmark_nav"}),
                on="trade_date",
                how="left",
            ).iter_rows(named=True)
        ],
    }

    lines: list[str] = [
        "# 因子组合回测报告",
        "",
        f"- 基准日：{meta.as_of_date.isoformat()}",
        f"- 因子池（{len(meta.factor_pool)} 个）：{' / '.join(meta.factor_pool)}",
        f"- 因子来源：{meta.source_run}",
        f"- 调仓周期 {rebalance_days} 交易日；top-{top_n} 等权多头；现金兜底",
        f"- 价格基准：`{price_col}`（未复权口径；close 成交次日生效）",
        "- 口径：未建模交易成本 / T+1 / 涨跌停；样本内回测；观察池幸存者偏差，仅供研究参考",
        "",
        "## 收益与风险",
        "",
        "| 指标 | 组合 | 基准（观察池等权） |",
        "| --- | --- | --- |",
        f"| 交易日数 | {stats.get('n_trading_days')} | {bench_stats.get('n_trading_days')} |",
        f"| 总收益 | {_fmt(stats.get('total_return'))} | {_fmt(bench_stats.get('total_return'))} |",
        f"| 年化收益 | {_fmt(stats.get('annual_return'))} | {_fmt(bench_stats.get('annual_return'))} |",
        "| 年化波动 | {} | {} |".format(
            _fmt(stats.get("annual_volatility")), _fmt(bench_stats.get("annual_volatility"))
        ),
        f"| Sharpe | {_fmt(stats.get('sharpe'))} | {_fmt(bench_stats.get('sharpe'))} |",
        "| 最大回撤 | {} | {} |".format(
            _fmt(stats.get("max_drawdown")), _fmt(bench_stats.get("max_drawdown"))
        ),
        f"| Calmar | {_fmt(stats.get('calmar'))} | {_fmt(bench_stats.get('calmar'))} |",
        f"| 调仓期胜率 | {_fmt(stats.get('period_win_rate'))} | - |",
        "",
        "## 口径与限制说明",
        "",
        "- 调仓日收盘按当日组合分数选取 top-N 等权建仓，持仓收益自下一交易日按新权重计算；",
        "- 持仓标的价格缺失（停牌）时该标的当日收益按 0 计；现金部分收益为 0；",
        "- 前向收益与净值基于未复权收盘价，除权日可能失真；建议复权价落地后重新回测；",
        "- 准入判定与回测窗口未做样本外分离，统计结论偏乐观，仅作研究参考；",
        "- 未建模交易成本、滑点、T+1 与涨跌停约束，高换手策略的实际表现需打折评估。",
    ]
    return "\n".join(lines), report_json


__all__ = ["BacktestMeta", "build_backtest_report"]
