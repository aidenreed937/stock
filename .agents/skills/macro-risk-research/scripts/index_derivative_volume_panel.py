"""指数速度/加速度/量价多指数对比观察面板（一阶导·二阶导·量价）。

口径说明（Ground Truth First）：
- 数据完全来自本地 Curated 指数日行情（index_daily_bar，tushare 口径），不臆造任何点位；
- 一阶导（速度）= 各窗口动量：close[t] / close[t-N] - 1，N = 5/20/60；
- 二阶导（加速度）= 动量自身的变化：当前 N 日动量 − N 日前的 N 日动量（pp）；
- 年线 = 250 日均线，年线位置 = 最新收盘相对 250 日均线的偏离 %；
- 量 = 指数日成交额（tushare index_daily 口径为千元）的历史分位与 20 日均额；
- 量价 = 近 5 日涨跌 vs 近5日均额/近20日均额，按 放量/缩量 × 涨/跌 四象限定性；
- 动量/成交额历史分位 = 该序列在全样本（数据起点起）中的位置（0-100）；
- 各指数成交额为各自成分股口径，跨指数绝对额不可直接类比，看分位与比值。

定位：独立价格动力学观察面板，非 v5 交易信号，不进 overheat/panic 双轨指数。
默认对比观察交易的三个指数：中证全指 (000985.CSI) / 创业板指 (399006.SZ) / 中证红利 (000922.CSI)。

用法：
    uv run python .agents/skills/macro-risk-research/scripts/index_derivative_volume_panel.py
    uv run python .agents/skills/macro-risk-research/scripts/index_derivative_volume_panel.py --symbols 000985.CSI,399006.SZ
    uv run python .agents/skills/macro-risk-research/scripts/index_derivative_volume_panel.py --symbols 399006.SZ --as-of 2026-06-30
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import polars as pl

DEFAULT_SYMBOLS = ("000985.CSI", "399006.SZ", "000922.CSI")  # 中证全指 / 创业板指 / 中证红利
INDEX_NAMES = {"000985.CSI": "中证全指", "399006.SZ": "创业板指", "000922.CSI": "中证红利"}
INDEX_ORDER = ("000985.CSI", "399006.SZ", "000922.CSI")
# 各窗口动量最长回看至少需覆盖 60 交易日的两倍，用于产出二阶导
_MIN_ROWS = 130
_WINDOWS = (5, 20, 60)


def _discover_index_daily() -> Path:
    """定位本地 Curated 指数日行情 parquet (兼容 tushare/理杏仁两处)。"""
    candidates = [
        Path("data/curated/tushare/market=CN/index_daily_bar/data.parquet"),
        Path("data/curated/lixinger/market=CN/index_daily_bar/data.parquet"),
    ]
    for p in candidates:
        if p.is_file():
            return p
    # 兜底: 递归查找
    for root in ("data/curated/tushare", "data/curated/lixinger"):
        hits = sorted(Path(root).rglob("index_daily_bar/data.parquet"))
        if hits:
            return hits[0]
    raise FileNotFoundError("未找到本地 Curated 指数日行情 (index_daily_bar)")


def _load(symbols: list[str], close_until: date) -> pl.DataFrame:
    src = _discover_index_daily()
    df = (
        pl.read_parquet(src)
        .with_columns(pl.col("trade_date").cast(pl.Date))
        .filter((pl.col("trade_date") <= close_until) & (pl.col("symbol").is_in(symbols)))
        .select(["symbol", "trade_date", "close", "volume", "amount"])
        .sort(["symbol", "trade_date"])
    )
    return df


def _pct_rank(series: pl.Series, cur: float) -> float | None:
    vals = series.drop_nulls().to_list()
    if not vals:
        return None
    return sum(1 for x in vals if x <= cur) / len(vals) * 100.0


def _accel_word(mom: float, acc: float) -> str:
    if mom > 0 and acc > 0.005:
        return "上行加速"
    if mom > 0 and acc < -0.005:
        return "上行减速"
    if mom < 0 and acc > 0.005:
        return "下行减速(跌势放缓)"
    if mom < 0 and acc < -0.005:
        return "下行加速"
    return "基本平稳"


def _pq_label(r5: float, vr: float) -> str:
    if r5 > 0 and vr >= 1.05:
        return "放量上涨(量价配合)"
    if r5 > 0 and vr < 0.95:
        return "缩量上涨(量价背离)"
    if r5 < 0 and vr >= 1.05:
        return "放量下跌(量价配合向下)"
    if r5 < 0 and vr < 0.95:
        return "缩量下跌(量价背离)"
    return "量能均衡"


def _metric(sym: str, df: pl.DataFrame) -> dict[str, float]:
    n = df.height
    df = df.with_columns(
        (pl.col("close") / pl.col("close").shift(5) - 1.0).alias("r5"),
        (pl.col("close") / pl.col("close").shift(20) - 1.0).alias("r20"),
        (pl.col("close") / pl.col("close").shift(60) - 1.0).alias("r60"),
        (pl.col("amount").rank("ordinal") / n * 100.0).alias("amt_pct"),
    )
    df = df.with_columns(
        (pl.col("r5") - pl.col("r5").shift(5)).alias("a5"),
        (pl.col("r20") - pl.col("r20").shift(20)).alias("a20"),
    )
    last = df.tail(1)
    closes = df["close"].to_list()
    ma250 = sum(closes[-250:]) / min(250, len(closes))
    amt_ma20 = float(df.tail(20)["amount"].mean())
    vol_ratio = float(df.tail(5)["amount"].mean()) / amt_ma20 if amt_ma20 > 0 else float("nan")
    m: dict[str, float] = {"close": float(last["close"][0])}
    for w in _WINDOWS:
        m[f"r{w}"] = float(last[f"r{w}"][0])
        m[f"p{w}"] = _pct_rank(df[f"r{w}"], m[f"r{w}"]) or float("nan")
    m["a5"] = float(last["a5"][0]) * 100.0
    m["a20"] = float(last["a20"][0]) * 100.0
    m["amt_pct"] = float(last["amt_pct"][0])
    m["amt_ma20_yi"] = amt_ma20 / 1e5  # 千元 -> 亿元
    m["amt_ratio"] = float(last["amount"][0]) / amt_ma20 if amt_ma20 > 0 else float("nan")
    m["vol_ratio"] = vol_ratio
    m["ret5"] = m["r5"] * 100.0
    m["ma250_rel"] = (m["close"] / ma250 - 1.0) * 100.0
    return m


def _fmt_signed_pct(x: float, digits: int = 2) -> str:
    return f"{x:+.{digits}f}%"


def _fmt_pp(x: float) -> str:
    return f"{x:+.2f}pp"


def _fmt_int(x: float) -> str:
    return f"{x:.0f}"


def _nameof(sym: str) -> str:
    return f"{INDEX_NAMES.get(sym, sym)} {sym}"


def run(symbols: list[str], as_of: date) -> None:
    df_all = _load(symbols, as_of)
    metrics: dict[str, dict[str, float]] = {}
    last_date = None
    for sym in symbols:
        sub = df_all.filter(pl.col("symbol") == sym).sort("trade_date")
        if sub.height < _MIN_ROWS:
            print(f"[{as_of}] {sym} 数据不足 ({sub.height} 行，需 >= {_MIN_ROWS})，已跳过")
            continue
        metrics[sym] = _metric(sym, sub)
        last_date = last_date or str(sub["trade_date"][-1])
    if not metrics:
        return
    ordered = [s for s in INDEX_ORDER if s in metrics] + [
        s for s in metrics if s not in INDEX_ORDER
    ]
    as_date = last_date or str(as_of)

    print(f"# 指数速度/加速度/量价对比面板 (截至 {as_date})")
    print(f"\n## 数据日期: {as_date}  (as_of={as_of})")

    print("\n### 一阶导（速度，各窗口动量 + 历史分位 + 年线位置）")
    print("| 指数 | 5D | 5D分位 | 20D | 20D分位 | 60D | 60D分位 | 年线位置 |")
    print("| :-- | --: | --: | --: | --: | --: | --: | --: |")
    for s in ordered:
        m = metrics[s]
        print(
            f"| {_nameof(s)} | {_fmt_signed_pct(m['r5'] * 100)} | {_fmt_int(m['p5'])} | "
            f"{_fmt_signed_pct(m['r20'] * 100)} | {_fmt_int(m['p20'])} | "
            f"{_fmt_signed_pct(m['r60'] * 100)} | {_fmt_int(m['p60'])} | {_fmt_signed_pct(m['ma250_rel'])} |"
        )

    print("\n### 二阶导（加速度，动量自身变化 pp）")
    print("| 指数 | 5D加速度 | 5D定性 | 20D加速度 | 20D定性 |")
    print("| :-- | --: | :-- | --: | :-- |")
    for s in ordered:
        m = metrics[s]
        print(
            f"| {_nameof(s)} | {_fmt_pp(m['a5'])} | {_accel_word(m['r5'], m['a5'] / 100)} | "
            f"{_fmt_pp(m['a20'])} | {_accel_word(m['r20'], m['a20'] / 100)} |"
        )

    print("\n### 量能")
    print("| 指数 | 成交额史分位 | 20日均额(亿元) | 当日/20日均值 |")
    print("| :-- | --: | --: | --: |")
    for s in ordered:
        m = metrics[s]
        print(
            f"| {_nameof(s)} | {_fmt_int(m['amt_pct'])} | {m['amt_ma20_yi']:.0f} | {m['amt_ratio']:.2f} |"
        )

    print("\n### 量价（近5日）")
    print("| 指数 | 近5日涨跌 | 5日均额/20日均额 | 量价定性 |")
    print("| :-- | --: | --: | :-- |")
    for s in ordered:
        m = metrics[s]
        print(
            f"| {_nameof(s)} | {_fmt_signed_pct(m['ret5'])} | {m['vol_ratio']:.2f} | "
            f"{_pq_label(m['r5'], m['vol_ratio'])} |"
        )

    print("\n### 解读")
    if len(metrics) == 1:
        s = ordered[0]
        m = metrics[s]
        trend = (
            "中期趋势向上"
            if m["r20"] > 0 and m["r60"] > 0
            else "中期趋势向下"
            if m["r20"] < 0 and m["r60"] < 0
            else "长短窗口方向背离"
        )
        print(
            f"- {_nameof(s)} 20D {_fmt_signed_pct(m['r20'] * 100)} / 60D {_fmt_signed_pct(m['r60'] * 100)}：{trend}"
        )
        print(
            f"- 加速度方向: 5D **{_accel_word(m['r5'], m['a5'] / 100)}** / "
            f"20D **{_accel_word(m['r20'], m['a20'] / 100)}**"
        )
        print(
            f"- 量价（近5日）: **{_pq_label(m['r5'], m['vol_ratio'])}**"
            f"（近5日 {_fmt_signed_pct(m['ret5'])}，量比 {m['vol_ratio']:.2f}）"
        )
    else:
        best20 = max(ordered, key=lambda s: metrics[s]["r20"])
        worst20 = min(ordered, key=lambda s: metrics[s]["r20"])
        best60 = max(ordered, key=lambda s: metrics[s]["r60"])
        worst60 = min(ordered, key=lambda s: metrics[s]["r60"])
        print(
            f"- 相对动量: 20D 最强 **{_nameof(best20)}** ({_fmt_signed_pct(metrics[best20]['r20'] * 100)})"
            f" / 最弱 **{_nameof(worst20)}** ({_fmt_signed_pct(metrics[worst20]['r20'] * 100)})；"
            f"60D 最强 **{_nameof(best60)}** ({_fmt_signed_pct(metrics[best60]['r60'] * 100)})"
            f" / 最弱 **{_nameof(worst60)}** ({_fmt_signed_pct(metrics[worst60]['r60'] * 100)})"
        )
        up, down = [], []
        for s in ordered:
            if metrics[s]["a20"] > 0.5:
                up.append(_nameof(s))
            elif metrics[s]["a20"] < -0.5:
                down.append(_nameof(s))
        if up:
            print(f"- 20D 动量上修（跌势放缓或转强）: {'、'.join(up)}")
        if down:
            print(f"- 20D 动量衰减（跌势加深或涨势收窄）: {'、'.join(down)}")
        div = [
            _nameof(s)
            for s in ordered
            if "背离" in _pq_label(metrics[s]["r5"], metrics[s]["vol_ratio"])
        ]
        if div:
            print(f"- 近5日量价背离: {'、'.join(div)}（缩量涨/跌，方向性动能存疑）")
        up_ma = [_nameof(s) for s in ordered if metrics[s]["ma250_rel"] > 0]
        if up_ma:
            print(f"- 年线上方: {'、'.join(up_ma)}（中长期多头结构）")

    print(
        "\n> 注: 动量窗口 N 日 = close[t]/close[t-N]-1；二阶导 = 当前 N 日动量 − N 日前的 N 日动量 (pp)；"
        "成交额单位 tushare index_daily 口径为千元，各指数为自身成分股口径，跨指数绝对额不可直接类比；"
        "动量/成交额分位为全样本位置。本文只描述价格动力学与量价关系，非 v5 宏观策略交易信号，不进 overheat/panic 双轨指数。"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="指数速度/加速度/量价多指数对比观察面板")
    parser.add_argument(
        "--symbols",
        default=",".join(DEFAULT_SYMBOLS),
        help=f"指数代码，逗号分隔，默认 {'、'.join(INDEX_NAMES.get(s, s) for s in DEFAULT_SYMBOLS)}",
    )
    parser.add_argument(
        "--as-of", type=date.fromisoformat, default=None, help="截止交易日期 YYYY-MM-DD，默认最新"
    )
    args = parser.parse_args()
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    run(symbols, args.as_of or date.today())


if __name__ == "__main__":
    main()
