"""每日全景量化复盘生成脚本。

串联【宏观双轨风控】+【申万31行业中观特征】+【全天候大类资产配置】+【场内ETF报单】。
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_data.catalog import DataCatalog
from stock_reporting.interpretation.macro_risk.logic import evaluate_macro_risk
from stock_strategy.macro.assembly import assemble_macro_panel
from stock_strategy.pool.macro_all_weather import MacroAllWeatherStrategy

# 申万一级行业 -> 场内标准 ETF 映射池
_INDUSTRY_ETF_MAP: dict[str, str] = {
    "煤炭": "515220.SH (煤炭ETF)",
    "基础化工": "516020.SH (化工ETF)",
    "有色金属": "512400.SH (有色金属ETF)",
    "石油石化": "561360.SH (油气ETF)",
    "钢铁": "515210.SH (钢铁ETF)",
    "电子": "512480.SH (半导体芯片ETF)",
    "通信": "515880.SH (通信ETF)",
    "计算机": "512760.SH (芯片ETF)",
    "电力设备": "159840.SH (锂电池ETF)",
    "国防军工": "512660.SH (军工ETF)",
    "医药生物": "512010.SH (医药ETF)",
    "食品饮料": "512690.SH (酒ETF)",
    "非银金融": "512000.SH (券商ETF)",
    "银行": "512800.SH (银行ETF)",
    "农林牧渔": "159825.SZ (农业ETF)",
    "家用电器": "159996.SZ (家电ETF)",
    "汽车": "516110.SH (汽车ETF)",
}


def build_daily_review_payload(
    as_of: date | None = None,
    risk_parquet: Path | str = "data/analytics/macro_risk/latest/risk_factors.parquet",
    industry_parquet: Path | str = "data/analytics/industry_structure/latest/industry_factor_panel.parquet",
) -> dict[str, Any]:
    catalog = DataCatalog(data_source="tushare")
    panel = assemble_macro_panel(catalog=catalog, benchmark_symbol="000985.CSI")
    panel = panel.sort("trade_date").with_columns([
        pl.col("close").rolling_mean(window_size=20).alias("ma20")
    ])

    df_risk = pl.read_parquet(risk_parquet)

    if as_of is None:
        last_row = panel.tail(1).to_dicts()[0]
        as_of = last_row["trade_date"]
    else:
        sub = panel.filter(pl.col("trade_date") == as_of)
        if sub.is_empty():
            raise ValueError(f"日期 {as_of} 在宏观面板中不存在")
        last_row = sub.to_dicts()[0]

    risk_sub = df_risk.filter(pl.col("trade_date").cast(pl.Date) == as_of)
    if risk_sub.is_empty():
        last_risk = df_risk.sort("trade_date").tail(1).to_dicts()[0]
    else:
        last_risk = risk_sub.to_dicts()[0]

    full_row = {**last_risk, **last_row}
    macro_eval = evaluate_macro_risk(full_row)

    # 运行全天候宏观状态机
    close = float(full_row["close"])
    ma20 = float(full_row["ma20"])
    overheat = float(full_row["overheat_index"])
    panic = float(full_row["panic_index"])

    strat = MacroAllWeatherStrategy()
    if overheat > strat.overheat_threshold and close < ma20:
        regime_name = "相态 4: 泡沫破裂终极避险"
        weights = {"511010.SH (国债ETF)": 0.60, "518880.SH (黄金ETF)": 0.40}
        equity_cap = 0.0
    elif panic > strat.panic_threshold or (
        panic > strat.panic_entry_threshold
        and (
            full_row.get("repurchase_score", 0) >= 80
            or full_row.get("etf_flow_ratio_score", 0) >= 85
        )
    ):
        if close < ma20:
            regime_name = "相态 1: 恐慌冰点多主体托底左侧防踩踏"
            weights = {
                "510300.SH (300ETF)": 0.40,
                "510880.SH (红利ETF)": 0.30,
                "159915.SZ (创业板ETF)": 0.30,
            }
            equity_cap = 1.0
        else:
            regime_name = "相态 1: 恐慌出清右侧突破打满成长"
            weights = {"159915.SZ (创业板ETF)": 0.70, "510300.SH (300ETF)": 0.30}
            equity_cap = 1.0
    elif overheat > strat.overheat_threshold and close >= ma20:
        regime_name = "相态 3: 泡沫膨胀切红利与债金锁润"
        weights = {
            "510880.SH (红利ETF)": 0.40,
            "511010.SH (国债ETF)": 0.30,
            "518880.SH (黄金ETF)": 0.30,
        }
        equity_cap = 0.40
    elif panic > strat.panic_entry_threshold:
        regime_name = "相态 2: 估值大底跨资产均衡锁仓"
        weights = {
            "510880.SH (红利ETF)": 0.30,
            "510300.SH (300ETF)": 0.30,
            "159915.SZ (创业板ETF)": 0.20,
            "511010.SH (国债ETF)": 0.20,
        }
        equity_cap = 0.80
    else:
        regime_name = "相态 0: 常态中枢均衡区间"
        weights = {
            "510300.SH (300ETF)": 0.40,
            "510880.SH (红利ETF)": 0.30,
            "511010.SH (国债ETF)": 0.30,
        }
        equity_cap = 0.70

    # 读取申万 31 行业中观特征
    ind_df = pl.read_parquet(industry_parquet)
    latest_ind = ind_df.filter(pl.col("trade_date") == as_of)
    if latest_ind.is_empty():
        latest_dt = ind_df["trade_date"].max()
        latest_ind = ind_df.filter(pl.col("trade_date") == latest_dt)

    top_comp = latest_ind.sort("composite_industry_score", descending=True).head(5).to_dicts()
    top_mom = latest_ind.sort("ind_momentum", descending=True).head(5).to_dicts()
    veto_crowd = (
        latest_ind.filter(pl.col("ind_crowding") >= 80.0)
        .sort("ind_crowding", descending=True)
        .to_dicts()
    )
    top_scissors = latest_ind.sort("ind_scissors", descending=True).head(5).to_dicts()

    return {
        "as_of": as_of,
        "close": close,
        "ma20": ma20,
        "diff_ma20": close - ma20,
        "diff_ma20_pct": (close / ma20 - 1.0) * 100.0,
        "overheat": overheat,
        "panic": panic,
        "regime_name": regime_name,
        "equity_cap": equity_cap,
        "weights": weights,
        "macro_eval": macro_eval,
        "full_row": full_row,
        "top_comp": top_comp,
        "top_mom": top_mom,
        "veto_crowd": veto_crowd,
        "top_scissors": top_scissors,
    }


def render_markdown_review(data: dict[str, Any]) -> str:
    as_of = data["as_of"]
    close = data["close"]
    ma20 = data["ma20"]
    diff_pct = data["diff_ma20_pct"]
    ovr = data["overheat"]
    pan = data["panic"]
    regime = data["regime_name"]
    weights = data["weights"]
    eval_res = data["macro_eval"]

    lines = []
    lines.append(f"# 每日全景量化复盘研报 ({as_of})\n")
    lines.append("## 一、宏观风控大盘全景 (Macro Regime & Risk Gate)\n")
    lines.append(
        f"- **中证全指收盘**：`{close:.2f}` 点 | **20日均线 (MA20)**：`{ma20:.2f}` 点（处于均线 **{'+' if diff_pct>=0 else ''}{diff_pct:.2f}%**）"
    )
    lines.append(
        f"- **双轨制雷达**：狂热指数 (Overheat) = **`{ovr:.1f}`** {'🔴' if ovr>=65 else '⚪'} | 恐慌指数 (Panic) = **`{pan:.1f}`** {'🟢' if pan>=65 else '⚪'}"
    )
    lines.append(f"- **当前宏观相态定位**：**【{regime}】**")
    lines.append(
        f"- **研报定性与建议**：\n  > {eval_res['status']}\n  {eval_res['advice']}\n"
    )

    lines.append("## 二、全天候大类资产配置与 14:50 调仓指令 (Portfolio Allocation)\n")
    lines.append("| 资产大类 | 目标标的 ETF | 建议目标权重 | 核心配置逻辑与功能 |")
    lines.append("| :--- | :--- | :---: | :--- |")
    for k, w in weights.items():
        if "国债" in k:
            cat_name = "固收避险"
            logic = "无风险流动性底座，防范权益系统性波动"
        elif "黄金" in k:
            cat_name = "商品避险"
            logic = "对冲全球地缘冲突与货币信用风险"
        elif "红利" in k:
            cat_name = "权益防守"
            logic = "高股息锁润，抗跌与现金流收益"
        else:
            cat_name = "权益成长"
            logic = "主升浪高贝塔进攻弹性"
        lines.append(f"| **{cat_name}** | `{k}` | **`{w:.1%}`** | {logic} |")
    lines.append("")

    lines.append("## 三、申万 31 行业中观特征与主线格局 (Industry Allocation)\n")
    lines.append("### 1. 动量领涨主线 Top 5")
    lines.append("| 申万行业 | 代码 | 动量分位 | 供需剪刀差 | 拥挤度 | 对应场内 ETF 映射 |")
    lines.append("| :--- | :---: | :---: | :---: | :---: | :--- |")
    for r in data["top_mom"]:
        name = r["industry_name"]
        etf_code = _INDUSTRY_ETF_MAP.get(name, "—")
        lines.append(
            f"| **{name}** | `{r['industry_code']}` | `{r['ind_momentum']:.1f}` | `{r['ind_scissors']:.1f}` | `{r['ind_crowding']:.1f}` | `{etf_code}` |"
        )
    lines.append("")

    lines.append("### 2. 供需剪刀差 / 基本面改善 Top 5")
    lines.append("| 申万行业 | 代码 | 剪刀差分位 | 估值分位 | 拥挤度 | 对应场内 ETF 映射 |")
    lines.append("| :--- | :---: | :---: | :---: | :---: | :--- |")
    for r in data["top_scissors"]:
        name = r["industry_name"]
        etf_code = _INDUSTRY_ETF_MAP.get(name, "—")
        lines.append(
            f"| **{name}** | `{r['industry_code']}` | `{r['ind_scissors']:.1f}` 🟢 | `{r['ind_valuation']:.1f}` | `{r['ind_crowding']:.1f}` | `{etf_code}` |"
        )
    lines.append("")

    if data["veto_crowd"]:
        lines.append("### 3. ⚠️ 高拥挤一票否决警报名单 (防抱团瓦解)")
        lines.append("| 申万行业 | 代码 | 拥挤度分位 | 动量分位 | 风控警示与操作建议 |")
        lines.append("| :--- | :---: | :---: | :---: | :--- |")
        for r in data["veto_crowd"]:
            name = r["industry_name"]
            lines.append(
                f"| **{name}** | `{r['industry_code']}` | **`{r['ind_crowding']:.1f}`** 🔴 | `{r['ind_momentum']:.1f}` | **【严禁追高/一票否决】** 成交额占比达历史极值，防短线踩踏。 |"
            )
        lines.append("")

    lines.append("## 四、次日关键临界防线与操作纪律 (Action Rules)\n")
    lines.append(
        f"1. **生命线刚性防守**：中证全指 20 日生命线位于 **`{ma20:.2f}`**（当前相距 `{diff_pct:+.2f}%`）；"
    )
    lines.append(
        f"2. **多头守线纪律**：若收盘价持续维持在 `{ma20:.2f}` 上方，严格维持 **【{regime}】**；"
    )
    lines.append(
        f"3. **破位断电熔断**：一旦盘尾放量跌破 `{ma20:.2f}`，无条件单日拉闸触发 **【相态 4：0% 权益 + 60% 国债 ETF + 40% 黄金 ETF】** 进防空洞规避多杀多踩踏。"
    )

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="生成每日全景量化复盘研报")
    parser.add_argument(
        "--as-of", type=date.fromisoformat, default=None, help="基准日期 YYYY-MM-DD"
    )
    parser.add_argument("--output", type=Path, default=None, help="输出 Markdown 文件路径")
    args = parser.parse_args()

    data = build_daily_review_payload(as_of=args.as_of)
    md = render_markdown_review(data)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(md, encoding="utf-8")
        print(f"✅ 复盘研报已生成并落盘至: {args.output}")
    else:
        print(md)


if __name__ == "__main__":
    main()
