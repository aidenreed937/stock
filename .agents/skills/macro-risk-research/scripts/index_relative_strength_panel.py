"""创业板指 (399006.SZ) vs 中证红利 (000922.CSI) 相对强度趋势观察面板。

口径说明（Ground Truth First）：
- 数据完全来自本地 Curated 指数日行情（index_daily_bar），不臆造任何点位。
- 相对强度 = 创业板累计收益 / 红利累计收益（自窗口起点归一），ratio>1 表示窗口内
  创业板跑赢红利，叠加方向指示剪刀差。
- 输出：当前读数 + 近1/3/6/12月超额 + 250日动量 + 年线相对位置 + 历史分位 +
  基于 log-ratio 均值回归的定性拐点解读。

用法：
    uv run python scripts/index_relative_strength_panel.py               # 最新交易日
    uv run python scripts/index_relative_strength_panel.py --as-of 2026-06-30
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import polars as pl

GROWTH = "399006.SZ"  # 创业板指
HEDGED = "000922.CSI"  # 中证红利
BENCH = "000985.CSI"  # 中证全指 (参考基准)

# 各曲线最长回看窗口需至少覆盖的最大年月 (约 3 年) 用于产出充分样本
_START = date(2010, 1, 1)


def _discover_index_daily() -> Path:
    """定位本地 Curated 指数日行情 parquet (兼容修鞋/理杏仁两处)。"""
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


def _load(close_until: date) -> pl.DataFrame:
    src = _discover_index_daily()
    df = (
        pl.read_parquet(src)
        .with_columns(pl.col("trade_date").cast(pl.Date))
        .filter(pl.col("trade_date") <= close_until)
        .filter(pl.col("symbol").is_in([GROWTH, HEDGED, BENCH]))
        .select(["symbol", "trade_date", "close"])
        .sort(["symbol", "trade_date"])
    )
    return df


def _window_ret(df: pl.DataFrame, days: int) -> float | None:
    if df.height <= days:
        return None
    cur = float(df["close"][-1])
    past = float(df["close"][-1 - days])
    if past <= 0:
        return None
    return cur / past - 1.0


def run(as_of: date) -> None:
    df = _load(as_of)

    def series(sym: str) -> pl.DataFrame:
        return df.filter(pl.col("symbol") == sym).select(["trade_date", "close"]).sort("trade_date")

    cy = series(GROWTH)
    hd = series(HEDGED)
    bench = series(BENCH)
    if cy.height < 260 or hd.height < 260:
        print(f"[{as_of}] 数据不足 (cy={cy.height}, hd={hd.height})")
        return

    # ---- 相对强度 ratio (自窗口起点归一) ----
    merged = (
        cy.rename({"close": "cy"})
        .join(hd.rename({"close": "hd"}), on="trade_date", how="inner")
        .sort("trade_date")
        .with_columns(
            (pl.col("cy") / pl.col("cy").first()).alias("cyn"),
            (pl.col("hd") / pl.col("hd").first()).alias("hdn"),
        )
        .with_columns(
            (pl.col("cyn") / pl.col("hdn")).alias("ratio"),
            (pl.col("cy") / pl.col("hd")).alias("raw"),
        )
    )

    # ---- 各期超额与动量 ----
    def relative_ratio_days(back: int) -> float | None:
        if merged.height <= back:
            return None
        cur = float(merged["ratio"][-1])
        past = float(merged["ratio"][-1 - back])
        if past <= 0:
            return None
        return cur / past - 1.0

    rel1 = relative_ratio_days(21)
    rel3 = relative_ratio_days(63)
    rel6 = relative_ratio_days(126)
    rel12 = relative_ratio_days(252)

    # 250 日动量 (log-ratio 差分, 年均化)
    lr = merged["ratio"].log()
    mom250 = (float(lr[-1]) - float(lr[-1 - 252])) if merged.height > 252 else None

    # 历史分位 (相对强度当前处于历史多高)
    r_all = merged["ratio"].drop_nulls().to_list()
    cur_ratio = r_all[-1]
    pct = sum(1 for x in r_all if x <= cur_ratio) / len(r_all) * 100

    # ---- 各指数自身中长期趋势 (60/120/250 日均线) ----
    def ma_status(cur_close: float, closes: pl.Series) -> str:
        values = closes.tail(250).to_list()
        ma250 = float(sum(values) / len(values)) if values else 0.0
        rel = (cur_close / ma250 - 1.0) * 100 if ma250 > 0 else float("nan")
        return f"{cur_close:.0f} (年线{rel:+.1f}%)"

    cy_status = ma_status(float(cy["close"][-1]), cy["close"])
    hd_status = ma_status(float(hd["close"][-1]), hd["close"])
    b_status = (
        ma_status(float(bench["close"][-1]), bench["close"]) if bench.height >= 250 else "n/a"
    )

    as_date = str(cy["trade_date"][-1])

    # ---- 定性拐点解读 ----
    verdict = []
    if rel12 is not None and rel12 > 0.10:
        verdict.append(f"近1年创业板相对红利走强 ({rel12 * 100:+.0f}%)，剪刀差处中长期扩张段")
    elif rel12 is not None and rel12 < -0.10:
        verdict.append(f"近1年创业板相对红利走弱 ({rel12 * 100:+.0f}%)，剪刀差处收缩段")
    else:
        verdict.append("近1年剪刀差总体持平")

    # 近3月 vs 前一个3月 (前一个3月 = ratio_{-63}/ratio_{-126} - 1)，比较边际变化
    prev3 = None
    if merged.height > 126:
        r_m63 = float(merged["ratio"][-1 - 63])
        r_m126 = float(merged["ratio"][-1 - 126])
        prev3 = (r_m63 / r_m126 - 1.0) if r_m126 > 0 else None
    if rel3 is not None and prev3 is not None:
        delta = rel3 - prev3
        if delta > 0.05:
            verdict.append(
                f"近3月较前3月相对强度进一步扩张 (边际 {delta * 100:+.0f}%)，创业板动量增强"
            )
        elif delta < -0.05:
            verdict.append(
                f"近3月较前3月相对强度回落 (边际 {delta * 100:+.0f}%)，创业板动量走弱/红利相对占优"
            )
        else:
            verdict.append("近3月相对强度较前3月基本持平，方向未明确变化")

    if rel3 is not None and rel3 < -0.08:
        verdict.append("警示：近3月剪刀差明显收敛，短期创业板或正落后红利")
    if rel1 is not None:
        if rel1 > 0.03:
            verdict.append(f"近1月剪刀差转扩张 ({rel1 * 100:+.1f}%)，创业板短期动能回升")
        elif rel1 < -0.03:
            verdict.append(f"近1月剪刀差继续收敛 ({rel1 * 100:+.1f}%)，创业板短期仍落后红利")

    # ---- 输出 ----
    print(f"# 创业板指/中证红利 相对强度观察面板 (截至 {as_date})")
    print(f"\n## 数据日期: {as_date}  (as_of={as_of})")
    print("\n### 当前读数")
    print(
        f"- 相对强度 ratio (创业板累计/红利累计): **{cur_ratio:.3f}**  (位于历史 **{pct:.0f}%** 分位)"
    )
    print(f"- 250日动量 (log-ratio, 年化): **{mom250:.3f}**")
    prev3_str = f"{prev3 * 100:+.1f}%" if prev3 is not None else "n/a"
    rel1_s = rel1 if rel1 is not None else 0.0
    rel3_s = rel3 if rel3 is not None else 0.0
    rel6_s = rel6 if rel6 is not None else 0.0
    rel12_s = rel12 if rel12 is not None else 0.0
    print(
        f"- 剪刀差: 近1月 **{rel1_s * 100:+.1f}%**  |  近3月 **{rel3_s * 100:+.1f}%** (前3月: {prev3_str})  |  近6月 **{rel6_s * 100:+.1f}%**  |  近1年 **{rel12_s * 100:+.1f}%**"
    )
    print("\n### 各指数中长期趋势 (最新收盘 + 年线相对)")
    print(f"- 创业板指: {cy_status}")
    print(f"- 中证红利: {hd_status}")
    print(f"- 中证全指: {b_status}")
    print("\n### 解读")
    for v in verdict:
        print(f"- {v}")
    print(
        "\n> 注: ratio=创业板累计收益/红利累计收益 (>1 窗口内创业板跑赢)；"
        "历史分位为相对强度在全样本 (2010 起共同交易日) 中的位置。"
        "本文只描述市场相对强弱，非 v5 策略交易信号。"
        "数据源: 本地 Curated index_daily_bar。"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="创业板指/中证红利相对强度趋势观察面板")
    parser.add_argument(
        "--as-of", type=date.fromisoformat, default=None, help="截止日期 (默认最新)"
    )
    args = parser.parse_args()
    as_of = args.as_of or date.today()
    run(as_of)


if __name__ == "__main__":
    main()
