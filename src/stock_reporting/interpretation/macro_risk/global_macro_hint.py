"""全球宏观与海外利率观察（动态数据提取与量化定性）。

定位：独立观测层，不作交易信号——海外利率因子的年度 IC 存在跨周期漂移，
其核心价值在于提供全球流动性与折现率背景，解释成长与红利风格分化。
所有数据与定性均为动态计算，禁止硬编码。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

_GLOBAL_MACRO_MART_PATH = Path("data/curated/mart/global_macro_daily.parquet")


@dataclass(frozen=True, slots=True)
class GlobalMacroItem:
    """单个宏观指标展示项。"""

    name: str
    display_value: str
    badge: str
    comment: str


@dataclass(frozen=True, slots=True)
class GlobalMacroHint:
    """全球宏观与海外利率观察输出结构。"""

    items: list[GlobalMacroItem]
    summary: str


def _eval_us10y(val: float) -> tuple[str, str]:
    if val >= 5.0:
        return "🔴", "站上 5% 关键高位，长久期科技成长估值承压"
    if val >= 4.2:
        return "🟡", "处于 4.2%~5.0% 偏高区间，贴现率持续受抑"
    return "⚪", "处于温和低位，海外折现率压制较弱"


def _eval_curve(val: float) -> tuple[str, str]:
    if val > 0:
        return "⚪", "收益率曲线倒挂解除陡峭化，期限溢价走阔"
    return "🔴", "收益率曲线倒挂，海外经济衰退与流动性收紧警示"


def _eval_spread(spread_pct: float, cn_10y: float, us_10y: float) -> tuple[str, str]:
    if spread_pct <= -2.5:
        return (
            "🔴",
            f"深度倒挂超 250 bps（国内 {cn_10y:.2f}% vs 美债 {us_10y:.2f}%），外资套息与汇率承压",
        )
    if spread_pct < 0:
        return (
            "🟡",
            f"适度倒挂（国内 {cn_10y:.2f}% vs 美债 {us_10y:.2f}%），中美利差存在一定压力",
        )
    return "🟢", f"正利差（国内 {cn_10y:.2f}% vs 美债 {us_10y:.2f}%），资金面环境友好"


def _eval_copper_gold(score: float) -> tuple[str, str]:
    if score >= 70.0:
        return "🟢", "大宗工业需求旺盛，全球制造业处于扩张期"
    if score <= 40.0:
        return "⚪", "大宗工业扩张预期平缓，黄金避险占优"
    return "⚪", "工业与避险需求处于均衡中枢"


def _eval_oil(
    wti_price: float | None,
    brent_price: float | None,
    spread_change: float | None,
    oil_changes: dict[str, float],
    high_threshold: float = 100.0,
    elevated_threshold: float = 85.0,
    low_threshold: float = 65.0,
    spread_shift_threshold: float = 5.0,
) -> tuple[str, str]:
    """根据最新原油价格、跨区价差走势及动能动态定性。"""
    prices = [p for p in (wti_price, brent_price) if p is not None]
    if not prices:
        return "⚪", "油价数据暂缺"

    # 基准参考价格（优先参考全球基准 Brent，若无则取 WTI）
    ref_price = brent_price if brent_price is not None else wti_price
    if ref_price is None:
        return "⚪", "油价数据暂缺"

    # 1. 价格区间定性与风险徽标
    if ref_price >= high_threshold:
        badge = "🔴"
        level_desc = "处于百元极端高位，输入型通胀黏性与滞胀预期显著，压制海外贴现率下行空间"
    elif ref_price >= elevated_threshold:
        badge = "🟡"
        level_desc = "处于偏高区间，对工业中下游成本与全球通胀预期存在边际压制"
    elif ref_price >= low_threshold:
        badge = "⚪"
        level_desc = "处于常态均衡中枢，通胀扰动相对中性"
    else:
        badge = "🟢"
        level_desc = "处于偏低区间，输入型成本压力显著释放，利好中下游制造业"

    # 2. 价差动能与跨区传导机制定性
    spread_desc = ""
    if spread_change is not None:
        if spread_change <= -spread_shift_threshold:
            spread_desc = (
                "Brent-WTI 价差显著收窄，表明前期局部地缘溢价向全谱系外溢，套利资金驱动美油补涨"
            )
        elif spread_change >= spread_shift_threshold:
            spread_desc = "Brent 对 WTI 溢价显著走阔，反映中东或欧洲航运受阻引发的局部断供溢价走高"
        else:
            spread_desc = "跨大西洋价差平稳，跨区套利物流与贸易传导正常"

    # 3. 相对强弱与动能速度
    rel_desc = ""
    if "WTI" in oil_changes and "Brent" in oil_changes:
        diff = oil_changes["WTI"] - oil_changes["Brent"]
        if abs(diff) >= 5.0:
            leader = "WTI" if diff > 0 else "Brent"
            rel_desc = f"{leader}动能相对领先 {abs(diff):.1f}pp"

    components = [level_desc]
    if spread_desc:
        components.append(spread_desc)
    if rel_desc:
        components.append(rel_desc)

    return badge, "；".join(components)


def _return_over_observations(
    frame: pl.DataFrame,
    column: str,
    observations: int = 20,
) -> float | None:
    if frame.height <= observations:
        return None
    values = frame.get_column(column).to_list()
    start = float(values[-observations - 1])
    latest = float(values[-1])
    if start == 0:
        return None
    return (latest / start - 1.0) * 100.0


def build_global_macro_hint(
    target_date: date | None = None,
    row_dict: dict[str, object] | None = None,
    mart_path: Path | None = None,
) -> GlobalMacroHint | None:
    """动态提取全球宏观与海外利率指标，生成量化看板。

    Args:
        target_date: 目标交易日。
        row_dict: 宏观因子表当前行（包含 copper_gold_score 等）。
        mart_path: global_macro_daily.parquet 路径，默认使用生产路径。
    """
    path = mart_path or _GLOBAL_MACRO_MART_PATH
    if not path.exists():
        return None

    try:
        df = pl.read_parquet(path)
    except Exception:
        return None

    if df.is_empty() or "trade_date" not in df.columns:
        return None

    df = df.with_columns(pl.col("trade_date").cast(pl.Date, strict=False)).sort("trade_date")
    avail = df.filter(pl.col("trade_date") <= target_date) if target_date is not None else df

    if avail.is_empty():
        return None

    items: list[GlobalMacroItem] = []

    # 1. 美债 10 年期收益率
    us_10y: float | None = None
    if "us_10y_yield" in avail.columns:
        us10y_series = avail.filter(pl.col("us_10y_yield").is_not_null())["us_10y_yield"]
        us_10y = float(us10y_series.tail(1).item()) if not us10y_series.is_empty() else None
        if us_10y is not None:
            badge, comment = _eval_us10y(us_10y)
            items.append(
                GlobalMacroItem(
                    name="美债 10 年期收益率",
                    display_value=f"{us_10y:.2f}%",
                    badge=badge,
                    comment=comment,
                )
            )

    # 2. 美债 10Y - 2Y 期限利差
    if "us_yield_curve_10y_2y" in avail.columns:
        curve_series = avail.filter(pl.col("us_yield_curve_10y_2y").is_not_null())[
            "us_yield_curve_10y_2y"
        ]
        curve = float(curve_series.tail(1).item()) if not curve_series.is_empty() else None
        if curve is not None:
            badge, comment = _eval_curve(curve)
            items.append(
                GlobalMacroItem(
                    name="美债 10Y - 2Y 期限利差",
                    display_value=f"{curve:+.2f}%",
                    badge=badge,
                    comment=comment,
                )
            )

    # 3. 中美 10Y 国债利差
    if "cn_10y_yield" in avail.columns:
        cn10y_series = avail.filter(pl.col("cn_10y_yield").is_not_null())["cn_10y_yield"]
        cn_10y = float(cn10y_series.tail(1).item()) if not cn10y_series.is_empty() else None
        if cn_10y is not None and us_10y is not None:
            spread_pct = cn_10y - us_10y
            badge, comment = _eval_spread(spread_pct, cn_10y, us_10y)
            bps = round(spread_pct * 100)
            items.append(
                GlobalMacroItem(
                    name="中美 10Y 国债利差",
                    display_value=f"{bps:+d} bps",
                    badge=badge,
                    comment=comment,
                )
            )

    # 4. 全球工业景气 (铜金比)
    cg_score = None
    if row_dict and "copper_gold_score" in row_dict:
        cg_val = row_dict.get("copper_gold_score")
        if isinstance(cg_val, int | float):
            cg_score = float(cg_val)
    if cg_score is not None:
        badge, comment = _eval_copper_gold(cg_score)
        items.append(
            GlobalMacroItem(
                name="全球工业景气 (铜金比)",
                display_value=f"{cg_score:.1f} 分位",
                badge=badge,
                comment=comment,
            )
        )

    wti = pl.DataFrame()
    if "crude_oil_price" in avail.columns:
        wti = (
            avail.select(
                "trade_date",
                pl.col("crude_oil_price").cast(pl.Float64, strict=False).alias("price"),
            )
            .drop_nulls(subset=["price"])
            .sort("trade_date")
        )
    brent = pl.DataFrame()
    if "brent_crude_oil_price" in avail.columns:
        brent = (
            avail.select(
                "trade_date",
                pl.col("brent_crude_oil_price").cast(pl.Float64, strict=False).alias("price"),
            )
            .drop_nulls(subset=["price"])
            .sort("trade_date")
        )
    wti_price: float | None = None
    brent_price: float | None = None
    if not wti.is_empty() or not brent.is_empty():
        display_values = []
        change_notes = []
        oil_changes: dict[str, float] = {}
        latest_dates = []
        if not wti.is_empty():
            wti_price = float(wti.get_column("price")[-1])
            latest_dates.append(wti.get_column("trade_date")[-1])
            display_values.append(f"WTI {wti_price:.2f}")
            change = _return_over_observations(wti, "price")
            if change is not None:
                oil_changes["WTI"] = change
                change_notes.append(f"WTI 近20个报价间隔 {change:+.1f}%")
        if not brent.is_empty():
            brent_price = float(brent.get_column("price")[-1])
            latest_dates.append(brent.get_column("trade_date")[-1])
            display_values.append(f"Brent {brent_price:.2f}")
            change = _return_over_observations(brent, "price")
            if change is not None:
                oil_changes["Brent"] = change
                change_notes.append(f"Brent 近20个报价间隔 {change:+.1f}%")

        spread_frame = pl.DataFrame()
        spread_change_val: float | None = None
        if not wti.is_empty() and not brent.is_empty():
            spread_frame = (
                wti.rename({"price": "wti_price"})
                .join(brent.rename({"price": "brent_price"}), on="trade_date", how="inner")
                .sort("trade_date")
            )
        if not spread_frame.is_empty():
            spread = float(spread_frame.get_column("brent_price")[-1]) - float(
                spread_frame.get_column("wti_price")[-1]
            )
            spread_note = f"Brent-WTI 价差 {spread:+.2f}"
            if spread_frame.height > 20:
                initial_spread = float(spread_frame.get_column("brent_price")[-21]) - float(
                    spread_frame.get_column("wti_price")[-21]
                )
                spread_change_val = spread - initial_spread
                spread_note += f"（近20个报价间隔变动 {spread_change_val:+.2f}）"
            change_notes.append(spread_note)
            latest_dates.append(spread_frame.get_column("trade_date")[-1])

        badge, dyn_interpretation = _eval_oil(
            wti_price=wti_price,
            brent_price=brent_price,
            spread_change=spread_change_val,
            oil_changes=oil_changes,
        )

        observation_date = max(latest_dates).isoformat()
        comment_parts = [f"报价截至 {observation_date}", *change_notes, dyn_interpretation]
        comment_parts.append("作为通胀与供给背景观察，不作单独交易信号")
        items.append(
            GlobalMacroItem(
                name="原油价格 (WTI / Brent)",
                display_value=" / ".join(display_values),
                badge=badge,
                comment="；".join(comment_parts) + "。",
            )
        )

    if not items:
        return None

    # 动态生成机制定性总结（联动利率、利差与大宗原油）
    is_high_us10y = us_10y is not None and us_10y >= 4.8
    is_deep_spread = (cn_10y is not None and us_10y is not None) and (cn_10y - us_10y <= -2.0)
    oil_prices = [p for p in (wti_price, brent_price) if p is not None]
    max_oil = max(oil_prices, default=None)
    is_high_oil = max_oil is not None and max_oil >= 100.0

    if is_high_oil and (is_high_us10y or is_deep_spread):
        summary = (
            "大宗原油高位运行加剧全球再通胀黏性，叠加无风险折现率高位运行与中美利差倒挂，"
            "外生流动性推力缺失，强化 A 股内部高股息防守与低估值出清格局。"
        )
    elif is_high_us10y or is_deep_spread:
        summary = (
            "全球无风险折现率高位运行且中美利差处于倒挂区间，"
            "外生流动性推力缺失，强化 A 股内部高股息防守与低估值出清格局。"
        )
    elif is_high_oil:
        summary = (
            "大宗原油高位运行加剧再通胀预期与海外折现率扰动，"
            "对 A 股中下游制造成本与高估值成长板块形成阶段性估值压制。"
        )
    else:
        summary = "全球宏观、大宗能源与海外流动性处于中性区间，对 A 股风格与估值无极端压制。"

    return GlobalMacroHint(items=items, summary=summary)


__all__ = ["GlobalMacroHint", "GlobalMacroItem", "build_global_macro_hint"]
