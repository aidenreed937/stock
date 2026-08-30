"""产业趋势跟踪盘尾实时信号推演与 ETF 报单指令生成引擎。

面向周期尺度全球产业趋势（AI 算力 / 新能源）的实盘巡检：
1. 加载产业趋势因子面板（三层共振 + 现实景气 + 拥挤度 + 环比趋势确认）；
2. 执行产业趋势跟踪策略（季度调仓追趋势确认，方向层象限过滤）；
3. 目标行业映射为场内 ETF（复用 industry_rotation 的 industry_etf_map）；
4. 输出报单卡片（含方向层状态：全球共振候选池的方向分）。

与行业轮动 live（industry/live.py）的区别：
- 数据源：产业趋势因子面板（industry_trend_panel）而非 5 大中观因子面板；
- 方向层状态展示：候选池（电子/通信/计算机/电力设备/有色）的 direction_score；
- 参考现价：从 fund_daily 最新收盘读取（非 mock）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from stock_analytics.pipelines.industry_trend import load_latest_industry_trend_panel
from stock_core.utils.logger import logger
from stock_data.catalog import DataCatalog
from stock_strategy.industry.live import IndustryLiveOrderInstruction, load_industry_etf_map
from stock_strategy.industry.report import load_all_industry_strategy_specs
from stock_strategy.pool import create_strategy

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_TREND_CONFIG = Path("config/strategy/industry_trend_tracking.yaml")
_ETF_MAP_CONFIG = Path("config/strategy/industry_rotation.yaml")


@dataclass(frozen=True)
class TrendLiveInspectionResult:
    """产业趋势跟踪盘尾巡检结果容器。"""

    strategy_key: str
    strategy_class: str
    as_of_time: datetime
    has_rebalance: bool
    latest_date: str
    candidate_direction: dict[str, float]  # 候选池行业 → 方向分
    instructions: list[IndustryLiveOrderInstruction]
    markdown_card: str


def inspect_live_industry_trend_signal(
    *,
    strategy_key: str = "industry_trend_momentum",
    config_path: Path | str = _TREND_CONFIG,
    etf_map_config: Path | str = _ETF_MAP_CONFIG,
    factor_root: Path | str = "data/analytics/industry_trend",
    total_capital: float = 100_000.0,
    data_source: str = "tushare",
) -> TrendLiveInspectionResult:
    """执行产业趋势跟踪盘尾信号推演与 ETF 报单指令生成。"""
    cfg_p = Path(config_path)
    specs = load_all_industry_strategy_specs(cfg_p)
    if strategy_key not in specs:
        raise ValueError(f"未找到产业趋势策略配置: {strategy_key}，可选: {list(specs.keys())}")

    spec = specs[strategy_key]
    cls_name = str(spec["strategy_class"])
    etf_map = load_industry_etf_map(etf_map_config)

    # 1. 加载产业趋势因子面板
    _run_dir, panel, _manifest = load_latest_industry_trend_panel(factor_root)
    if panel.is_empty():
        raise RuntimeError("产业趋势因子面板为空，无法推演信号")
    panel = panel.sort(["trade_date", "industry_code"])
    latest_date = panel["trade_date"].max()

    # 2. 实例化策略并推演
    kwargs = {
        k: v
        for k, v in spec.items()
        if k not in ("strategy_class", "friction", "description", "name")
    }
    strat = create_strategy(cls_name, **kwargs)
    strat.on_init()
    signals = strat.on_bar(panel)
    has_rebalance = len(signals) > 0

    # 3. 候选池方向层状态（每个全球共振行业最近可用方向分；中性 50 为数据缺口）
    latest_rows = panel.filter(pl.col("trade_date") == latest_date)
    ind_names: dict[str, str] = {}
    for r in latest_rows.select(["industry_code", "industry_name"]).to_dicts():
        ind_names[str(r["industry_code"])] = str(r.get("industry_name", r["industry_code"]))

    candidate_direction: dict[str, float] = {}
    for code in panel["industry_code"].unique().to_list():
        sub = (
            panel.filter(pl.col("industry_code") == code)
            .filter((pl.col("direction_score") - 50.0).abs() > 1e-6)
            .sort("trade_date")
        )
        if not sub.is_empty():
            candidate_direction[code] = round(float(sub["direction_score"][-1]), 1)

    # 4. 参考现价：ETF 最新收盘
    catalog = DataCatalog(data_source=data_source)
    etf_codes = sorted({v["symbol"] for v in etf_map.values() if isinstance(v, dict)})
    latest_prices: dict[str, float] = {}
    try:
        fund = catalog.load_dataset("fund_daily", symbols=etf_codes)
        if not fund.is_empty():
            for row in (
                fund.group_by("symbol").agg(pl.col("trade_date").max().alias("d")).to_dicts()
            ):
                sym = str(row["symbol"])
                price_rows = fund.filter(
                    (pl.col("symbol") == sym) & (pl.col("trade_date") == row["d"])
                )
                if not price_rows.is_empty():
                    latest_prices[sym] = float(price_rows["close"][0])
    except Exception as exc:
        logger.warning(f"读取 ETF 最新价格失败，使用占位价: {exc}")

    # 5. 生成报单指令
    instructions: list[IndustryLiveOrderInstruction] = []
    for sig in signals:
        code = sig.symbol
        ind_name = ind_names.get(code, code)
        etf_info = etf_map.get(code, {"symbol": code, "name": ind_name})
        etf_code = etf_info.get("symbol", code)
        etf_name = etf_info.get("name", ind_name)

        t_weight = float(sig.target_weight or 0.0)
        t_amount = total_capital * t_weight
        ref_price = latest_prices.get(etf_code, 1.0)
        lots = int(t_amount / (ref_price * 100)) if ref_price > 0 and t_amount > 0 else 0

        instructions.append(
            IndustryLiveOrderInstruction(
                industry_code=code,
                industry_name=ind_name,
                etf_symbol=etf_code,
                etf_name=etf_name,
                direction="BUY" if t_weight > 0 else "CLOSE",
                target_weight=round(t_weight, 4),
                current_weight=0.0,
                delta_weight=round(t_weight, 4),
                latest_price=ref_price,
                target_amount=round(t_amount, 2),
                recommended_lots=lots,
                reason=sig.reason,
            )
        )

    now_time = datetime.now(_SHANGHAI_TZ)
    card_md = _render_trend_markdown_card(
        strategy_key=strategy_key,
        strategy_class=cls_name,
        as_of_time=now_time,
        latest_date=str(latest_date),
        has_rebalance=has_rebalance,
        candidate_direction=candidate_direction,
        instructions=instructions,
        total_capital=total_capital,
    )

    return TrendLiveInspectionResult(
        strategy_key=strategy_key,
        strategy_class=cls_name,
        as_of_time=now_time,
        has_rebalance=has_rebalance,
        latest_date=str(latest_date),
        candidate_direction=candidate_direction,
        instructions=instructions,
        markdown_card=card_md,
    )


def _render_trend_markdown_card(
    strategy_key: str,
    strategy_class: str,
    as_of_time: datetime,
    latest_date: str,
    has_rebalance: bool,
    candidate_direction: dict[str, float],
    instructions: list[IndustryLiveOrderInstruction],
    total_capital: float,
) -> str:
    """生成产业趋势跟踪盘尾实盘调仓指令卡片。"""
    time_str = as_of_time.strftime("%Y-%m-%d %H:%M:%S")
    status = "🚨 【触发调仓】" if has_rebalance else "🟢 【维持现状】"

    # 候选池方向层状态
    dir_rows = [
        f"| `{code}` | **{d:.1f}** |"
        for code, d in sorted(candidate_direction.items(), key=lambda x: -x[1])
    ]
    dir_table = (
        "| 全球共振候选行业 | 方向分 (0-100) |\n| :--- | :---: |\n" + "\n".join(dir_rows)
        if dir_rows
        else "候选池方向层数据缺失。"
    )

    inst_rows = []
    for inst in instructions:
        inst_rows.append(
            f"| `{inst.industry_code}` ({inst.industry_name}) | **{inst.etf_symbol}** ({inst.etf_name}) | **{inst.direction}** | {inst.target_weight * 100:.1f}% | ¥{inst.target_amount:,.0f} | **{inst.recommended_lots} 手** | {inst.reason} |"
        )
    inst_table = (
        "| 申万行业 | 对应场内 ETF | 调仓方向 | 目标权重 | 目标金额 | 建议下单手数 | 调仓理由 |\n"
        "| :--- | :--- | :---: | :---: | :---: | :---: | :--- |\n" + "\n".join(inst_rows)
        if inst_rows
        else "今日无调仓指令，保持当前产业配置。"
    )

    return f"""# 产业趋势跟踪 盘尾实盘巡检卡片

> **巡检时间**: `{time_str}` | **因子基准日**: `{latest_date}` | **总资金规模**: `¥{total_capital:,.2f}`
> **策略标识**: `{strategy_key}` (`{strategy_class}`) | **调仓状态**: **{status}**

---

## 🌍 方向层状态（全球共振候选池）

{dir_table}

---

## 🎯 今日目标配置与 ETF 报单指令

{inst_table}

---
💡 **执行提示**：产业趋势跟踪为季度尺度，调仓指令在季度确认日盘尾通过对应场内 ETF 申报；
注意规避 ETF 盘中大幅折溢价 (>0.3%)。方向层防守：全球方向高位 × 非量价齐升行业已被策略过滤。
"""


__all__ = [
    "TrendLiveInspectionResult",
    "inspect_live_industry_trend_signal",
]
