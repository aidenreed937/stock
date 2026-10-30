"""风格轮动观察：进攻/防守腿剪刀差 + 三指数速度/加速度/量价（宏观日报段落）。

口径与 .agents/skills/macro-risk-research/scripts/style_rotation_observation_panel.py 一致
（Ground Truth First，数据来自本地 Curated index_daily_bar，tushare 优先）：
- 一阶导（速度）= 各窗口动量 close[t]/close[t-N]-1，N = 5/20/60；
- 二阶导（加速度）= 当前 N 日动量 − N 日前的 N 日动量（pp）；
- 剪刀差 ratio = 创业板累计收益/红利累计收益（共同交易日窗口起点归一，>1 创业板跑赢）；
- 量 = 指数日成交额历史分位（tushare index_daily 口径为千元，分位为全样本位置）；
- 量价 = 近5日涨跌 vs 5日均额/20日均额 四象限定性（放量/缩量 × 涨/跌）。

定位：独立风格轮动观察段落，非 v5 交易信号，不进 overheat/panic 双轨指数
（v5 的红利↔创业板切换由宏观状态机驱动，不读取本段落）。

对外入口：build_style_rotation_section(target_date) -> str（数据缺失时返回空串）。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

BENCH = "000985.CSI"  # 中证全指（参考基准）
GROWTH = "399006.SZ"  # 创业板指（进攻腿）
HEDGED = "000922.CSI"  # 中证红利（防守腿）
STYLE_SYMBOLS = (BENCH, GROWTH, HEDGED)
# 各窗口动量最长回看至少需覆盖 60 交易日的两倍，用于产出二阶导
_MIN_ROWS = 130
_WINDOWS = (5, 20, 60)
_SC_DAYS = (21, 63, 126, 252)  # 近 1/3/6/12 月（交易日）


def _discover_index_daily() -> Path | None:
    """定位本地 Curated 指数日行情 parquet (tushare 优先，兼容理杏仁)。"""
    candidates = [
        Path("data/curated/tushare/market=CN/index_daily_bar/data.parquet"),
        Path("data/curated/lixinger/market=CN/index_daily_bar/data.parquet"),
    ]
    for p in candidates:
        if p.is_file():
            return p
    for root in ("data/curated/tushare", "data/curated/lixinger"):
        hits = sorted(Path(root).rglob("index_daily_bar/data.parquet"))
        if hits:
            return hits[0]
    return None


def _pct_rank(series: pl.Series, cur: float) -> float | None:
    vals = series.drop_nulls().to_list()
    if not vals:
        return None
    return sum(1 for x in vals if x <= cur) / len(vals) * 100.0


def _symbol_metrics(df: pl.DataFrame) -> dict[str, float]:
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
    amounts = df["amount"].to_list()
    ma250 = sum(closes[-250:]) / min(250, len(closes))
    amt_ma20 = sum(amounts[-20:]) / 20.0
    m: dict[str, float] = {"close": float(last["close"][0])}
    for w in _WINDOWS:
        m[f"r{w}"] = float(last[f"r{w}"][0])
        m[f"p{w}"] = _pct_rank(df[f"r{w}"], m[f"r{w}"]) or float("nan")
    m["a5"] = float(last["a5"][0]) * 100.0
    m["a20"] = float(last["a20"][0]) * 100.0
    m["amt_pct"] = float(last["amt_pct"][0])
    m["vol_ratio"] = sum(amounts[-5:]) / 5.0 / amt_ma20 if amt_ma20 > 0 else float("nan")
    m["ma250_rel"] = (float(last["close"][0]) / ma250 - 1.0) * 100.0
    return m


def _scissors_metrics(cy: pl.DataFrame, hd: pl.DataFrame) -> dict[str, float | None]:
    merged = (
        cy.rename({"close": "cy"})
        .join(hd.rename({"close": "hd"}), on="trade_date", how="inner")
        .sort("trade_date")
        .with_columns(
            (pl.col("cy") / pl.col("cy").first()).alias("cyn"),
            (pl.col("hd") / pl.col("hd").first()).alias("hdn"),
        )
        .with_columns((pl.col("cyn") / pl.col("hdn")).alias("ratio"))
    )
    vals = merged["ratio"].to_list()
    cur = vals[-1]
    pct = sum(1 for x in vals if x <= cur) / len(vals) * 100.0

    def rel(back: int) -> float | None:
        return cur / vals[-1 - back] - 1.0 if len(vals) > back else None

    sc1, sc3, sc6, sc12 = (rel(d) for d in _SC_DAYS)
    prev3 = None
    if len(vals) > 126:
        prev3 = vals[-1 - 63] / vals[-1 - 126] - 1.0
    mom250 = None
    if len(vals) > 252:
        lr = merged["ratio"].log()
        mom250 = float(lr[-1]) - float(lr[-1 - 252])
    return {
        "ratio": cur,
        "pct": pct,
        "mom250": mom250,
        "sc1": sc1,
        "sc3": sc3,
        "sc6": sc6,
        "sc12": sc12,
        "prev3": prev3,
        "delta": (sc3 - prev3) if (sc3 is not None and prev3 is not None) else None,
    }


def compute_style_rotation(bars: pl.DataFrame) -> dict[str, Any] | None:
    """由指数日行情计算风格轮动指标；数据不足返回 None。"""
    metrics: dict[str, dict[str, float]] = {}
    for sym in STYLE_SYMBOLS:
        sub = bars.filter(pl.col("symbol") == sym).sort("trade_date")
        if sub.height < _MIN_ROWS:
            return None
        metrics[sym] = _symbol_metrics(sub)
    sc = _scissors_metrics(
        bars.filter(pl.col("symbol") == GROWTH).sort("trade_date"),
        bars.filter(pl.col("symbol") == HEDGED).sort("trade_date"),
    )
    return {
        "metrics": metrics,
        "scissors": sc,
        "as_of": str(bars["trade_date"].max()),
    }


def _cent(x: float | None, hi: float, lo: float) -> str | None:
    if x is None:
        return None
    if x > hi:
        return "扩张"
    if x < lo:
        return "收缩"
    return "持平"


def _fmt_pct(x: float | None, digits: int = 2) -> str:
    return f"{x * 100:+.{digits}f}%" if x is not None else "n/a"


def _accel_word(mom: float, acc: float) -> str:
    if mom > 0 and acc > 0.005:
        return "上行加速"
    if mom > 0 and acc < -0.005:
        return "上行减速"
    if mom < 0 and acc > 0.005:
        return "下行减速"
    if mom < 0 and acc < -0.005:
        return "下行加速"
    return "基本平稳"


def _pq_label(r5: float, vr: float) -> str:
    if r5 > 0 and vr >= 1.05:
        return "放量上涨"
    if r5 > 0 and vr < 0.95:
        return "缩量上涨"
    if r5 < 0 and vr >= 1.05:
        return "放量下跌"
    if r5 < 0 and vr < 0.95:
        return "缩量下跌"
    return "量能均衡"


def render_style_rotation_section(computed: dict[str, Any]) -> str:
    """渲染风格轮动观察 Markdown 段落（宏观日报附录）。"""
    sc: dict[str, float | None] = computed["scissors"]
    metrics: dict[str, dict[str, float]] = computed["metrics"]
    lines: list[str] = []
    lines.append("## 风格轮动观察（独立参考，非 v5 信号）")
    lines.append("")
    lines.append("### 剪刀差（创业板指 vs 中证红利）")
    regime = _cent(sc["sc12"], 0.10, -0.10) or "持平"
    short = _cent(sc["delta"], 0.05, -0.05) or "持平"
    sc1_word = _cent(sc["sc1"], 0.03, -0.03) or "持平"
    sc6_word = _cent(sc["sc6"], 0.05, -0.05) or "持平"
    prev3_s = _fmt_pct(sc["prev3"], 1)
    delta_s = f"{sc['delta'] * 100:+.1f}pp" if sc["delta"] is not None else "—"
    mom250_s = f"{sc['mom250']:+.3f}" if sc["mom250"] is not None else "—"

    lines.append("| 周期 / 维度 | 剪刀差读数 | 历史 / 前期对比 | 状态定性 |")
    lines.append("| :--- | :---: | :---: | :--- |")
    lines.append(
        f"| **相对强度 Ratio** | `{sc['ratio']:.3f}` | 历史 {sc['pct']:.0f}% 分位 | 250D 动量 {mom250_s} |"
    )
    lines.append(f"| **近 1 月 (21D)** | `{_fmt_pct(sc['sc1'], 1)}` | — | {sc1_word} |")
    lines.append(
        f"| **近 3 月 (63D)** | `{_fmt_pct(sc['sc3'], 1)}` | 前3月 {prev3_s}（边际 {delta_s}） | 短期{short} |"
    )
    lines.append(f"| **近 6 月 (126D)** | `{_fmt_pct(sc['sc6'], 1)}` | — | {sc6_word} |")
    lines.append(f"| **近 1 年 (252D)** | `{_fmt_pct(sc['sc12'], 1)}` | — | 中长期{regime} |")
    lines.append("")
    lines.append(
        f"> 状态诊断：中长期{regime}（近1年 {_fmt_pct(sc['sc12'], 1)}），"
        f"短期{short}（近3月边际 {delta_s}），近1月{sc1_word}。"
    )

    lines.append("")
    lines.append("### 三指数速度/加速度/量价（中证全指 / 创业板指 / 中证红利）")
    lines.append("| 指数 | 5D | 20D | 60D | 20D加速度 | 成交额分位 | 近5日量价 |")
    lines.append("| :-- | --: | --: | --: | :-- | --: | :-- |")
    for s in STYLE_SYMBOLS:
        m = metrics[s]
        name = {"000985.CSI": "中证全指", "399006.SZ": "创业板指", "000922.CSI": "中证红利"}.get(
            s, s
        )
        lines.append(
            f"| {name} | {_fmt_pct(m['r5'])} | {_fmt_pct(m['r20'])} | {_fmt_pct(m['r60'])} | "
            f"{m['a20']:+.2f}pp {_accel_word(m['r20'], m['a20'] / 100)} | "
            f"{m['amt_pct']:.0f}% | {_pq_label(m['r5'], m['vol_ratio'])} |"
        )

    hd_pq = _pq_label(metrics[HEDGED]["r5"], metrics[HEDGED]["vol_ratio"])
    cy_pq = _pq_label(metrics[GROWTH]["r5"], metrics[GROWTH]["vol_ratio"])
    lines.append("")
    lines.append("### 解读")
    if regime == "扩张" and short == "收缩":
        lines.append("- 剪刀差结构：中长期扩张段 + 短期快速收敛，风格正边际切向防御")
    elif regime == "扩张" and short == "扩张":
        lines.append("- 剪刀差结构：中长期扩张段 + 短期继续扩张，成长进攻动能延续")
    elif regime == "收缩" and short == "扩张":
        lines.append("- 剪刀差结构：中长期收缩段 + 短期反弹，成长或处超跌修复")
    elif regime == "收缩":
        lines.append("- 剪刀差结构：中长期收缩段，红利系统性占优")
    else:
        lines.append("- 剪刀差结构：方向未形成显著背离，风格轮动处于观察期")
    if "放量下跌" in hd_pq:
        lines.append(
            "- 防御腿警示：中证红利近5日放量下跌，不是单纯避险切红利，"
            "红利内部也在被抛售（补跌），资金或在收缩整体风险敞口"
        )
    elif "缩量下跌" in hd_pq:
        lines.append("- 中证红利近5日缩量下跌：防御腿回调伴缩量，抛压有限但亦无进攻性")
    elif "缩量上涨" in hd_pq:
        lines.append("- 中证红利近5日缩量上涨：防御腿反弹但量能不配合，持续性存疑")
    if "缩量下跌" in cy_pq:
        lines.append("- 创业板近5日缩量下跌：情绪回落但抛压有限，缺乏增量承接")
    elif "放量上涨" in cy_pq:
        lines.append("- 创业板近5日放量上涨：成长主动进攻，剪刀差扩张有资金面支撑")
    if short == "收缩" and "放量下跌" in hd_pq:
        lines.append(
            "- 综合：风险偏好边际降温 + 防御腿补跌 = 收缩型轮动（risk-off），"
            "防御价值打折，比单向切红利更值得警惕"
        )
    elif short == "收缩":
        lines.append("- 综合：风格由成长切防御（剪刀差收敛），红利相对占优但驱动偏被动")
    elif short == "扩张" and "放量上涨" in cy_pq:
        lines.append("- 综合：成长主动进攻、风险偏好回升，风格轮动偏进攻")
    else:
        lines.append("- 综合：剪刀差边际方向未明确，等待量价确认")
    lines.append("")
    lines.append(
        "> 注: 独立风格轮动观察，非 v5 交易信号，不进 overheat/panic 双轨指数；成交额分位为各指数全样本位置。"
    )
    return "\n".join(lines)


def build_style_rotation_section(target_date: date) -> str:
    """生成宏观日报风格轮动段落；数据缺失/不足时返回空串。"""
    try:
        src = _discover_index_daily()
        if src is None:
            return ""
        bars = (
            pl.read_parquet(src)
            .with_columns(pl.col("trade_date").cast(pl.Date))
            .filter(pl.col("trade_date") <= target_date)
            .filter(pl.col("symbol").is_in(list(STYLE_SYMBOLS)))
            .select(["symbol", "trade_date", "close", "volume", "amount"])
            .sort(["symbol", "trade_date"])
        )
        computed = compute_style_rotation(bars)
        return render_style_rotation_section(computed) if computed else ""
    except Exception:
        return ""


__all__ = [
    "build_style_rotation_section",
    "compute_style_rotation",
    "render_style_rotation_section",
]
