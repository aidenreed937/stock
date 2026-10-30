"""加速度 × 双轨指数择时门控实验（恐慌抄底门 / 狂热减仓门）。

背景：用户提出两个直觉假设——
A. 恐慌区（panic_index 高分位）应避免在指数「加速度下跌」时抄底；
B. 狂热区（overheat_index 高分位）应在「加速度放缓」时减仓。
先导胜率探针显示 A 方向被否定、B 显示危险在「加速段」而非「放缓段」（镜像假设）。

本脚本把假设形式化为 000985.CSI 择时门控规则做正式回测：
- G1: 恐慌≥T 且 20D 加速度<0 → 空仓（假设 A）
- G2: 狂热≥T 且 20D 加速度>0 → 空仓（镜像假设：加速段减仓）
- G3: 狂热≥T 且 20D 加速度≤0 → 空仓（原始假设 B：放缓段减仓）
并给出 6 大宏观范式分段与分年度超额（跨范式稳定性检查）。

评估口径（与 stock_cli/macro_strategy 及 proto 脚本对齐）：
- 严格 T+1：交易日 t 收盘生成信号，t+1 日生效；
- 摩擦 = 佣金 0.0001 + 滑点 0.0005（config/strategy/macro_risk.yaml 口径），每次换仓计一次；
- 空仓 = 现金 0 收益，不做固收腿（披露口径）；
- 指标：CAGR / 年化波动 / 夏普（无风险 1.5%）/ 最大回撤 / 暴露时间 / 换仓次数 / 相对 B&H 超额。

用法:
    uv run python scripts/accel_regime_gate_experiment.py
    uv run python scripts/accel_regime_gate_experiment.py --accel-threshold 0.005
"""

from __future__ import annotations

from datetime import date
from math import sqrt
from pathlib import Path

import polars as pl

BENCH = "000985.CSI"
RF_RATE = 0.015  # 无风险 1.5%/年（与 proto 脚本同口径）
FRICTION = 0.0001 + 0.0005  # 万1佣金 + 0.05% 滑点（单边）

RISK_FACTORS = Path("data/analytics/macro_risk/latest/risk_factors.parquet")
INDEX_BARS = Path("data/curated/tushare/market=CN/index_daily_bar/data.parquet")

# 6 大宏观范式窗口（与 macro_slow_top_divergence_proto.py 同口径）
REGIMES: list[tuple[str, str, str | None]] = [
    ("范式一：杠杆牛熊", "2015-01-05", "2015-12-31"),
    ("范式二：供给侧蓝筹", "2016-01-04", "2017-12-29"),
    ("范式三：去杠杆慢熊", "2018-01-02", "2018-12-28"),
    ("范式四：公募抱团牛", "2019-01-02", "2021-02-18"),
    ("范式五：存量红利防守", "2021-02-19", "2024-01-31"),
    ("范式六：政策新质牛", "2024-02-01", None),
]


def _load_panel() -> pl.DataFrame:
    idx = (
        pl.read_parquet(INDEX_BARS)
        .filter(pl.col("symbol") == BENCH)
        .select(["trade_date", "close"])
        .sort("trade_date")
    )
    df = idx.with_columns(
        (pl.col("close") / pl.col("close").shift(20) - 1.0).alias("r20"),
        (pl.col("close") / pl.col("close").shift(1) - 1.0).alias("ret"),
    ).with_columns(
        (pl.col("r20") - pl.col("r20").shift(20)).alias("a20"),
    )
    rf = pl.read_parquet(RISK_FACTORS).select(["trade_date", "overheat_index", "panic_index"])
    return (
        df.join(rf, on="trade_date", how="inner")
        .drop_nulls(subset=["a20", "ret"])
        .sort("trade_date")
    )


def _run_rule(df: pl.DataFrame, regime_col: str, threshold: float, cond: str) -> pl.DataFrame:
    """规则：regime >= threshold 且 a20 满足 cond 时下一日空仓。"""
    accel = pl.col("a20")
    if cond == "<":
        hit = accel < 0.0
    elif cond == "<=":
        hit = accel <= 0.0
    else:
        hit = accel > 0.0
    signal = (pl.col(regime_col) >= threshold) & hit
    return df.with_columns(pl.when(signal).then(0.0).otherwise(1.0).alias("pos_raw")).with_columns(
        pl.col("pos_raw").shift(1).fill_null(1.0).alias("pos")
    )


def _attach_strat_ret(df: pl.DataFrame) -> pl.DataFrame:
    """策略日收益：pos × 基准日收益 − 换仓摩擦（换仓发生在 pos 变化当日）。"""
    return df.with_columns(
        (
            pl.col("pos") * pl.col("ret") - FRICTION * pl.col("pos").diff().abs().fill_null(0.0)
        ).alias("strat_ret")
    )


def _backtest(df: pl.DataFrame) -> dict:
    n = df.height
    strat = df["strat_ret"].to_list()
    nav = 1.0
    navs = []
    for r in strat:
        nav *= 1.0 + r
        navs.append(nav)
    navs = pl.Series(navs, dtype=pl.Float64)
    mean_d = sum(strat) / n
    vol_d = float(navs.diff().drop_nulls().std()) if n > 1 else 0.0
    vol = vol_d * sqrt(252) if n > 1 else 0.0
    sharpe = (mean_d * 252.0 - RF_RATE) / vol if vol > 0 else 0.0
    mdd = float(((navs / navs.cum_max()) - 1.0).min())
    return {
        "total": navs[-1],
        "cagr": navs[-1] ** (252.0 / n) - 1.0 if n > 0 else 0.0,
        "vol": vol,
        "sharpe": sharpe,
        "mdd": mdd,
        "exposure": sum(1.0 for p in df["pos"].to_list() if p > 0) / n,
        "switches": int((df["pos"].diff().abs().fill_null(0.0) > 0).sum()),
    }


def _segment_ret(df: pl.DataFrame, lo: date, hi: date | None) -> float | None:
    cond = pl.col("trade_date") >= lo
    if hi is not None:
        cond = cond & (pl.col("trade_date") <= hi)
    s = df.filter(cond)
    if s.height < 20:
        return None
    nav = 1.0
    for r in s["strat_ret"].to_list():
        nav *= 1.0 + r
    return nav - 1.0


def main() -> None:
    df = _load_panel()
    bench = _attach_strat_ret(df.with_columns(pl.lit(1.0).alias("pos")))
    rules = [
        ("G1 恐慌加速门(假设A)", "panic_index", 60.0, "<"),
        ("G1 恐慌加速门(假设A)", "panic_index", 70.0, "<"),
        ("G2 狂热加速门(镜像假设)", "overheat_index", 60.0, ">"),
        ("G2 狂热加速门(镜像假设)", "overheat_index", 65.0, ">"),
        ("G3 狂热放缓门(原始假设B)", "overheat_index", 60.0, "<="),
        ("G3 狂热放缓门(原始假设B)", "overheat_index", 65.0, "<="),
    ]
    results: list[tuple[str, dict, pl.DataFrame]] = [
        ("000985 买入持有基准", _backtest(bench), bench)
    ]
    for label, col, thr, cond in rules:
        rd = _attach_strat_ret(_run_rule(df, col, thr, cond))
        results.append((f"{label} ≥{thr:.0f}", _backtest(rd), rd))

    lines = [
        "# 加速度 × 双轨指数择时门控实验",
        "",
        "> 严格 T+1；摩擦=佣金 0.01% + 滑点 0.05%（单边/次换仓）；空仓=现金 0 收益；"
        "夏普无风险 1.5%；基准=中证全指 000985.CSI；加速度=20D 动量差分（a20，符号门）。",
        "",
        "## 全周期表现",
        "| 规则 | 期末净值 | CAGR | 年化波动 | 夏普 | 最大回撤 | 暴露时间 | 换仓次数 |",
        "| :-- | --: | --: | --: | --: | --: | --: | --: |",
    ]
    for label, m, _rd in results:
        lines.append(
            f"| {label} | {m['total']:.3f} | {m['cagr'] * 100:+.2f}% | {m['vol'] * 100:.1f}% | "
            f"{m['sharpe']:.2f} | {m['mdd'] * 100:.1f}% | {m['exposure'] * 100:.0f}% | {m['switches']} |"
        )

    pick = {
        "G1-70": next(r for r in results if "G1" in r[0] and "70" in r[0]),
        "G2-65": next(r for r in results if "G2" in r[0] and "65" in r[0]),
        "G3-65": next(r for r in results if "G3" in r[0] and "65" in r[0]),
    }
    lines.append("\n## 6 大宏观范式分段（范式内收益）")
    lines.append("| 范式 | 基准 | G1-70 | G2-65 | G3-65 |")
    lines.append("| :-- | --: | --: | --: | --: |")
    for name, start, end in REGIMES:
        lo, hi = date.fromisoformat(start), date.fromisoformat(end) if end else None
        cells = [name]
        for _, _m, rd in [results[0], pick["G1-70"], pick["G2-65"], pick["G3-65"]]:
            v = _segment_ret(rd, lo, hi)
            cells.append("n/a" if v is None else f"{v * 100:+.1f}%")
        lines.append("| " + " | ".join(cells) + " |")

    lines.append("\n## 分年度超额（策略 − 基准，pp）")
    years = sorted({int(str(d)[:4]) for d in df["trade_date"].to_list()})
    lines.append("| 年份 | G1-70 | G2-65 | G3-65 |")
    lines.append("| :-- | --: | --: | --: |")

    def year_excess(rd: pl.DataFrame, yr: int) -> str:
        seg_rd = _segment_ret(rd, date(yr, 1, 1), date(yr, 12, 31))
        seg_b = _segment_ret(results[0][2], date(yr, 1, 1), date(yr, 12, 31))
        if seg_rd is None or seg_b is None:
            return "n/a"
        return f"{(seg_rd - seg_b) * 100:+.1f}"

    for yr in years:
        cells = [str(yr)] + [year_excess(pick[key][2], yr) for key in ("G1-70", "G2-65", "G3-65")]
        lines.append("| " + " | ".join(cells) + " |")

    lines.append(
        "\n> 口径: G1=恐慌≥T 且 20D 加速度<0 空仓（假设A：避免加速下跌时抄底）；"
        "G2=狂热≥T 且 a20>0 空仓（镜像假设：加速段减仓）；G3=狂热≥T 且 a20≤0 空仓（原始假设B：放缓段减仓）。"
    )
    out = "\n".join(lines)
    out_path = Path("data/analytics/macro_strategy/robustness/accel_regime_gate_experiment.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(out, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
