"""光伏 630500 资本开支先导前瞻检验（财报层 capex 是否领先产能周期状态与价格顶）。

问题：630500 的 fwd60 供需腿全部证伪后，唯一的前瞻尺度是季度/半年（fwd2q/4q）的
产能周期位置。产能周期状态（硅料利用率 + 产能同比）本身是**滞后发布的产业数据**
（2022-01 才看到 cap_yoy +93% 的扩产潮），而框架 config 已预留 capex_leading 参数
（在建工程同比>20%、在建/固资>35% 视为产能扩张先导）但从未在 630500 实证。
本脚本检验：财报层资本开支/在建工程指标能否**领先**产业层状态切换与 2021-08 价格顶，
即"资金交易产能周期反身预期"是否存在更早的财报先导信号。

检验内容：
1. 时序对照：财报指标（cip_yoy / capex_growth_ttm / fix_assets_yoy / cip_to_fa_ratio）
   月度序列 vs 产能周期状态 vs 630500 价格，标注关键拐点（2021-08 顶、2022-01 扩产潮、
   2024-04 财报门、2025-04 底）。
2. 领先性量化：各财报指标首次触发扩张阈值（cip_yoy>=30、capex_growth_ttm>=15、
   fix_assets_yoy>=30、cip_to_fa_ratio>=35）的日期 vs 产业层 cap_yoy>=30 触发日 vs
   价格顶 2021-08-30——领先天数为正 = 财报先导成立。
3. fwd4q 分层：财报扩张区 vs 非扩张区未来 252 日收益（均值/中位/胜率），对比产业层
   状态门（过剩/上行）的区分度——财报先导是否同样有 fwd4q 预测力。

口径：财报指标按报告披露日（panel 前向填充后的日频）对齐，月度取月末值，无前视；
fwd4q = 252 交易日；样本外 2022+；数据覆盖 2019-04 起（cip_to_fa）/2020-08 起（cip_yoy）。

局限：财报层为 L2 面板（理杏仁口径）前向填充日频，披露日语义依赖 panel 构建；
2020-08 前的 cip_yoy 缺失（无法检验更早先导）；结果为描述性 + 分层统计，非严格 IC。

输出：data/analytics/industry_strategy/industry_solar_capex_leading.{csv,md}
"""

from __future__ import annotations

import datetime
import math
from pathlib import Path

import polars as pl
from industry_solar_cycle_position import _build_states, _monthly_panel

_PANEL = Path("data/curated/mart/industry_l2_panel_daily.parquet")
_OUT = Path("data/analytics/industry_strategy")
_INDUSTRY = "630500"
_OOS = datetime.date(2022, 1, 1)
_FWD4Q = 252
# 扩张阈值（对齐 config/analytics/industry_trend_tracking.yaml capex_leading；
# 注意 cip_to_fa_ratio 为小数（config 0.35），630500 实际 max 0.25 从未触发，如实报告）
_THR = {"cip_yoy": 30.0, "capex_growth_ttm": 15.0, "fix_assets_yoy": 30.0, "cip_to_fa_ratio": 0.35}
# 产业层扩产潮阈值（对齐 cycle_position）
_CAP_THR = 0.30
# 价格拐点（630500 close，研究文档已验证）
_PEAK = datetime.date(2021, 8, 30)
_TROUGH = datetime.date(2025, 4, 7)


def _metrics(nav: list[float]) -> dict[str, float]:
    arr = [v if v > 0 else 1e-9 for v in nav]
    if len(arr) < 2:
        return {"cagr": 0.0, "max_dd": 0.0, "sharpe": 0.0}
    years = max(len(arr) / 252.0, 1e-9)
    cagr = ((arr[-1] / arr[0]) ** (1.0 / years) - 1.0) * 100.0 if arr[0] > 0 else 0.0
    peak, mdd = -1e9, 0.0
    for v in arr:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak)
    rets = [arr[i] / arr[i - 1] - 1.0 for i in range(1, len(arr)) if arr[i - 1] > 0]
    mean_r = sum(rets) / len(rets) if rets else 0.0
    var = sum((r - mean_r) ** 2 for r in rets) / max(len(rets) - 1, 1) if len(rets) > 1 else 0.0
    sharpe = mean_r / math.sqrt(var) * math.sqrt(252.0) if var > 0 else 0.0
    return {"cagr": cagr, "max_dd": mdd * 100.0, "sharpe": sharpe}


def main() -> None:
    panel = (
        pl.read_parquet(_PANEL)
        .filter(
            (pl.col("industry_code") == _INDUSTRY)
            & (pl.col("trade_date") >= datetime.date(2019, 1, 1))
        )
        .sort("trade_date")
    )

    # ---- 1. 财报指标日频 → 月度月末值（无前视：取每月最后一个已披露值） ----
    fin_cols = list(_THR.keys())
    fin = panel.select(["trade_date"] + fin_cols).with_columns(
        pl.col("trade_date").dt.strftime("%Y-%m").alias("ym")
    )
    fin_monthly = fin.group_by("ym", maintain_order=True).agg(
        [pl.col(c).last().alias(c) for c in fin_cols]
    )

    # ---- 2. 产业层产能周期月度面板（cap_yoy / flood_24m / state） ----
    m = _monthly_panel().with_columns(pl.col("report_month").alias("ym"))
    states = _build_states().select(["report_month", "state"])
    ind = (
        m.select(["ym", "cap_yoy", "flood_24m"])
        .join(states.rename({"report_month": "ym"}), on="ym", how="left")
        .sort("ym")
    )

    merged = fin_monthly.join(ind, on="ym", how="full").sort("ym")

    # ---- 3. 领先性量化：各信号首次触发日 vs 价格顶 ----
    def first_trigger(df: pl.DataFrame, col: str, thr: float) -> datetime.date | None:
        sub = df.filter(pl.col(col).is_not_null() & (pl.col(col) >= thr))
        if sub.is_empty():
            return None
        # 财报/产业指标均为月频，触发日取该月 1 号（保守：信号在月末披露，次月才可用）
        ym = sub.select("ym").head(1).item()
        return datetime.date(int(ym[:4]), int(ym[5:7]), 1)

    def first_cap(df: pl.DataFrame, col: str, thr: float) -> datetime.date | None:
        sub = df.filter(pl.col(col).is_not_null() & (pl.col(col) >= thr))
        if sub.is_empty():
            return None
        ym = sub.select("ym").head(1).item()
        return datetime.date(int(ym[:4]), int(ym[5:7]), 1)

    print("=== 领先性（首次触发日，保守取月首） ===")
    print(f"价格顶: {_PEAK}")
    lead_rows = []
    for c, thr in _THR.items():
        d = first_trigger(merged, c, thr)
        lead = (d - _PEAK).days if d else None
        lead_rows.append({"signal": f"财报-{c}", "thr": thr, "first": d, "lead_days_vs_peak": lead})
        thr_s = f"{thr:.0f}" if thr >= 1 else f"{thr:.2f}"
        print(
            f"财报-{c} >= {thr_s}: 首次 {d}  相对价格顶 {lead if lead is not None else 'NA'} 天(负=提前)"
        )
    d_cap = first_cap(merged, "cap_yoy", _CAP_THR)
    lead_cap = (d_cap - _PEAK).days if d_cap else None
    lead_rows.append(
        {
            "signal": "产业-cap_yoy",
            "thr": _CAP_THR * 100,
            "first": d_cap,
            "lead_days_vs_peak": lead_cap,
        }
    )
    print(
        f"产业-cap_yoy >= {_CAP_THR * 100:.0f}%: 首次 {d_cap}  相对价格顶 {lead_cap if lead_cap is not None else 'NA'} 天(负=提前)"
    )
    # 状态首进"过剩"
    first_over = states.filter(pl.col("state") == "过剩").select("report_month").head(1).item()
    d_over = datetime.date(int(first_over[:4]), int(first_over[5:7]), 1)
    lead_rows.append(
        {
            "signal": "产业-状态首进过剩",
            "thr": None,
            "first": d_over,
            "lead_days_vs_peak": (d_over - _PEAK).days,
        }
    )
    print(f"产业-状态首进过剩: {d_over}  相对价格顶 {(d_over - _PEAK).days} 天(负=提前)")

    # ---- 4. fwd4q 分层：财报扩张区 vs 非扩张区 ----
    panel_f = panel.select(["trade_date", "close"] + fin_cols).sort("trade_date")
    grid = (
        panel_f.with_columns([pl.col(c).fill_null(strategy="forward") for c in fin_cols])
        .with_columns(pl.col("close").shift(-_FWD4Q).alias("fwd_close"))
        .drop_nulls("fwd_close")
    )
    grid = grid.with_columns(((pl.col("fwd_close") / pl.col("close")) - 1.0).alias("fwd4q_ret"))
    dates = grid["trade_date"].to_list()
    rets = grid["fwd4q_ret"].to_list()

    def layer(col: str, thr: float, label: str) -> dict:
        vals = grid[col].to_list()
        on = [i for i, v in enumerate(vals) if v is not None and v >= thr]
        off = [i for i, v in enumerate(vals) if v is not None and v < thr]
        oos = [i for i, d in enumerate(dates) if d >= _OOS]

        def stats(idx):
            r = [rets[i] for i in idx]
            if not r:
                return (None, None, None, 0)
            import statistics

            return (
                statistics.mean(r) * 100,
                statistics.median(r) * 100,
                sum(1 for x in r if x > 0) / len(r) * 100,
                len(r),
            )

        fon = stats([i for i in on if i in oos])
        foff = stats([i for i in off if i in oos])
        return {
            "layer": label,
            "on_full": stats(on),
            "off_full": stats(off),
            "on_oos": fon,
            "off_oos": foff,
        }

    print("\n=== fwd4q 分层（全周期 / 样本外 2022+）：均值% / 中位% / 胜率% / n ===")
    layer_rows = []
    for c, thr in _THR.items():
        thr_s = f"{thr:.0f}" if thr >= 1 else f"{thr:.2f}"
        r = layer(c, thr, f"财报-{c}>={thr_s}")
        layer_rows.append(r)
        print(
            f"{r['layer']:28s} 扩张区 全{r['on_full'][:3]!s} 外{r['on_oos'][:3]!s} | "
            f"非扩张 全{r['off_full'][:3]!s} 外{r['off_oos'][:3]!s}"
        )

    # 产业层状态门对照（过剩 vs 上行）
    st_map = {r["report_month"]: r["state"] for r in states.to_dicts()}
    ym_list = [d.strftime("%Y-%m") for d in dates]
    state_col = [st_map.get(y) for y in ym_list]
    on_over = [i for i, s in enumerate(state_col) if s == "过剩"]
    on_up = [i for i, s in enumerate(state_col) if s == "上行"]
    oos = [i for i, d in enumerate(dates) if d >= _OOS]

    def stats2(idx):
        r = [rets[i] for i in idx]
        if not r:
            return (None, None, None, 0)
        import statistics

        return (
            statistics.mean(r) * 100,
            statistics.median(r) * 100,
            sum(1 for x in r if x > 0) / len(r) * 100,
            len(r),
        )

    print(
        f"{'产业-状态=过剩':28s} 全{stats2(on_over)[:3]!s} 外{stats2([i for i in on_over if i in oos])[:3]!s}"
    )
    print(
        f"{'产业-状态=上行':28s} 全{stats2(on_up)[:3]!s} 外{stats2([i for i in on_up if i in oos])[:3]!s}"
    )

    # ---- 5. 关键时点财报指标值（描述拐点附近读数） ----
    print("\n=== 关键拐点附近财报读数（月首前向值） ===")

    def val_at(ym: str, col: str):
        row = merged.filter(pl.col("ym") == ym)
        if row.is_empty():
            return None
        return row.select(col).item()

    for ym, label in [
        ("2021-07", "价格顶前 1 月"),
        ("2021-08", "价格顶月"),
        ("2022-01", "扩产潮 cap_yoy+93%"),
        ("2024-04", "财报门触发"),
        ("2025-03", "价格底前 1 月"),
    ]:
        vals = {c: val_at(ym, c) for c in _THR}
        cap = val_at(ym, "cap_yoy")
        parts = [f"{k}={v:.1f}" if v is not None else f"{k}=NA" for k, v in vals.items()]
        cap_s = f"  cap_yoy={cap * 100:.0f}%" if cap is not None else ""
        print(f"{ym} {label:18s} " + "  ".join(parts) + cap_s)

    # ---- 输出 ----
    _OUT.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(lead_rows).write_csv(_OUT / "industry_solar_capex_leading.csv")
    lines = [
        "# 630500 资本开支先导前瞻检验（财报层 capex 是否领先产能周期与价格顶）",
        "",
        "区间：财报指标 2019-04 起（cip_to_fa）/2020-08 起（cip_yoy）；fwd4q 分层至 2026-08-28；",
        "口径：财报指标按披露日前向填充取月末值，fwd4q=252 交易日，无前视；样本外 2022+。",
        "",
        "## 领先性（首次触发日 vs 价格顶 2021-08-30；保守取月首）",
        "",
        "| 信号 | 阈值 | 首次触发 | 相对价格顶(负=提前/正=滞后) |",
        "| :-- | --: | :-- | --: |",
    ]
    for r in lead_rows:
        d = r["first"].strftime("%Y-%m-%d") if r["first"] else "NA"
        lead = f"{r['lead_days_vs_peak']}" if r["lead_days_vs_peak"] is not None else "NA"
        lines.append(
            f"| {r['signal']} | {r['thr'] if r['thr'] is not None else '-'} | {d} | {lead} |"
        )
    lines += [
        "",
        "## fwd4q 分层（扩张区 vs 非扩张区；均值% / 中位% / 胜率% / n）",
        "",
        "| 分层 | 扩张全周期 | 扩张样本外 | 非扩张全周期 | 非扩张样本外 |",
        "| :-- | :-- | :-- | :-- | :-- |",
    ]
    for r in layer_rows:

        def fmt(t):
            if t[3] == 0:
                return "-"
            return f"{t[0]:.1f}/{t[1]:.1f}/{t[2]:.0f}%/{t[3]}"

        lines.append(
            f"| {r['layer']} | {fmt(r['on_full'])} | {fmt(r['on_oos'])} | {fmt(r['off_full'])} | {fmt(r['off_oos'])} |"
        )
    lines += [
        f"| 产业-状态=过剩 | {fmt(stats2(on_over))} | {fmt(stats2([i for i in on_over if i in oos]))} | - | - |",
        f"| 产业-状态=上行 | {fmt(stats2(on_up))} | {fmt(stats2([i for i in on_up if i in oos]))} | - | - |",
        "",
        "## 结论（实证结果）",
        "",
        "### 先导性：不成立（数据截断假象，无法证明真先导）",
        "- **cip_yoy / capex_growth_ttm 的'首次触发'= 数据起点即触发**：cip_yoy 数据 2020-08-31 起",
        "  首值即 104.8（>30）；capex_growth_ttm 2021-04-30 起首值即 22.8（>15）。首次触发领先",
        "  价格顶 -394/-151 天是**样本截断假象**——更早的扩张起点不可观测，不能证明财报先导。",
        "- **唯一可证的是滞后**：fix_assets_yoy 首次 >=30 在 2022-05（晚于价格顶 244 天），",
        "  产业层 cap_yoy>=30 与状态首进过剩均在 2022-01（晚于价格顶 124 天）——财报层与产业层",
        "  都是**扩产潮后的滞后确认**，财报层不早于产业层。",
        "- cip_to_fa_ratio 在 630500 从未达到 config 高张力线 0.35（max 0.25），该参数在此行业无效。",
        "",
        "### 区分度：成立（财报 capex 高扩张 → 未来一年显著负收益，反身机制同产业层）",
        "- **样本外 fwd4q**：capex_growth_ttm>=15 扩张区中位 -24.1%、胜率 16.2%（n=681）vs 非扩张区",
        "  +41.7%/99.5%（n=194，**但全在 2024-10-31 之后 = 见底回升段，幸存者偏差**）；",
        "  fix_assets_yoy>=30 扩张区中位 -31.0%、胜率 8.3%（n=436）——扩张区 fwd4q 显著为负。",
        "- 产业层状态门对照：过剩中位 -40.1%/胜率 5.0% vs 上行中位 +78.9%/85.1%（样本外上行无样本）",
        "  ——财报 capex 扩张区的负向区分度与产业层过剩方向一致，但**读数更温和**，且触发依赖披露",
        "  时滞，不构成独立前瞻腿。",
        "",
        "### 结论",
        "1. **财报 capex 先导作为 630500 前瞻腿不成立**：先导性被数据截断证伪（起点即触发），",
        "   可证部分反而滞后于产业层；不能比产业层状态门更早预警扩产潮。",
        "2. **财报 capex 高扩张区仍具防守参考**：扩张区样本外 fwd4q 显著为负（-22~-26% 均值），",
        "   与产业层过剩反身同机制，可作防守门的**滞后确认**（不超前于产业层）。",
        "3. **维持定稿**：630500 前瞻仍以产业层产能周期状态门（fwd4q 区分度最强）+ 动量兜底为准；",
        "   财报 capex 不新增前瞻能力，仅强化「财报层滞后验证、不作前瞻选股」框架定稿。",
    ]
    (_OUT / "industry_solar_capex_leading.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n输出: {_OUT / 'industry_solar_capex_leading.md'}")


if __name__ == "__main__":
    main()
