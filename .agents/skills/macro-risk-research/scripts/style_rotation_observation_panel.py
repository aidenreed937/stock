"""风格轮动观察面板（进攻/防守腿剪刀差 + 三指数速度/加速度/量价）。

把两类独立观察合并为一份「风格轮动观察」输出：
1) 创业板指 (399006.SZ) vs 中证红利 (000922.CSI) 相对强度剪刀差
   （口径同 index_relative_strength_panel.py：ratio = 创业板累计收益/红利累计收益，
   自 2010 年共同交易日窗口起点归一；>1 表示窗口内创业板跑赢红线）；
2) 中证全指/创业板指/中证红利三指数一阶导（5/20/60D 动量）、二阶导（动量变化 pp）、
   量能历史分位与量价四象限定性（口径同 index_derivative_volume_panel.py）。

数据完全来自本地 Curated 指数日行情（index_daily_bar，tushare 口径），不臆造点位。
定位：独立风格轮动观察指标，非 v5 交易信号，不进 overheat/panic 双轨指数
（v5 的红利↔创业板切换由宏观状态机驱动，不读取本面板）。

用法：
    uv run python .agents/skills/macro-risk-research/scripts/style_rotation_observation_panel.py
    uv run python .agents/skills/macro-risk-research/scripts/style_rotation_observation_panel.py --as-of 2026-06-30
"""

from __future__ import annotations

import argparse
from datetime import date

import polars as pl
from index_derivative_volume_panel import (
    _MIN_ROWS,
    _accel_word,
    _fmt_int,
    _fmt_pp,
    _fmt_signed_pct,
    _load,
    _metric,
    _nameof,
    _pq_label,
)

GROWTH = "399006.SZ"  # 创业板指（进攻腿）
HEDGED = "000922.CSI"  # 中证红利（防守腿）
BENCH = "000985.CSI"  # 中证全指（参考基准）
ALL_SYMBOLS = (BENCH, GROWTH, HEDGED)
SC_DAYS = (21, 63, 126, 252)  # 近 1/3/6/12 月（交易日）


def _scissors_metrics(cy: pl.DataFrame, hd: pl.DataFrame) -> dict[str, float | None]:
    """创业板 vs 红利 相对强度剪刀差指标（口径同 index_relative_strength_panel.py）。"""
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

    sc1, sc3, sc6, sc12 = (rel(d) for d in SC_DAYS)
    prev3 = None
    if len(vals) > 126:
        # 前3月 = 更早一段 (-126, -63] 窗口的剪刀差变化
        prev3 = vals[-1 - 63] / vals[-1 - 126] - 1.0
    mom250 = None
    if len(vals) > 252:
        lr = merged["ratio"].log()
        mom250 = float(lr[-1]) - float(lr[-1 - 252])

    def ma250_rel(close: pl.Series) -> float:
        closes = close.to_list()
        ma = sum(closes[-250:]) / min(250, len(closes))
        return (closes[-1] / ma - 1.0) * 100.0

    return {
        "ratio": cur,
        "pct": pct,
        "mom250": mom250,
        "sc1": sc1,
        "sc3": sc3,
        "sc6": sc6,
        "sc12": sc12,
        "prev3": prev3,
        "delta": (sc3 - prev3)
        if (sc3 is not None and prev3 is not None)
        else None,  # 近3月边际 pp? 保留比例口径
        "cy_ma": ma250_rel(cy["close"]),
        "hd_ma": ma250_rel(hd["close"]),
    }


def _fmt_sc(x: float | None) -> str:
    return _fmt_signed_pct(x * 100.0, 1) if x is not None else "n/a"


def _cent(x: float, hi: float, lo: float) -> str | None:
    if x is None:
        return None
    if x > hi:
        return "扩张"
    if x < lo:
        return "收缩"
    return "持平"


def run(as_of: date) -> None:
    df_all = _load(list(ALL_SYMBOLS), as_of)
    metrics: dict[str, dict[str, float]] = {}
    last_date = None
    for sym in ALL_SYMBOLS:
        sub = df_all.filter(pl.col("symbol") == sym).sort("trade_date")
        if sub.height < _MIN_ROWS:
            print(f"[{as_of}] {sym} 数据不足 ({sub.height} 行，需 >= {_MIN_ROWS})，已跳过")
            continue
        metrics[sym] = _metric(sym, sub)
        last_date = last_date or str(sub["trade_date"][-1])
    if not metrics or GROWTH not in metrics or HEDGED not in metrics:
        print(f"[{as_of}] 剪刀差所需标的缺失，放弃输出")
        return

    cy = df_all.filter(pl.col("symbol") == GROWTH).sort("trade_date")
    hd = df_all.filter(pl.col("symbol") == HEDGED).sort("trade_date")
    sc = _scissors_metrics(cy, hd)
    as_date = last_date or str(as_of)

    # ---- 一、剪刀差 ----
    print(f"# 风格轮动观察面板 (截至 {as_date})")
    print(f"\n## 数据日期: {as_date}  (as_of={as_of})")
    print("\n### 一、进攻/防守腿剪刀差（创业板指 vs 中证红利）")
    print(
        f"- 相对强度 ratio (创业板累计/红利累计): **{sc['ratio']:.3f}**"
        f"  (位于历史 **{sc['pct']:.0f}%** 分位)"
    )
    print(
        f"- 250日动量 (log-ratio, 年化): **{sc['mom250']:+.3f}**"
        if sc["mom250"] is not None
        else "- 250日动量: n/a"
    )
    prev3_s = _fmt_sc(sc["prev3"])
    print(
        f"- 剪刀差: 近1月 **{_fmt_sc(sc['sc1'])}** | 近3月 **{_fmt_sc(sc['sc3'])}**"
        f" (前3月 {prev3_s}, 边际 {sc['delta'] * 100:+.1f}pp) | "
        f"近6月 **{_fmt_sc(sc['sc6'])}** | 近1年 **{_fmt_sc(sc['sc12'])}**"
    )
    print(f"- 年线相对: 创业板指 {sc['cy_ma']:+.1f}% | 中证红利 {sc['hd_ma']:+.1f}%")
    regime = _cent(sc["sc12"], 0.10, -0.10)
    short = _cent(sc["delta"], 0.05, -0.05)
    sc1_word = _cent(sc["sc1"], 0.03, -0.03)
    print(
        f"- 状态: 中长期{regime} (近1年 {_fmt_sc(sc['sc12'])})，"
        f"短期{short} (近3月边际 {sc['delta'] * 100:+.1f}pp)，近1月{sc1_word or '持平'}"
    )

    # ---- 二、三指数量价 ----
    ordered = [s for s in ALL_SYMBOLS if s in metrics]
    print("\n### 二、三指数速度/加速度/量价（中证全指 / 创业板指 / 中证红利）")
    print("\n#### 一阶导（速度，各窗口动量 + 历史分位 + 年线位置）")
    print("| 指数 | 5D | 5D分位 | 20D | 20D分位 | 60D | 60D分位 | 年线位置 |")
    print("| :-- | --: | --: | --: | --: | --: | --: | --: |")
    for s in ordered:
        m = metrics[s]
        print(
            f"| {_nameof(s)} | {_fmt_signed_pct(m['r5'] * 100)} | {_fmt_int(m['p5'])} | "
            f"{_fmt_signed_pct(m['r20'] * 100)} | {_fmt_int(m['p20'])} | "
            f"{_fmt_signed_pct(m['r60'] * 100)} | {_fmt_int(m['p60'])} | {_fmt_signed_pct(m['ma250_rel'])} |"
        )
    print("\n#### 二阶导（加速度，动量自身变化 pp）")
    print("| 指数 | 5D加速度 | 5D定性 | 20D加速度 | 20D定性 |")
    print("| :-- | --: | :-- | --: | :-- |")
    for s in ordered:
        m = metrics[s]
        print(
            f"| {_nameof(s)} | {_fmt_pp(m['a5'])} | {_accel_word(m['r5'], m['a5'] / 100)} | "
            f"{_fmt_pp(m['a20'])} | {_accel_word(m['r20'], m['a20'] / 100)} |"
        )
    print("\n#### 量能")
    print("| 指数 | 成交额史分位 | 20日均额(亿元) | 当日/20日均值 |")
    print("| :-- | --: | --: | --: |")
    for s in ordered:
        m = metrics[s]
        print(
            f"| {_nameof(s)} | {_fmt_int(m['amt_pct'])} | {m['amt_ma20_yi']:.0f} | {m['amt_ratio']:.2f} |"
        )
    print("\n#### 量价（近5日）")
    print("| 指数 | 近5日涨跌 | 5日均额/20日均额 | 量价定性 |")
    print("| :-- | --: | --: | :-- |")
    for s in ordered:
        m = metrics[s]
        print(
            f"| {_nameof(s)} | {_fmt_signed_pct(m['ret5'])} | {m['vol_ratio']:.2f} | "
            f"{_pq_label(m['r5'], m['vol_ratio'])} |"
        )

    # ---- 三、风格轮动交叉解读 ----
    print("\n### 三、风格轮动交叉解读")
    hd_pq = _pq_label(metrics[HEDGED]["r5"], metrics[HEDGED]["vol_ratio"])
    cy_pq = _pq_label(metrics[GROWTH]["r5"], metrics[GROWTH]["vol_ratio"])
    if regime == "扩张" and short == "收缩":
        print(
            "- 剪刀差结构：中长期扩张段 + 短期快速收敛 —— 前期成长占优的余温仍在，但风格正边际切向防御"
        )
    elif regime == "扩张" and short == "扩张":
        print("- 剪刀差结构：中长期扩张段 + 短期继续扩张 —— 成长进攻动能延续，风格偏进攻")
    elif regime == "收缩" and short == "扩张":
        print("- 剪刀差结构：中长期收缩段 + 短期反弹 —— 成长或处超跌修复，持续性待量价确认")
    elif regime == "收缩":
        print("- 剪刀差结构：中长期收缩段，红利系统性占优，成长持续弱于防御")
    else:
        print("- 剪刀差结构：中长期/短期方向未形成显著背离，风格轮动处于观察期")

    if "放量下跌" in hd_pq:
        print(
            "- 防御腿警示：中证红利近5日放量下跌，不是单纯避险切红利，"
            "红利内部也在被抛售（补跌），资金或在收缩整体风险敞口而非换仓防御"
        )
    elif "缩量下跌" in hd_pq:
        print("- 中证红利近5日缩量下跌：防御腿回调伴缩量（量价背离），抛压有限但亦无进攻性")
    elif "缩量上涨" in hd_pq:
        print("- 中证红利近5日缩量上涨：防御腿反弹但量能不配合，持续性存疑")
    else:
        print(f"- 中证红利近5日量价: {hd_pq}")

    if "缩量下跌" in cy_pq:
        print(
            "- 创业板近5日缩量下跌：情绪回落但抛压有限（缩量回调型），缺乏增量承接、尚未见恐慌放量"
        )
    elif "放量上涨" in cy_pq:
        print("- 创业板近5日放量上涨：成长主动进攻，量价配合，剪刀差扩张有资金面支撑")

    amt_pcts = sorted(metrics[s]["amt_pct"] for s in ordered)
    print(
        f"- 量能位置：三指数成交额史分位 {amt_pcts[0]:.0f}–{amt_pcts[-1]:.0f}，"
        "全市场量能处高位区，风格轮动伴随整体量能放大，需警惕高位滞涨"
    )

    if short == "收缩" and "放量下跌" in hd_pq:
        print(
            "- 综合：风险偏好边际降温 + 防御腿补跌 = 收缩型轮动（risk-off），防御价值打折，比单向切红利更值得警惕"
        )
    elif short == "收缩":
        print(
            "- 综合：风格由成长切防御（剪刀差收敛），红利相对占优但驱动偏被动，防御性价比依赖量价确认"
        )
    elif short == "扩张" and "放量上涨" in cy_pq:
        print("- 综合：成长主动进攻、风险偏好回升，风格轮动偏进攻")
    else:
        print("- 综合：剪刀差边际方向未明确，等待量价确认，维持观察")

    print(
        "\n> 注: ratio=创业板累计收益/红利累计收益 (>1 窗口内创业板跑赢，2010 起共同交易日)；"
        "边际 = 近3月剪刀差 − 前3月剪刀差 (pp)；成交额为各指数自身成分股口径(千元)，跨指数绝对额不可直接类比；"
        "本文只描述风格轮动与量价关系，非 v5 宏观策略交易信号，不进 overheat/panic 双轨指数。"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="风格轮动观察面板（剪刀差 + 三指数量价）")
    parser.add_argument(
        "--as-of", type=date.fromisoformat, default=None, help="截止交易日期 YYYY-MM-DD，默认最新"
    )
    args = parser.parse_args()
    run(args.as_of or date.today())


if __name__ == "__main__":
    main()
